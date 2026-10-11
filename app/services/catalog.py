import json
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Bid, Card, Trade
from app.services.advice import decide
from app.services.analysis import compute_metrics


def trade_record(row: Trade) -> dict:
    return {
        "id": row.id,
        "price": row.price,
        "grade": row.grade,
        "is_bundle": row.is_bundle,
        "trade_date": row.trade_date,
        "trade_datetime": row.trade_datetime,
        "card_name": row.card_name,
        "notes": row.notes,
        "is_suspicious": row.is_suspicious,
    }


def bid_record(row: Bid) -> dict:
    ladder = []
    if row.ladder_json:
        try:
            ladder = json.loads(row.ladder_json)
        except json.JSONDecodeError:
            ladder = []
    return {
        "bid_date": row.bid_date,
        "highest_bid": row.highest_bid,
        "second_highest_bid": row.second_highest_bid,
        "lowest_ask": row.lowest_ask,
        "bid_count": row.bid_count,
        "ladder": ladder,
    }


def population_of(card: Card) -> dict:
    return {
        "psa_population_total": card.psa_population_total,
        "psa_population_10": card.psa_population_10,
        "psa_gem_rate": card.psa_gem_rate,
    }


def analyze_card(db: Session, card: Card, start: date | None = None, end: date | None = None) -> dict:
    trades = db.scalars(select(Trade).where(Trade.card_code == card.card_code)).all()
    bids = db.scalars(select(Bid).where(Bid.card_code == card.card_code)).all()
    metrics = compute_metrics(
        [trade_record(row) for row in trades],
        [bid_record(row) for row in bids],
        population_of(card),
        as_of=end,
        start=start,
    )
    advice = decide(metrics)
    metrics["advice"] = advice
    metrics["card_code"] = card.card_code
    metrics["card_name"] = card.card_name
    metrics["card_series"] = card.card_series
    metrics["card_type"] = card.card_type
    metrics["region"] = card.region
    metrics["external_notes"] = card.external_notes
    return metrics


def active_cards(db: Session) -> list[Card]:
    return list(db.scalars(select(Card).where(Card.is_active.is_(True)).order_by(Card.card_code)).all())


def summarize(metrics: dict) -> dict:
    returns = metrics.get("returns") or {}
    volume = metrics.get("volume") or {}
    risk = metrics.get("risk") or {}
    series = metrics.get("series") or []
    spark = [{"date": point["date"], "median": point["median"]} for point in series if point.get("traded")]
    return {
        "card_code": metrics.get("card_code"),
        "card_name": metrics.get("card_name"),
        "card_series": metrics.get("card_series"),
        "latest_price": metrics.get("latest_price"),
        "latest_date": metrics.get("latest_date"),
        "return_7d": (returns.get("d7") or {}).get("return"),
        "return_30d": (returns.get("d30") or {}).get("return"),
        "return_90d": (returns.get("d90") or {}).get("return"),
        "volume_7d": volume.get("d7"),
        "volume_change_7d": volume.get("change_7d"),
        "volatility": risk.get("volatility"),
        "max_drawdown": risk.get("max_drawdown"),
        "avg_active": volume.get("avg_active"),
        "percentile": metrics.get("percentile"),
        "divergence": (metrics.get("divergence") or {}).get("signal"),
        "heat": metrics.get("heat"),
        "advice": metrics.get("advice"),
        "warnings": metrics.get("warnings") or [],
        "has_psa10": metrics.get("has_psa10"),
        "psa10_count": metrics.get("psa10_count"),
        "sparkline": spark[-40:],
        "sample_end": metrics.get("sample_end"),
    }


def market_as_of(db: Session) -> date | None:
    latest = db.scalars(select(Trade.trade_date).order_by(Trade.trade_date.desc())).first()
    return latest


def dump_trade(row: Trade) -> dict:
    return {
        "id": row.id,
        "card_code": row.card_code,
        "card_name": row.card_name,
        "trade_date": row.trade_date.isoformat(),
        "trade_time": row.trade_time.strftime("%H:%M:%S") if row.trade_time else None,
        "price": row.price,
        "grade": row.grade,
        "is_bundle": row.is_bundle,
        "is_suspicious": row.is_suspicious,
        "source": row.source,
        "notes": row.notes,
        "created_at": row.created_at.isoformat(timespec="seconds") if isinstance(row.created_at, datetime) else None,
    }
