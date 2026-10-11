import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"
DB_PATH = DATA_DIR / "market.db"

def load_local_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()

EXCEL_CANDIDATES = []
if os.environ.get("QUANT_EXCEL"):
    EXCEL_CANDIDATES.append(Path(os.environ["QUANT_EXCEL"]))
EXCEL_CANDIDATES.append(ROOT.parent / "集换社交易汇总数据.xlsx")
