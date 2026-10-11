import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"
DB_PATH = DATA_DIR / "market.db"

EXCEL_CANDIDATES = []
if os.environ.get("QUANT_EXCEL"):
    EXCEL_CANDIDATES.append(Path(os.environ["QUANT_EXCEL"]))
EXCEL_CANDIDATES.append(ROOT.parent / "集换社交易汇总数据.xlsx")
