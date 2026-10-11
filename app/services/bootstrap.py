import logging

from sqlalchemy import func, select

from app.config import EXCEL_CANDIDATES
from app.database import SessionLocal, init_db
from app.models import AuditLog, Event, Trade
from app.services.alerts import scan_alerts
from app.services.cleaning import SEED_EVENTS
from app.services.importer import import_workbook

logger = logging.getLogger("quant")


def find_excel():
    for path in EXCEL_CANDIDATES:
        if path.exists():
            return path
    return None


def seed_events(db) -> int:
    existing = db.scalar(select(func.count()).select_from(Event)) or 0
    if existing:
        return 0
    for payload in SEED_EVENTS:
        db.add(Event(**payload))
    db.add(AuditLog(action="seed_events", detail=f"写入 {len(SEED_EVENTS)} 条参考事件"))
    db.commit()
    return len(SEED_EVENTS)


def bootstrap(import_excel: bool = True, scan: bool = True):
    init_db()
    db = SessionLocal()
    try:
        trade_count = db.scalar(select(func.count()).select_from(Trade)) or 0
        if import_excel and trade_count == 0:
            excel = find_excel()
            if excel is not None:
                logger.info("导入 %s", excel.name)
                import_workbook(db, excel.read_bytes(), excel.name)
            else:
                logger.info("未找到集换社 Excel，跳过初始导入")
        seed_events(db)
        if scan:
            scan_alerts(db)
    finally:
        db.close()


def reset_and_import(path=None):
    from app.database import Base, engine
    from app import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    excel = path or find_excel()
    db = SessionLocal()
    try:
        if excel is None:
            raise FileNotFoundError("找不到集换社交易汇总数据.xlsx")
        summary = import_workbook(db, excel.read_bytes(), excel.name)
        seed_events(db)
        scan_alerts(db)
        return summary
    finally:
        db.close()
