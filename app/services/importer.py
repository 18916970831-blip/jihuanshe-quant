import json
from collections import Counter
from datetime import date, datetime
from io import BytesIO

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, Bid, Card, ImportLog, Trade
from app.services.cleaning import (
    KNOWN_CARDS,
    canonicalize_code,
    detect_bundle,
    extract_card_code,
    gem_rate,
    is_bid_sheet,
    map_headers,
    normalize_grade,
    parse_date,
    parse_price,
    parse_time,
)


def _cell(row, idx):
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def ensure_card(db: Session, card_code: str, fallback_name: str | None, series_hint: str | None) -> Card:
    card = db.get(Card, card_code)
    known = KNOWN_CARDS.get(card_code, {})
    if card is None:
        total = known.get("psa_population_total")
        psa10 = known.get("psa_population_10")
        card = Card(
            card_code=card_code,
            card_name=known.get("card_name") or fallback_name or card_code,
            card_series=known.get("card_series") or series_hint,
            card_type=known.get("card_type"),
            region=known.get("region"),
            date_added=date.today(),
            is_active=True,
            psa_population_total=total,
            psa_population_10=psa10,
            psa_gem_rate=gem_rate(total, psa10),
            external_notes=known.get("external_notes"),
        )
        db.add(card)
        db.flush()
        return card
    if card.psa_population_total is None and known.get("psa_population_total"):
        card.psa_population_total = known["psa_population_total"]
        card.psa_population_10 = known.get("psa_population_10")
        card.psa_gem_rate = gem_rate(card.psa_population_total, card.psa_population_10)
    if not card.external_notes and known.get("external_notes"):
        card.external_notes = known["external_notes"]
    if not card.card_series and (known.get("card_series") or series_hint):
        card.card_series = known.get("card_series") or series_hint
    return card


def _series_hint(sheet_name: str, card_code: str) -> str:
    known = KNOWN_CARDS.get(card_code, {})
    if known.get("card_series"):
        return known["card_series"]
    if "海贼王" in sheet_name or "航海王" in sheet_name:
        return "海贼王"
    return "宝可梦"


def _duplicate(db: Session, card_code: str, when: datetime, price: float, grade: str) -> bool:
    stmt = select(Trade.id).where(
        Trade.card_code == card_code,
        Trade.trade_datetime == when,
        Trade.price == price,
        Trade.grade == grade,
    )
    return db.execute(stmt).first() is not None


def refresh_suspicious(db: Session, card_code: str):
    rows = db.scalars(
        select(Trade).where(Trade.card_code == card_code, Trade.grade == "PSA10", Trade.is_bundle.is_(False))
    ).all()
    if len(rows) < 8:
        for row in rows:
            row.is_suspicious = False
        return
    prices = [row.price for row in rows]
    mean = sum(prices) / len(prices)
    var = sum((p - mean) ** 2 for p in prices) / (len(prices) - 1)
    std = var**0.5
    if std == 0:
        for row in rows:
            row.is_suspicious = False
        return
    limit = mean + 3 * std
    for row in rows:
        row.is_suspicious = row.price > limit


def _import_trades(db: Session, sheet_name: str, rows: list, today: date) -> dict:
    header = rows[0]
    mapping = map_headers(header)
    result = {
        "sheet": sheet_name,
        "kind": "trades",
        "card_code": None,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
        "warnings": [],
    }
    missing = [field for field in ("name", "date", "price") if field not in mapping]
    if missing:
        result["failed"] = max(len(rows) - 1, 0)
        result["errors"].append({"row": 1, "reason": f"缺少列：{'、'.join(missing)}"})
        return result

    card_code = extract_card_code(sheet_name)
    names = []
    pending = []
    for offset, row in enumerate(rows[1:], start=2):
        if row is None or all(cell is None or str(cell).strip() == "" for cell in row):
            continue
        name = _cell(row, mapping.get("name"))
        name = "" if name is None else str(name).strip()
        if not name:
            result["failed"] += 1
            _push(result["errors"], {"row": offset, "reason": "缺少卡牌名称"})
            continue
        trade_date = parse_date(_cell(row, mapping["date"]))
        if trade_date is None:
            result["failed"] += 1
            _push(result["errors"], {"row": offset, "reason": "日期无法识别"})
            continue
        price = parse_price(_cell(row, mapping["price"]))
        if price is None:
            result["failed"] += 1
            _push(result["errors"], {"row": offset, "reason": "价格不是数字"})
            continue
        if price <= 0:
            result["failed"] += 1
            _push(result["errors"], {"row": offset, "reason": "价格必须大于 0"})
            continue
        grade = normalize_grade(_cell(row, mapping.get("grade")))
        notes_raw = _cell(row, mapping.get("notes"))
        notes = None if notes_raw is None or str(notes_raw).strip() == "" else str(notes_raw).strip()
        if trade_date > today:
            _push(result["warnings"], f"第 {offset} 行日期晚于今天")
        names.append(name)
        pending.append((offset, name, trade_date, parse_time(_cell(row, mapping.get("time"))), price, grade, notes))

    if card_code is None and names:
        card_code = extract_card_code(names[0]) or sheet_name.strip()[:50]
    result["card_code"] = card_code
    if not card_code:
        result["failed"] += len(pending)
        result["errors"].append({"row": 1, "reason": "无法识别卡牌代码"})
        return result

    clean_names = [name for name in names if "套出" not in name] or names
    fallback = Counter(clean_names).most_common(1)[0][0] if clean_names else card_code
    ensure_card(db, card_code, fallback, _series_hint(sheet_name, card_code))
    seen = set()

    for offset, name, trade_date, trade_time, price, grade, notes in pending:
        when = datetime.combine(trade_date, trade_time)
        key = (when, price, grade)
        if key in seen or _duplicate(db, card_code, when, price, grade):
            result["skipped"] += 1
            continue
        seen.add(key)
        db.add(
            Trade(
                card_code=card_code,
                card_name=name,
                trade_date=trade_date,
                trade_time=trade_time,
                trade_datetime=when,
                price=price,
                grade=grade,
                is_bundle=detect_bundle(name, notes),
                source="集换社",
                notes=notes,
            )
        )
        result["success"] += 1
    if result["success"]:
        db.flush()
        refresh_suspicious(db, card_code)
    return result


def _import_bids(db: Session, sheet_name: str, rows: list, bid_date: date) -> dict:
    result = {
        "sheet": sheet_name,
        "kind": "bids",
        "card_code": None,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
        "warnings": [],
    }
    for offset, row in enumerate(rows[1:], start=2):
        if not row or row[0] in (None, ""):
            continue
        code = canonicalize_code(str(row[0]).strip())
        code = extract_card_code(code) or code
        numbers = []
        for cell in row[1:]:
            price = parse_price(cell)
            if price is not None and price > 0:
                numbers.append(price)
        if not numbers:
            result["failed"] += 1
            _push(result["errors"], {"row": offset, "reason": "没有有效竞价"})
            continue
        ensure_card(db, code, KNOWN_CARDS.get(code, {}).get("card_name"), _series_hint(sheet_name, code))
        existing = db.scalars(select(Bid).where(Bid.card_code == code, Bid.bid_date == bid_date)).first()
        payload = dict(
            highest_bid=numbers[0],
            second_highest_bid=numbers[1] if len(numbers) > 1 else None,
            bid_count=len(numbers),
            ladder_json=json.dumps(numbers),
        )
        if existing:
            for key, value in payload.items():
                setattr(existing, key, value)
            result["skipped"] += 1
        else:
            db.add(Bid(card_code=code, bid_date=bid_date, **payload))
            result["success"] += 1
    return result


def _push(bucket: list, item, limit: int = 30):
    if len(bucket) < limit:
        bucket.append(item)


def import_workbook(db: Session, content: bytes, filename: str) -> dict:
    try:
        workbook = openpyxl.load_workbook(BytesIO(content), data_only=True, read_only=True)
    except Exception as exc:
        raise ValueError(f"无法读取 Excel：{exc}") from exc

    today = date.today()
    sheet_results = []
    trade_dates: list[date] = []
    bid_sheets = []
    for sheet in workbook.worksheets:
        rows = [tuple(row) for row in sheet.iter_rows(values_only=True)]
        if not rows:
            continue
        if is_bid_sheet(sheet.title, rows[0]):
            bid_sheets.append((sheet.title, rows))
            continue
        result = _import_trades(db, sheet.title, rows, today)
        sheet_results.append(result)
        if result["card_code"]:
            latest = db.scalars(
                select(Trade.trade_date).where(Trade.card_code == result["card_code"]).order_by(Trade.trade_date.desc())
            ).first()
            if latest:
                trade_dates.append(latest)
    bid_date = max(trade_dates) if trade_dates else today
    for title, rows in bid_sheets:
        sheet_results.append(_import_bids(db, title, rows, bid_date))
    workbook.close()

    summary = {
        "filename": filename,
        "success": sum(item["success"] for item in sheet_results),
        "failed": sum(item["failed"] for item in sheet_results),
        "skipped": sum(item["skipped"] for item in sheet_results),
        "sheets": sheet_results,
        "bid_date": bid_date.isoformat(),
    }
    db.add(
        ImportLog(
            filename=filename,
            success_count=summary["success"],
            failed_count=summary["failed"],
            skipped_count=summary["skipped"],
            detail_json=json.dumps(summary, ensure_ascii=False),
        )
    )
    db.add(AuditLog(action="excel_import", detail=f"{filename} 成功 {summary['success']} / 失败 {summary['failed']} / 跳过 {summary['skipped']}"))
    db.commit()
    return summary
