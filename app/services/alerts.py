from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alert, Event
from app.services.catalog import active_cards, analyze_card, market_as_of

RULES = {
    "A-01": "价格暴涨",
    "A-02": "价格暴跌",
    "A-03": "成交量异常",
    "A-04": "异常成交",
    "A-05": "竞价偏离",
    "A-06": "供给事件",
    "A-07": "波动率飙升",
}


def scan_alerts(db: Session) -> list[Alert]:
    as_of = market_as_of(db)
    found: dict[str, dict] = {}
    for card in active_cards(db):
        metrics = analyze_card(db, card, end=as_of)
        if not metrics.get("has_psa10"):
            continue
        stamp = metrics.get("sample_end") or "na"
        ret7 = (metrics.get("returns") or {}).get("d7", {}).get("return")
        name = card.card_name
        if ret7 is not None and ret7 > 0.20:
            _add(found, "A-01", card.card_code, stamp, "高" if ret7 > 0.35 else "中", f"{name} 近 7 日上涨 {ret7 * 100:.1f}%，超过 +20% 阈值。")
        if ret7 is not None and ret7 < -0.20:
            _add(found, "A-02", card.card_code, stamp, "高", f"{name} 近 7 日下跌 {ret7 * 100:.1f}%，超过 -20% 阈值。")
        volume = metrics.get("volume") or {}
        latest_count = volume.get("latest_day_count") or 0
        baseline = volume.get("baseline_active")
        if baseline and latest_count > 3 * baseline:
            _add(found, "A-03", card.card_code, stamp, "中", f"{name} 最近一个交易日成交 {latest_count} 笔，超过有效日均量 {baseline:.1f} 的 3 倍。")
        recent_anomalies = [row for row in metrics.get("anomalies") or [] if row.get("date") and as_of and row["date"] >= (as_of - timedelta(days=7)).isoformat()]
        if recent_anomalies:
            prices = "、".join(f"{row['price']:.0f}" for row in recent_anomalies[:4])
            _add(found, "A-04", card.card_code, stamp, "高", f"{name} 近 7 日有 {len(recent_anomalies)} 笔异常成交，价格包括 {prices} 元。")
        deviation = (metrics.get("liquidity") or {}).get("bid_deviation")
        if deviation is not None and abs(deviation) > 0.40:
            bid = (metrics.get("liquidity") or {}).get("highest_bid")
            _add(found, "A-05", card.card_code, stamp, "高", f"{name} 最高竞价 {bid:.0f} 元，偏离最新成交 {deviation * 100:+.1f}%。")
        vol = (metrics.get("risk") or {}).get("volatility")
        vol7 = (metrics.get("risk") or {}).get("volatility_7d")
        if vol and vol7 and vol7 > 2 * vol:
            _add(found, "A-07", card.card_code, stamp, "中", f"{name} 近端波动率 {vol7 * 100:.1f}%，高于全样本 {vol * 100:.1f}% 的 2 倍。")

    if as_of:
        events = db.scalars(select(Event).where(Event.impact_level == "高", Event.event_date >= as_of - timedelta(days=365))).all()
        for event in events:
            _add(found, "A-06", event.card_code, event.id, "高", f"{event.event_date.isoformat()} {event.title}")

    current = set(found)
    existing = db.scalars(select(Alert)).all()
    by_fp = {row.fingerprint: row for row in existing}
    for fp, payload in found.items():
        row = by_fp.get(fp)
        if row is None:
            db.add(Alert(fingerprint=fp, is_active=True, is_read=False, **payload))
        else:
            row.is_active = True
            row.title = payload["title"]
            row.message = payload["message"]
            row.level = payload["level"]
    for row in existing:
        if row.fingerprint not in current:
            row.is_active = False
    db.commit()
    return list(db.scalars(select(Alert).where(Alert.is_active.is_(True)).order_by(Alert.created_at.desc())).all())


def _add(found: dict, rule_id: str, card_code: str | None, bucket: str, level: str, message: str):
    fp = f"{rule_id}|{card_code or 'ALL'}|{bucket}"
    found[fp] = {
        "rule_id": rule_id,
        "card_code": card_code,
        "title": RULES[rule_id],
        "message": message,
        "level": level,
    }


def public_alert(row: Alert) -> dict:
    return {
        "id": row.id,
        "rule_id": row.rule_id,
        "card_code": row.card_code,
        "title": row.title,
        "message": row.message,
        "level": row.level,
        "is_read": row.is_read,
        "is_active": row.is_active,
        "created_at": row.created_at.isoformat(timespec="seconds"),
    }
