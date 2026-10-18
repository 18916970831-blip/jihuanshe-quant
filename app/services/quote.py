"""Compare one asking price with the latest PSA10 median.

The listing can come from Xianyu or Jihuanshe. The comparison still uses only
PSA10 trades with bundle sales removed.
"""

from __future__ import annotations


def judge_quote(metrics: dict, ask: float, source: str | None = None) -> dict:
    latest = metrics.get("latest_price")
    advice = (metrics.get("advice") or {}).get("action")
    if not metrics.get("has_psa10") or not latest:
        return _payload(
            metrics,
            ask,
            source,
            "无法判断",
            "这张卡还没有可比较的 PSA10 成交。",
            ["没有 PSA10 且非套出的成交，挂牌价没法对照。"],
            None,
        )

    gap = (ask - latest) / latest
    low = metrics.get("low")
    high = metrics.get("high")
    place = None
    if low is not None and high is not None and high != low:
        place = (ask - low) / (high - low)
    ret7 = _ret(metrics, "d7")
    ret30 = _ret(metrics, "d30")
    vol_change = (metrics.get("volume") or {}).get("change_7d")
    drawdown = (metrics.get("risk") or {}).get("max_drawdown")
    divergence = (metrics.get("divergence") or {}).get("signal")
    dumping = ret7 is not None and ret7 < -0.15 and vol_change is not None and vol_change > 0
    counter = None

    if gap <= -0.35:
        verdict = "先核对"
        headline = "这个价比最近的 PSA10 中位价低了三成以上，先确认是不是同一张 PSA10 单卡。"
    elif gap <= -0.03:
        if advice == "强卖出" or dumping:
            verdict = "先别买"
            headline = "虽然比最近成交便宜，但这张卡正在走弱，便宜不一定能接住。"
        else:
            verdict = "可以买"
            headline = "低于最近的 PSA10 中位价，按现在的成交看，这个挂牌价可以买。"
    elif gap <= 0.03:
        if advice in {"强买入", "买入"} and (place is None or place < 0.75):
            verdict = "可以买"
            headline = "和最近成交差不多，这张卡当前的位置也支持分批买。"
        elif advice in {"强卖出", "卖出/减仓"} or dumping:
            verdict = "先别买"
            headline = "价格只是贴着最近成交，但这张卡的趋势不支持现在买。"
        else:
            verdict = "再还价"
            headline = "和最近成交差不多，没有明显便宜。想买就还到中位价下面一点。"
            counter = round(latest * 0.97, 2)
    elif gap <= 0.12:
        verdict = "再还价"
        headline = "比最近的 PSA10 成交贵。可以还价，不建议按挂牌价直接买。"
        counter = round(latest, 2)
    else:
        verdict = "先别买"
        headline = "比最近的 PSA10 中位价贵了一截，这个挂牌价先别买。"
        counter = round(latest, 2)

    if place is not None and place > 1 and verdict == "可以买":
        verdict = "再还价"
        headline = "这个价已经高于剔掉极端成交后的样本高点，先还价。"
        counter = round(latest, 2)

    reasons = [
        f"挂牌价 {_cny(ask)}，最近 PSA10 中位价 {_cny(latest)}（{metrics.get('latest_date') or '—'}），相差 {_pct(gap)}。",
    ]
    if place is None:
        reasons.append("样本高低点拉不开，只和最近成交比较。")
    elif place > 1:
        reasons.append("这个挂牌价已经高于剔掉极端成交后的样本高点。")
    else:
        spot = "高位" if place >= 0.75 else ("低位" if place <= 0.35 else "中位")
        reasons.append(f"放进历史成交里，这个价处在样本{spot}。")
    window = []
    if ret7 is not None:
        window.append(f"7 日 {_pct(ret7)}")
    if ret30 is not None:
        window.append(f"30 日 {_pct(ret30)}")
    if window:
        reasons.append("、".join(window) + "。")
    if vol_change is not None:
        reasons.append(f"近 7 日成交量变化 {_pct(vol_change)}，{divergence or '量价样本不足'}。")
    if drawdown is not None and drawdown <= -0.25:
        reasons.append(f"样本内最大回撤 {_pct(drawdown)}。")
    if advice:
        reasons.append(f"这张卡现在的趋势建议是{advice}。询价只判断这一笔挂牌价。")
    if verdict == "可以买" and drawdown is not None and drawdown <= -0.40:
        reasons.append("回撤已经很深，买的话少买一点。")
    if counter is not None:
        reasons.append(f"还价可以对着 {_cny(counter)} 附近。")

    return _payload(metrics, ask, source, verdict, headline, reasons, counter, gap, place, advice)


def _payload(metrics, ask, source, verdict, headline, reasons, counter, gap=None, place=None, advice=None):
    where = (source or "").strip() or None
    return {
        "card_code": metrics.get("card_code"),
        "card_name": metrics.get("card_name"),
        "source": where,
        "ask": round(float(ask), 2),
        "latest_price": metrics.get("latest_price"),
        "latest_date": metrics.get("latest_date"),
        "gap": None if gap is None else round(gap, 4),
        "place": None if place is None else round(place, 4),
        "market_action": advice,
        "verdict": verdict,
        "headline": headline,
        "reasons": reasons,
        "counter": counter,
    }


def _ret(metrics, key):
    return ((metrics.get("returns") or {}).get(key) or {}).get("return")


def _pct(value) -> str:
    return f"{value * 100:+.1f}%"


def _cny(value) -> str:
    number = float(value)
    if number.is_integer():
        return f"¥{number:.0f}"
    return f"¥{number:.2f}"
