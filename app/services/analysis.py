"""PSA10 quantitative metrics.

N-day return is the latest daily median versus the daily median on the last
trading day at least N calendar days earlier. That matches the published
sample: for example SV-P-260 is +23.3% over 7 days and -2.1% over 30 days.
Volume change still compares trade counts in the two calendar windows.
Volatility and max drawdown use every PSA10 daily median, including days
dominated by an outlier print.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from app.services.cleaning import supply_pressure


def _fnum(value, digits=6):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, digits)


def _iso(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _as_date(value) -> date | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _records_frame(records: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    if frame.empty:
        return frame
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
    frame["trade_datetime"] = pd.to_datetime(frame["trade_datetime"])
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    frame["is_bundle"] = frame["is_bundle"].fillna(False).astype(bool)
    frame["grade"] = frame["grade"].fillna("其他").astype(str)
    return frame.dropna(subset=["price", "trade_date"])


def _window(frame: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    return frame[(frame["trade_date"] >= start_ts) & (frame["trade_date"] <= end_ts)]


def _change(recent, prior):
    if recent is None or prior in (None, 0):
        return None
    return (recent - prior) / prior


def _iqr_fences(prices: pd.Series):
    q1 = float(prices.quantile(0.25))
    q3 = float(prices.quantile(0.75))
    iqr = q3 - q1
    return q1, q3, q1 - 1.5 * iqr, q3 + 1.5 * iqr


def _forecast(daily: pd.DataFrame):
    if daily.empty or len(daily) < 8:
        return {
            "available": False,
            "reason": "有效交易日不足 8 天，不做外推",
            "d7": None,
            "d30": None,
            "bias": None,
            "r2": None,
            "disclaimer": _DISCLAIMER,
        }
    dates = list(daily.index)
    origin = dates[0]
    t_all = np.array([(item - origin).days for item in dates], dtype=float)
    y_all = np.log(daily["median"].to_numpy(dtype=float))
    windows = []
    for size in (14, 21, 28):
        if len(daily) >= size:
            windows.append(size)
    if not windows:
        windows.append(len(daily))

    point_7 = []
    point_30 = []
    r2s = []
    last_offset = float((dates[-1] - origin).days)
    for size in windows:
        t = t_all[-size:]
        y = y_all[-size:]
        slope, intercept = np.polyfit(t, y, 1)
        fitted = intercept + slope * t
        ss_res = float(np.sum((y - fitted) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2s.append(1 - ss_res / ss_tot if ss_tot else 1.0)
        point_7.append(math.exp(intercept + slope * (last_offset + 7)))
        point_30.append(math.exp(intercept + slope * (last_offset + 30)))

    def band(points):
        low, high = min(points), max(points)
        if high - low < 1e-6:
            pad = abs(points[0]) * 0.03
            low, high = points[0] - pad, points[0] + pad
        return {"low": _fnum(low, 2), "high": _fnum(high, 2), "mid": _fnum((low + high) / 2, 2)}

    d30 = band(point_30)
    latest = float(daily["median"].iloc[-1])
    mid = d30["mid"]
    if mid > latest * 1.05:
        bias = "偏强"
    elif mid < latest * 0.95:
        bias = "偏弱"
    else:
        bias = "震荡"
    r2 = sum(r2s) / len(r2s)
    if r2 < 0.15:
        bias = f"{bias}（拟合偏弱）"
    return {
        "available": True,
        "reason": None,
        "windows": windows,
        "d7": band(point_7),
        "d30": d30,
        "bias": bias,
        "r2": _fnum(r2, 3),
        "disclaimer": _DISCLAIMER,
    }


_DISCLAIMER = (
    "预测基于 PSA10 日中位价的对数线性外推，取 14/21/28 个有效交易日窗口，"
    "向后推 7 个与 30 个自然日。结果只是统计情景，不是单一目标价，历史表现也不代表未来收益。"
)


def compute_metrics(records: list[dict], bids: list[dict] | None = None, population: dict | None = None, as_of: date | None = None, start: date | None = None) -> dict:
    bids = bids or []
    population = population or {}
    frame = _records_frame(records)
    if start is not None and not frame.empty:
        frame = frame[frame["trade_date"] >= pd.Timestamp(start)]
    if as_of is not None and not frame.empty:
        frame = frame[frame["trade_date"] <= pd.Timestamp(as_of)]

    grade_mix = []
    if not frame.empty:
        counts = frame.groupby("grade").size().sort_values(ascending=False)
        grade_mix = [{"grade": str(grade), "count": int(count)} for grade, count in counts.items()]

    empty = _empty(grade_mix)
    if frame.empty:
        empty["warnings"].append("无交易数据")
        return empty

    psa = frame[(frame["grade"] == "PSA10") & (~frame["is_bundle"])].copy()
    bundles = frame[frame["is_bundle"]].sort_values("trade_datetime")
    others = frame[(frame["grade"] != "PSA10") & (~frame["is_bundle"])]
    empty["bundle_count"] = int(len(bundles))
    empty["other_grade_count"] = int(len(others))
    empty["grade_mix"] = grade_mix
    empty["bundle_trades"] = _bundle_rows(bundles)

    if psa.empty:
        empty["warnings"].append("无 PSA10 数据")
        return empty

    psa = psa.sort_values("trade_datetime")
    q1, q3, fence_low, fence_high = _iqr_fences(psa["price"])
    mean = float(psa["price"].mean())
    std = float(psa["price"].std(ddof=1)) if len(psa) > 1 else 0.0
    day_median = psa.groupby("trade_date")["price"].transform("median")
    reasons = []
    for idx, row in psa.iterrows():
        tags = []
        price = float(row["price"])
        if price < fence_low or price > fence_high:
            tags.append("IQR")
        base = float(day_median.loc[idx])
        if base and abs(price - base) / base > 0.5:
            tags.append("日内偏离中位价超过 50%")
        if std and price > mean + 3 * std:
            tags.append("高于均值 3 倍标准差")
        reasons.append(tags)

    psa = psa.copy()
    psa["anomaly_reasons"] = reasons
    anomalies = psa[psa["anomaly_reasons"].map(bool)].copy()
    inliers = psa[psa["anomaly_reasons"].map(lambda tags: "IQR" not in tags)].copy()
    price_base = inliers if len(inliers) >= 3 else psa

    daily_all = psa.groupby("trade_date")["price"].agg(median="median", high="max", low="min", count="count").sort_index()
    daily = price_base.groupby("trade_date")["price"].agg(median="median", high="max", low="min", count="count").sort_index()
    if daily.empty:
        daily = daily_all

    sample_start = _as_date(daily_all.index.min())
    sample_end = as_of or _as_date(daily_all.index.max())
    sample_days = (sample_end - sample_start).days + 1
    latest_date = _as_date(daily_all.index.max())
    latest_price = float(daily_all.iloc[-1]["median"])

    def period(days: int):
        recent_start = sample_end - timedelta(days=days - 1)
        prior_end = sample_end - timedelta(days=days)
        prior_start = sample_end - timedelta(days=2 * days - 1)
        recent = _window(psa, recent_start, sample_end) if sample_days >= days else psa.iloc[0:0]
        prior = _window(psa, prior_start, prior_end) if sample_days >= days else psa.iloc[0:0]
        payload = {
            "return": None,
            "recent_median": _fnum(latest_price, 2) if sample_days >= days else None,
            "prior_median": None,
            "anchor_date": None,
            "recent_count": int(len(recent)) if sample_days >= days else None,
            "prior_count": int(len(prior)) if sample_days >= days else None,
            "recent": [recent_start.isoformat(), sample_end.isoformat()] if sample_days >= days else None,
            "prior": [prior_start.isoformat(), prior_end.isoformat()] if sample_days >= days else None,
            "reason": f"数据不足 {days} 天",
        }
        if sample_days < days:
            return payload
        boundary = pd.Timestamp(sample_end - timedelta(days=days))
        history = daily_all[daily_all.index <= boundary]
        if history.empty:
            payload["reason"] = f"{days} 日前没有成交"
            return payload
        prior_median = float(history.iloc[-1]["median"])
        payload.update(
            {
                "return": _fnum(_change(latest_price, prior_median)),
                "prior_median": _fnum(prior_median, 2),
                "anchor_date": _iso(history.index[-1]),
                "reason": None if prior_median else "对比价格为 0",
            }
        )
        return payload

    d7, d30, d90 = period(7), period(30), period(90)
    vol_7 = d7["recent_count"]
    vol_30 = d30["recent_count"] if d30["recent_count"] is not None else int(len(_window(psa, sample_end - timedelta(days=29), sample_end))) if sample_days >= 1 else 0
    active_days = int(daily_all.shape[0])
    avg_active = len(psa) / active_days if active_days else None
    avg_calendar = len(psa) / sample_days if sample_days else None

    gaps = psa["trade_datetime"].sort_values().diff().dt.total_seconds().dropna() / 3600
    median_gap = float(gaps.median()) if not gaps.empty else None

    observed = daily_all["median"].copy()
    observed.index = pd.DatetimeIndex(observed.index)
    calendar = pd.date_range(sample_start, sample_end, freq="D")
    filled = observed.reindex(calendar).ffill()
    ma7 = filled.rolling(7, min_periods=1).mean()
    ma30 = filled.rolling(30, min_periods=1).mean()
    trade_peak = observed.cummax()
    trade_drawdown = (observed - trade_peak) / trade_peak.replace(0, np.nan)
    drawdown = trade_drawdown.reindex(calendar).ffill()
    trade_returns = observed.pct_change().dropna()
    volatility = float(trade_returns.std(ddof=1)) if len(trade_returns) > 1 else None
    rolling_vol = trade_returns.rolling(7, min_periods=3).std(ddof=1)
    max_drawdown = float(trade_drawdown.min()) if trade_drawdown.notna().any() else None

    last_day = daily_all.loc[daily_all.index.max()]
    intraday = None
    if last_day["low"]:
        intraday = (float(last_day["high"]) - float(last_day["low"])) / float(last_day["low"])
    recent_levels = observed[observed.index >= pd.Timestamp(sample_end - timedelta(days=6))]
    std_7d = float(recent_levels.std(ddof=1)) if len(recent_levels) > 1 else None

    raw_high = float(psa["price"].max())
    raw_low = float(psa["price"].min())
    high = float(price_base["price"].max())
    low = float(price_base["price"].min())
    percentile = None if high == low else (latest_price - low) / (high - low)

    vol_change_7 = _change(d7["recent_count"], d7["prior_count"]) if d7["recent_count"] is not None else None
    vol_change_30 = _change(d30["recent_count"], d30["prior_count"]) if d30["recent_count"] is not None else None
    divergence = _divergence(d7["return"], vol_change_7)
    heat = None
    if vol_30 and sample_days >= 7:
        heat = (vol_7 or 0) * min(30, sample_days) / (vol_30 * 7)

    anomaly_rows = []
    for _, row in anomalies.sort_values("trade_datetime", ascending=False).iterrows():
        anomaly_rows.append(
            {
                "id": row.get("id"),
                "date": _iso(row["trade_date"]),
                "time": row["trade_datetime"].strftime("%H:%M") if pd.notna(row["trade_datetime"]) else None,
                "price": _fnum(row["price"], 2),
                "name": row.get("card_name"),
                "reasons": list(row["anomaly_reasons"]),
                "extreme": bool(row["price"] > high * 1.8 or row["price"] < low * 0.5),
            }
        )

    series = []
    vol_lookup = {idx.date() if hasattr(idx, "date") else idx: value for idx, value in rolling_vol.items()}
    count_lookup = daily_all["count"].to_dict()
    for day in calendar:
        key = pd.Timestamp(day)
        traded = key in observed.index
        count = int(count_lookup.get(key, 0))
        series.append(
            {
                "date": day.date().isoformat(),
                "median": _fnum(filled.loc[key], 2),
                "traded": bool(traded and count),
                "count": count,
                "ma7": _fnum(ma7.loc[key], 2),
                "ma30": _fnum(ma30.loc[key], 2),
                "drawdown": _fnum(drawdown.loc[key]),
                "volatility": _fnum(vol_lookup.get(day.date())),
                "volume_ma7": None,
            }
        )
    counts = pd.Series([point["count"] for point in series], index=calendar)
    volume_ma = counts.rolling(7, min_periods=1).mean()
    for point, day in zip(series, calendar):
        point["volume_ma7"] = _fnum(volume_ma.loc[day], 2)

    hist = _histogram(daily_all["median"], latest_price)
    bid_rows = _bid_rows(bids, latest_price)
    latest_bid = bid_rows[-1] if bid_rows else None
    pop_total = population.get("psa_population_total")
    pop_10 = population.get("psa_population_10")
    rate = population.get("psa_gem_rate")
    if pop_total and pop_10 is not None:
        rate = pop_10 / pop_total
    pressure = supply_pressure(pop_total, rate)

    warnings = []
    if len(psa) <= 2:
        warnings.append("样本量不足")
    elif len(psa) < 8:
        warnings.append("样本量偏少")
    if sample_days < 7:
        warnings.append("数据不足 7 天")
    elif sample_days < 30:
        warnings.append("数据不足 30 天")

    short_vol = float(trade_returns.tail(7).std(ddof=1)) if len(trade_returns) >= 5 else None
    today_count = int(count_lookup.get(pd.Timestamp(sample_end), 0))
    baseline_counts = counts[counts.index < pd.Timestamp(sample_end)]
    baseline = float(baseline_counts[baseline_counts > 0].mean()) if (baseline_counts > 0).any() else None

    return {
        "has_psa10": True,
        "sample_start": sample_start.isoformat(),
        "sample_end": sample_end.isoformat(),
        "sample_days": sample_days,
        "psa10_count": int(len(psa)),
        "bundle_count": int(len(bundles)),
        "other_grade_count": int(len(others)),
        "grade_mix": grade_mix,
        "warnings": warnings,
        "latest_price": _fnum(latest_price, 2),
        "latest_date": latest_date.isoformat() if latest_date else None,
        "high": _fnum(high, 2),
        "low": _fnum(low, 2),
        "high_raw": _fnum(raw_high, 2),
        "low_raw": _fnum(raw_low, 2),
        "percentile": _fnum(percentile),
        "returns": {"d7": d7, "d30": d30, "d90": d90},
        "volume": {
            "d7": vol_7,
            "d30": d30["recent_count"],
            "change_7d": _fnum(vol_change_7),
            "change_30d": _fnum(vol_change_30),
            "avg_active": _fnum(avg_active, 2),
            "avg_calendar": _fnum(avg_calendar, 2),
            "median_gap_hours": _fnum(median_gap, 1),
            "active_days": active_days,
            "active_ratio": _fnum(active_days / sample_days if sample_days else None),
            "latest_day_count": today_count,
            "baseline_active": _fnum(baseline, 2),
        },
        "risk": {
            "volatility": _fnum(volatility),
            "volatility_7d": _fnum(short_vol),
            "max_drawdown": _fnum(max_drawdown),
            "intraday_range": _fnum(intraday),
            "std_7d": _fnum(std_7d, 2),
        },
        "liquidity": {
            "active_ratio": _fnum(active_days / sample_days if sample_days else None),
            "avg_active": _fnum(avg_active, 2),
            "spread": latest_bid.get("spread") if latest_bid else None,
            "highest_bid": latest_bid.get("highest_bid") if latest_bid else None,
            "second_bid": latest_bid.get("second_highest_bid") if latest_bid else None,
            "lowest_ask": latest_bid.get("lowest_ask") if latest_bid else None,
            "bid_count": latest_bid.get("bid_count") if latest_bid else None,
            "bid_deviation": latest_bid.get("deviation") if latest_bid else None,
        },
        "population": {
            "total": pop_total,
            "psa10": pop_10,
            "gem_rate": _fnum(rate),
            "pressure": pressure,
        },
        "divergence": divergence,
        "heat": _fnum(heat, 2),
        "anomalies": anomaly_rows[:80],
        "anomaly_count": int(len(anomaly_rows)),
        "iqr": {"q1": _fnum(q1, 2), "q3": _fnum(q3, 2), "low": _fnum(fence_low, 2), "high": _fnum(fence_high, 2)},
        "bundle_trades": _bundle_rows(bundles),
        "prediction": _forecast(daily_all),
        "histogram": hist,
        "series": series,
        "bids": bid_rows,
    }


def _divergence(price_return, volume_change):
    if price_return is None or volume_change is None:
        return {"signal": "样本不足", "meaning": "收益或成交量窗口不完整，暂不判断背离。"}
    up = price_return > 0
    down = price_return < 0
    vol_up = volume_change > 0
    vol_down = volume_change < 0
    if up and vol_down:
        return {"signal": "价升量缩", "meaning": "上涨缺少成交量配合，持续性需要打折。"}
    if down and vol_down:
        return {"signal": "价跌量缩", "meaning": "下跌动能减弱，可能接近短期底部。"}
    if up and vol_up:
        return {"signal": "价升量增", "meaning": "上涨得到成交量确认，趋势相对完整。"}
    if down and vol_up:
        return {"signal": "价跌量增", "meaning": "下跌伴随放量，抛压偏重。"}
    return {"signal": "价量中性", "meaning": "价格或成交量几乎没有变化。"}


def _bundle_rows(bundles: pd.DataFrame):
    rows = []
    if bundles.empty:
        return rows
    for _, row in bundles.sort_values("trade_datetime", ascending=False).head(40).iterrows():
        rows.append(
            {
                "date": _iso(row["trade_date"]),
                "time": row["trade_datetime"].strftime("%H:%M") if pd.notna(row["trade_datetime"]) else None,
                "price": _fnum(row["price"], 2),
                "grade": row["grade"],
                "name": row.get("card_name"),
                "notes": row.get("notes"),
            }
        )
    return rows


def _histogram(prices: pd.Series, latest: float):
    if prices.empty:
        return []
    unique = prices.nunique()
    bins = int(min(12, max(4, unique)))
    counts, edges = np.histogram(prices.to_numpy(dtype=float), bins=bins)
    total = counts.sum() or 1
    running = 0
    rows = []
    for count, left, right in zip(counts, edges[:-1], edges[1:]):
        running += int(count)
        rows.append(
            {
                "left": round(float(left), 2),
                "right": round(float(right), 2),
                "count": int(count),
                "cdf": round(running / total, 4),
                "contains_latest": bool(left <= latest <= right),
            }
        )
    return rows


def _bid_rows(bids: list[dict], latest_price: float | None):
    rows = []
    for bid in sorted(bids, key=lambda item: item.get("bid_date") or date.min):
        highest = bid.get("highest_bid")
        lowest_ask = bid.get("lowest_ask")
        spread = None if highest is None or lowest_ask is None else round(lowest_ask - highest, 2)
        deviation = None
        if highest and latest_price:
            deviation = (highest - latest_price) / latest_price
        rows.append(
            {
                "date": _iso(bid.get("bid_date")),
                "highest_bid": _fnum(highest, 2),
                "second_highest_bid": _fnum(bid.get("second_highest_bid"), 2),
                "lowest_ask": _fnum(lowest_ask, 2),
                "bid_count": bid.get("bid_count"),
                "ladder": bid.get("ladder") or [],
                "spread": spread,
                "deviation": _fnum(deviation),
            }
        )
    return rows


def _empty(grade_mix):
    return {
        "has_psa10": False,
        "sample_start": None,
        "sample_end": None,
        "sample_days": 0,
        "psa10_count": 0,
        "bundle_count": 0,
        "other_grade_count": 0,
        "grade_mix": grade_mix,
        "warnings": [],
        "latest_price": None,
        "latest_date": None,
        "high": None,
        "low": None,
        "high_raw": None,
        "low_raw": None,
        "percentile": None,
        "returns": {"d7": {"return": None, "reason": "无 PSA10 数据"}, "d30": {"return": None, "reason": "无 PSA10 数据"}, "d90": {"return": None, "reason": "无 PSA10 数据"}},
        "volume": {},
        "risk": {},
        "liquidity": {},
        "population": {},
        "divergence": {"signal": "无数据", "meaning": "没有可计算的 PSA10 成交。"},
        "heat": None,
        "anomalies": [],
        "anomaly_count": 0,
        "iqr": {},
        "bundle_trades": [],
        "prediction": {"available": False, "reason": "无 PSA10 数据", "disclaimer": _DISCLAIMER},
        "histogram": [],
        "series": [],
        "bids": [],
    }
