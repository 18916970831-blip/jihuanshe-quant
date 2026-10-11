import re
from datetime import date, datetime, time, timedelta

GRADE_FAMILIES = ("PSA", "PCG", "BGS", "CGC", "ARS", "SGC", "BRG")

HEADER_ALIASES = {
    "name": {"名称", "卡名", "卡片名称", "cardname", "name"},
    "date": {"交易日期", "日期", "tradedate", "date"},
    "time": {"交易时间", "时间", "tradetime", "time"},
    "price": {"成交价", "价格", "price", "成交价(元)"},
    "grade": {"品相", "评级", "grade"},
    "notes": {"备注", "notes", "note"},
}

CODE_ALIASES = {
    "223/293": "223-193",
    "223/193": "223-193",
    "236/187": "236-187",
}

KNOWN_CARDS = {
    "SV-P-260": {
        "card_name": "宝可梦2025日文 SV-P-260（东北皮卡丘）",
        "card_series": "宝可梦",
        "card_type": "皮卡丘",
        "region": "Tohoku",
        "psa_population_total": 48841,
        "psa_population_10": 30174,
        "external_notes": "东北限定。竞价与成交均按人民币计。",
    },
    "SV-P-261": {
        "card_name": "宝可梦2025日文 SV-P-261（广岛皮卡丘）",
        "card_series": "宝可梦",
        "card_type": "皮卡丘",
        "region": "Hiroshima",
        "psa_population_total": 48988,
        "psa_population_10": 36454,
        "external_notes": "广岛限定。历史成交中存在 IQR 异常高价。",
    },
    "SV-P-289": {
        "card_name": "宝可梦2025日文 SV-P-289（福冈皮卡丘）",
        "card_series": "宝可梦",
        "card_type": "皮卡丘",
        "region": "Fukuoka",
        "psa_population_total": 52318,
        "psa_population_10": 43355,
        "external_notes": "福冈限定。Gem Rate 高于另外两款地区皮卡丘。",
    },
    "223-193": {
        "card_name": "超级喷火龙Xex",
        "card_series": "宝可梦",
        "card_type": "喷火龙",
        "region": None,
        "external_notes": "竞价表代码写作 223/293，交易明细为 223-193，系统合并为 223-193。",
    },
    "236-187": {
        "card_name": "皮卡丘ex",
        "card_series": "宝可梦",
        "card_type": "皮卡丘",
        "region": None,
        "external_notes": "多品相混合，分析只取 PSA10 且非套出成交。",
    },
    "ST13-003": {
        "card_name": "蒙奇·D·路飞（航海王2025英文 ST13-003）",
        "card_series": "海贼王",
        "card_type": "路飞",
        "region": None,
        "external_notes": "航海王英文 ST13-003。",
    },
}

EVENT_TYPES = [
    "追加生产",
    "再版/再抽选",
    "Pokemon Center开店/迁址",
    "官方活动",
    "明星/赛事联动",
    "平台规则变化",
    "PSA批量出分",
    "市场传闻",
]

SEED_EVENTS = [
    {
        "event_date": date(2026, 3, 13),
        "event_type": "追加生产",
        "card_code": None,
        "title": "官方宣布三款 Special Box 追加生产和追加销售",
        "description": "中期供给压力增大，压制三款地区皮卡丘的价格天花板。",
        "impact_level": "高",
        "source_url": None,
    },
    {
        "event_date": date(2026, 3, 1),
        "event_type": "再版/再抽选",
        "card_code": "SV-P-289",
        "title": "Fukuoka 官方商品页显示再次抽选销售",
        "description": "5 月下旬发货，追加货源会逐步进入二级市场。",
        "impact_level": "中",
        "source_url": None,
    },
]


def norm_header(value) -> str:
    text = str(value or "").strip().lower()
    return text.replace("（", "(").replace("）", ")").replace(" ", "")


def map_headers(headers: list) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, header in enumerate(headers):
        key = norm_header(header)
        if not key:
            continue
        for field, aliases in HEADER_ALIASES.items():
            if key in aliases and field not in mapping:
                mapping[field] = idx
    return mapping


def canonicalize_code(raw: str) -> str:
    code = raw.strip().upper()
    return CODE_ALIASES.get(code, code)


def extract_card_code(sheet_name: str) -> str | None:
    patterns = (r"SV-P-\d+", r"ST\d+-\d+", r"\d{3}-\d{3}", r"\d{3}/\d{3}")
    for pattern in patterns:
        match = re.search(pattern, sheet_name, flags=re.IGNORECASE)
        if match:
            return canonicalize_code(match.group(0))
    return None


def normalize_grade(raw) -> str:
    if raw is None:
        return "其他"
    text = str(raw).strip()
    if not text or text.lower() in {"none", "nan"}:
        return "其他"
    compact = re.sub(r"[\s_\-]+", "", text).upper()
    families = "|".join(GRADE_FAMILIES)
    match = re.fullmatch(rf"({families})(\d{{1,2}}(?:\.5)?)", compact)
    if match:
        return f"{match.group(1)}{match.group(2)}"
    return text


def is_psa10(grade: str) -> bool:
    return normalize_grade(grade) == "PSA10"


def detect_bundle(name: str | None, notes: str | None) -> bool:
    title = name or ""
    memo = notes or ""
    if "套出" in title:
        return True
    if any(token in memo for token in ("套出", "套卡", "打包")):
        return True
    if "+" in title or "＋" in title:
        return True
    return False


def parse_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip().replace("/", "-").replace(".", "-")
    if not text or text.lower() in {"none", "nan"}:
        return None
    head = text[:10]
    for fmt in ("%Y-%m-%d",):
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            pass
    try:
        serial = float(text)
    except ValueError:
        return None
    if serial > 20000:
        return (datetime(1899, 12, 30) + timedelta(days=serial)).date()
    return None


def parse_time(value) -> time:
    if value is None or value == "":
        return time(0, 0, 0)
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    if isinstance(value, time):
        return value.replace(microsecond=0)
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan"}:
        return time(0, 0, 0)
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return time(0, 0, 0)


def parse_price(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value != value:
            return None
        return float(value)
    text = str(value).strip().replace(",", "").replace("，", "").replace("元", "").replace("¥", "").replace("￥", "")
    if not text or text.lower() in {"none", "nan"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def is_bid_sheet(sheet_name: str, headers: list) -> bool:
    if "竞价" in sheet_name:
        return True
    blob = "".join(str(h or "") for h in headers)
    return "竞价" in blob


def gem_rate(total, psa10) -> float | None:
    if not total or psa10 is None:
        return None
    return round(psa10 / total, 4)


def supply_pressure(total, rate) -> dict:
    if total is None and rate is None:
        return {"score": None, "label": "缺少人口数据"}
    pop_score = min(100.0, (total or 0) / 60000 * 100)
    gem_score = (rate or 0) * 100
    score = round(0.45 * pop_score + 0.55 * gem_score, 1)
    if score >= 75:
        label = "高"
    elif score >= 55:
        label = "中"
    else:
        label = "低"
    return {"score": score, "label": label}
