import json
from datetime import date, datetime, time
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.access import is_readonly
from app.database import get_db
from app.models import Alert, AuditLog, Bid, Card, Event, ImportLog, Trade
from app.schemas import BidIn, CardIn, CardPatch, EventIn, TradeIn
from app.services.alerts import public_alert, scan_alerts
from app.services.catalog import active_cards, analyze_card, dump_trade, market_as_of, summarize
from app.services.publish import publish_status, schedule_publish
from app.services.cleaning import EVENT_TYPES, detect_bundle, gem_rate, normalize_grade
from app.services.importer import ensure_card, import_workbook, refresh_suspicious
from app.services.report import build_report, render_docx, render_xlsx

router = APIRouter(prefix="/api")


def _audit(db: Session, action: str, detail: str):
    db.add(AuditLog(action=action, detail=detail))


def _card_out(card: Card) -> dict:
    return {
        "card_code": card.card_code,
        "card_name": card.card_name,
        "card_series": card.card_series,
        "card_type": card.card_type,
        "region": card.region,
        "date_added": card.date_added.isoformat() if card.date_added else None,
        "is_active": card.is_active,
        "psa_population_total": card.psa_population_total,
        "psa_population_10": card.psa_population_10,
        "psa_gem_rate": card.psa_gem_rate,
        "external_notes": card.external_notes,
    }


@router.get("/status")
def status(request: Request, db: Session = Depends(get_db)):
    as_of = market_as_of(db)
    return {
        "cards": db.scalar(select(func.count()).select_from(Card)) or 0,
        "trades": db.scalar(select(func.count()).select_from(Trade)) or 0,
        "alerts_open": db.scalar(select(func.count()).select_from(Alert).where(Alert.is_active.is_(True), Alert.is_read.is_(False))) or 0,
        "as_of": as_of.isoformat() if as_of else None,
        "readonly": is_readonly(request),
        "sync": publish_status(),
    }


@router.post("/sync")
def sync_public():
    from app.services.publish import pull_once

    return pull_once()


@router.get("/meta")
def meta():
    return {
        "grades": ["PSA10", "PSA9", "PSA8", "PCG10", "PCG9", "BGS10", "其他"],
        "event_types": EVENT_TYPES,
        "impacts": ["高", "中", "低"],
        "series": ["宝可梦", "海贼王", "足球", "网球", "F1", "其他"],
    }


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    as_of = market_as_of(db)
    cards = [summarize(analyze_card(db, card, end=as_of)) for card in active_cards(db)]
    alerts = [public_alert(row) for row in db.scalars(select(Alert).where(Alert.is_active.is_(True)).order_by(Alert.level.desc(), Alert.created_at.desc())).all()]
    events = [_event_out(row) for row in db.scalars(select(Event).order_by(Event.event_date.desc()).limit(8)).all()]
    briefing = []
    ranked = sorted([card for card in cards if card["has_psa10"]], key=lambda item: (item["advice"] or {}).get("score") or 0, reverse=True)
    if ranked:
        briefing.append(f"当前样本截止 {as_of.isoformat() if as_of else '—'}，{len(ranked)} 张卡有 PSA10 成交。")
        lead = ranked[0]
        briefing.append(f"规则排序首位是 {lead['card_name']}，建议{lead['advice']['action']}。")
        hot = [card for card in ranked if (card["return_7d"] or 0) >= 0.20]
        if hot:
            briefing.append("7 日涨幅超过 20%：" + "、".join(card["card_name"] for card in hot) + "。")
        weak_volume = [card for card in ranked if card["divergence"] == "价升量缩"]
        if weak_volume:
            briefing.append("价升量缩：" + "、".join(card["card_name"] for card in weak_volume) + "。")
    else:
        briefing.append("还没有可计算的 PSA10 成交。先导入集换社 Excel，或手工录入一笔。")
    return {"as_of": as_of.isoformat() if as_of else None, "cards": cards, "alerts": alerts[:12], "events": events, "briefing": briefing}


@router.get("/cards")
def list_cards(db: Session = Depends(get_db)):
    cards = db.scalars(select(Card).order_by(Card.card_code)).all()
    return [_card_out(card) for card in cards]


@router.post("/cards")
def create_card(payload: CardIn, db: Session = Depends(get_db)):
    if db.get(Card, payload.card_code):
        raise HTTPException(409, "卡牌代码已存在")
    card = Card(
        card_code=payload.card_code.strip(),
        card_name=payload.card_name.strip(),
        card_series=payload.card_series,
        card_type=payload.card_type,
        region=payload.region,
        date_added=date.today(),
        is_active=True,
        psa_population_total=payload.psa_population_total,
        psa_population_10=payload.psa_population_10,
        psa_gem_rate=gem_rate(payload.psa_population_total, payload.psa_population_10),
        external_notes=payload.external_notes,
    )
    db.add(card)
    _audit(db, "create_card", card.card_code)
    db.commit()
    schedule_publish()
    return _card_out(card)


@router.patch("/cards/{card_code}")
def patch_card(card_code: str, payload: CardPatch, db: Session = Depends(get_db)):
    card = db.get(Card, card_code)
    if card is None:
        raise HTTPException(404, "找不到卡牌")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(card, key, value)
    if "psa_population_total" in data or "psa_population_10" in data:
        card.psa_gem_rate = gem_rate(card.psa_population_total, card.psa_population_10)
    _audit(db, "update_card", card_code)
    db.commit()
    schedule_publish()
    return _card_out(card)


@router.get("/cards/{card_code}/analysis")
def card_analysis(
    card_code: str,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
):
    card = db.get(Card, card_code)
    if card is None:
        raise HTTPException(404, "找不到卡牌")
    return analyze_card(db, card, start=start, end=end)


@router.get("/compare")
def compare(db: Session = Depends(get_db)):
    as_of = market_as_of(db)
    rows = []
    for card in active_cards(db):
        metrics = analyze_card(db, card, end=as_of)
        points = []
        base = None
        for point in metrics.get("series") or []:
            if not point.get("traded") or point.get("median") in (None, 0):
                continue
            if base is None:
                base = point["median"]
            points.append({"date": point["date"], "median": point["median"], "index": round(point["median"] / base * 100, 2)})
        rows.append({**summarize(metrics), "normalized": points, "population": metrics.get("population")})
    return {"as_of": as_of.isoformat() if as_of else None, "cards": rows}


@router.get("/trades")
def list_trades(
    card_code: str | None = None,
    grade: str | None = None,
    bundle: bool | None = None,
    limit: int = Query(80, le=500),
    db: Session = Depends(get_db),
):
    stmt = select(Trade).order_by(Trade.trade_datetime.desc(), Trade.id.desc())
    if card_code:
        stmt = stmt.where(Trade.card_code == card_code)
    if grade:
        stmt = stmt.where(Trade.grade == grade)
    if bundle is not None:
        stmt = stmt.where(Trade.is_bundle.is_(bundle))
    rows = db.scalars(stmt.limit(limit)).all()
    return [dump_trade(row) for row in rows]


@router.post("/trades")
def create_trade(payload: TradeIn, force: bool = False, db: Session = Depends(get_db)):
    card = db.get(Card, payload.card_code)
    if card is None:
        raise HTTPException(404, "请先在卡牌库里添加这张卡")
    grade = normalize_grade(payload.grade)
    trade_time = payload.trade_time or time(0, 0, 0)
    when = datetime.combine(payload.trade_date, trade_time)
    duplicate = db.scalars(
        select(Trade).where(
            Trade.card_code == card.card_code,
            Trade.trade_datetime == when,
            Trade.price == payload.price,
            Trade.grade == grade,
        )
    ).first()
    if duplicate and not force:
        raise HTTPException(409, "同一张卡、同一时间、同一价格已有记录。确认后可强制保存。")
    row = Trade(
        card_code=card.card_code,
        card_name=card.card_name,
        trade_date=payload.trade_date,
        trade_time=trade_time,
        trade_datetime=when,
        price=payload.price,
        grade=grade,
        is_bundle=payload.mark_bundle or detect_bundle(card.card_name, payload.notes),
        source=payload.source or "手动录入",
        notes=payload.notes,
    )
    db.add(row)
    db.flush()
    refresh_suspicious(db, card.card_code)
    _audit(db, "create_trade", f"{card.card_code} {payload.price} {grade}")
    db.commit()
    schedule_publish()
    db.refresh(row)
    day_rows = db.scalars(select(Trade).where(Trade.card_code == card.card_code, Trade.trade_date == payload.trade_date, Trade.grade == "PSA10", Trade.is_bundle.is_(False))).all()
    prices = sorted(item.price for item in day_rows)
    median = prices[len(prices) // 2] if prices else None
    if prices and len(prices) % 2 == 0:
        median = (prices[len(prices) // 2 - 1] + prices[len(prices) // 2]) / 2
    return {"trade": dump_trade(row), "today": {"count": len(prices), "median": median}}


@router.delete("/trades/{trade_id}")
def delete_trade(trade_id: str, db: Session = Depends(get_db)):
    row = db.get(Trade, trade_id)
    if row is None:
        raise HTTPException(404, "找不到成交")
    code = row.card_code
    db.delete(row)
    db.flush()
    refresh_suspicious(db, code)
    _audit(db, "delete_trade", trade_id)
    db.commit()
    schedule_publish()
    return {"ok": True}


@router.post("/import")
def import_excel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    name = file.filename or "upload.xlsx"
    if not name.lower().endswith(".xlsx"):
        raise HTTPException(400, "只接收 .xlsx 文件")
    content = file.file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, "文件超过 20MB")
    try:
        summary = import_workbook(db, content, name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    scan_alerts(db)
    schedule_publish()
    return summary


@router.get("/imports")
def list_imports(db: Session = Depends(get_db)):
    rows = db.scalars(select(ImportLog).order_by(ImportLog.created_at.desc()).limit(12)).all()
    result = []
    for row in rows:
        result.append(
            {
                "id": row.id,
                "filename": row.filename,
                "success": row.success_count,
                "failed": row.failed_count,
                "skipped": row.skipped_count,
                "created_at": row.created_at.isoformat(timespec="seconds"),
            }
        )
    return result


@router.get("/report")
def report(db: Session = Depends(get_db)):
    return build_report(db)


@router.get("/report.docx")
def report_docx(db: Session = Depends(get_db)):
    payload = render_docx(build_report(db))
    filename = quote("集换社量化分析报告.docx")
    return Response(
        payload,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/report.xlsx")
def report_xlsx(db: Session = Depends(get_db)):
    payload = render_xlsx(build_report(db))
    filename = quote("集换社量化指标.xlsx")
    return Response(
        payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/alerts")
def list_alerts(active_only: bool = True, db: Session = Depends(get_db)):
    stmt = select(Alert).order_by(Alert.is_active.desc(), Alert.created_at.desc())
    if active_only:
        stmt = stmt.where(Alert.is_active.is_(True))
    return [public_alert(row) for row in db.scalars(stmt.limit(100)).all()]


@router.post("/alerts/scan")
def rescan(db: Session = Depends(get_db)):
    rows = scan_alerts(db)
    _audit(db, "scan_alerts", f"{len(rows)} 条有效告警")
    db.commit()
    return [public_alert(row) for row in rows]


@router.post("/alerts/{alert_id}/read")
def read_alert(alert_id: str, db: Session = Depends(get_db)):
    row = db.get(Alert, alert_id)
    if row is None:
        raise HTTPException(404, "找不到告警")
    row.is_read = True
    db.commit()
    return public_alert(row)


@router.post("/alerts/read-all")
def read_all(db: Session = Depends(get_db)):
    for row in db.scalars(select(Alert).where(Alert.is_active.is_(True), Alert.is_read.is_(False))).all():
        row.is_read = True
    db.commit()
    return {"ok": True}


@router.get("/events")
def list_events(db: Session = Depends(get_db)):
    return [_event_out(row) for row in db.scalars(select(Event).order_by(Event.event_date.desc())).all()]


@router.post("/events")
def create_event(payload: EventIn, db: Session = Depends(get_db)):
    if payload.card_code and db.get(Card, payload.card_code) is None:
        raise HTTPException(404, "关联卡牌不存在")
    row = Event(**payload.model_dump())
    db.add(row)
    _audit(db, "create_event", payload.title)
    db.commit()
    scan_alerts(db)
    schedule_publish()
    return _event_out(row)


@router.delete("/events/{event_id}")
def delete_event(event_id: str, db: Session = Depends(get_db)):
    row = db.get(Event, event_id)
    if row is None:
        raise HTTPException(404, "找不到事件")
    db.delete(row)
    _audit(db, "delete_event", event_id)
    db.commit()
    scan_alerts(db)
    schedule_publish()
    return {"ok": True}


@router.get("/bids")
def list_bids(card_code: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Bid).order_by(Bid.bid_date.desc())
    if card_code:
        stmt = stmt.where(Bid.card_code == card_code)
    return [_bid_out(row) for row in db.scalars(stmt).all()]


@router.post("/bids")
def create_bid(payload: BidIn, db: Session = Depends(get_db)):
    if db.get(Card, payload.card_code) is None:
        ensure_card(db, payload.card_code, payload.card_code, None)
    ladder = payload.ladder or [price for price in (payload.highest_bid, payload.second_highest_bid) if price]
    row = Bid(
        card_code=payload.card_code,
        bid_date=payload.bid_date,
        highest_bid=payload.highest_bid if payload.highest_bid is not None else (ladder[0] if ladder else None),
        second_highest_bid=payload.second_highest_bid if payload.second_highest_bid is not None else (ladder[1] if len(ladder) > 1 else None),
        lowest_ask=payload.lowest_ask,
        bid_count=payload.bid_count if payload.bid_count is not None else (len(ladder) or None),
        ladder_json=json.dumps(ladder) if ladder else None,
    )
    db.add(row)
    _audit(db, "create_bid", payload.card_code)
    db.commit()
    scan_alerts(db)
    schedule_publish()
    return _bid_out(row)


@router.get("/audit")
def audit(db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(40)).all()
    return [{"id": row.id, "action": row.action, "detail": row.detail, "created_at": row.created_at.isoformat(timespec="seconds")} for row in rows]


def _event_out(row: Event) -> dict:
    return {
        "id": row.id,
        "event_date": row.event_date.isoformat(),
        "event_type": row.event_type,
        "card_code": row.card_code,
        "title": row.title,
        "description": row.description,
        "impact_level": row.impact_level,
        "source_url": row.source_url,
    }


def _bid_out(row: Bid) -> dict:
    ladder = []
    if row.ladder_json:
        try:
            ladder = json.loads(row.ladder_json)
        except json.JSONDecodeError:
            ladder = []
    return {
        "id": row.id,
        "card_code": row.card_code,
        "bid_date": row.bid_date.isoformat(),
        "highest_bid": row.highest_bid,
        "second_highest_bid": row.second_highest_bid,
        "lowest_ask": row.lowest_ask,
        "bid_count": row.bid_count,
        "ladder": ladder,
    }
