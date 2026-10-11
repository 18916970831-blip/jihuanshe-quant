import uuid
from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Card(Base):
    __tablename__ = "cards"

    card_code: Mapped[str] = mapped_column(String(50), primary_key=True)
    card_name: Mapped[str] = mapped_column(String(200), nullable=False)
    card_series: Mapped[str | None] = mapped_column(String(100))
    card_type: Mapped[str | None] = mapped_column(String(50))
    region: Mapped[str | None] = mapped_column(String(50))
    date_added: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    psa_population_total: Mapped[int | None] = mapped_column(Integer)
    psa_population_10: Mapped[int | None] = mapped_column(Integer)
    psa_gem_rate: Mapped[float | None] = mapped_column(Float)
    external_notes: Mapped[str | None] = mapped_column(Text)

    trades: Mapped[list["Trade"]] = relationship(back_populates="card")


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (
        Index("idx_trades_card_date", "card_code", "trade_date"),
        Index("idx_trades_grade", "card_code", "grade"),
        Index("idx_trades_datetime", "trade_datetime"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    card_code: Mapped[str] = mapped_column(ForeignKey("cards.card_code"), nullable=False)
    card_name: Mapped[str] = mapped_column(String(200), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    trade_time: Mapped[time | None] = mapped_column(Time)
    trade_datetime: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    grade: Mapped[str] = mapped_column(String(20), nullable=False)
    is_bundle: Mapped[bool] = mapped_column(Boolean, default=False)
    is_suspicious: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(50), default="集换社")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    card: Mapped[Card] = relationship(back_populates="trades")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    card_code: Mapped[str | None] = mapped_column(ForeignKey("cards.card_code"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    impact_level: Mapped[str | None] = mapped_column(String(20))
    source_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Bid(Base):
    __tablename__ = "bids"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    card_code: Mapped[str] = mapped_column(ForeignKey("cards.card_code"), nullable=False)
    bid_date: Mapped[date] = mapped_column(Date, nullable=False)
    highest_bid: Mapped[float | None] = mapped_column(Float)
    second_highest_bid: Mapped[float | None] = mapped_column(Float)
    lowest_ask: Mapped[float | None] = mapped_column(Float)
    bid_count: Mapped[int | None] = mapped_column(Integer)
    ladder_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    fingerprint: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    rule_id: Mapped[str] = mapped_column(String(10), nullable=False)
    card_code: Mapped[str | None] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(String(20), default="中")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ImportLog(Base):
    __tablename__ = "import_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    detail_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
