from datetime import date, time

from pydantic import BaseModel, Field


class TradeIn(BaseModel):
    card_code: str
    trade_date: date
    trade_time: time | None = None
    price: float = Field(gt=0)
    grade: str
    notes: str | None = None
    source: str = "手动录入"
    mark_bundle: bool = False


class CardIn(BaseModel):
    card_code: str
    card_name: str
    card_series: str | None = None
    card_type: str | None = None
    region: str | None = None
    psa_population_total: int | None = None
    psa_population_10: int | None = None
    external_notes: str | None = None


class CardPatch(BaseModel):
    card_name: str | None = None
    card_series: str | None = None
    card_type: str | None = None
    region: str | None = None
    is_active: bool | None = None
    psa_population_total: int | None = None
    psa_population_10: int | None = None
    external_notes: str | None = None


class EventIn(BaseModel):
    event_date: date
    event_type: str
    card_code: str | None = None
    title: str
    description: str | None = None
    impact_level: str | None = None
    source_url: str | None = None


class BidIn(BaseModel):
    card_code: str
    bid_date: date
    highest_bid: float | None = None
    second_highest_bid: float | None = None
    lowest_ask: float | None = None
    bid_count: int | None = None
    ladder: list[float] | None = None
