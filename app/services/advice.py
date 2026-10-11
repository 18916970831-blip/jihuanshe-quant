"""Rule engine from the PRD.

Strong sell treats max drawdown as a negative return. The written condition
"Max Drawdown > -40%" would fire on shallow drawdowns, so the trigger used
here is a drawdown of 40% or worse together with a 30-day return below -20%.
"""

from __future__ import annotations


def decide(metrics: dict) -> dict:
    if not metrics.get("has_psa10"):
        return {
            "action": "无法判断",
            "score": 0,
            "reasons": ["没有 PSA10 且非套出的成交。"],
            "position": "不建仓",
            "take_profit": None,
            "stop_loss": None,
            "target": None,
        }

    ret7 = _ret(metrics, "d7")
    ret30 = _ret(metrics, "d30")
    vol_change = (metrics.get("volume") or {}).get("change_7d")
    drawdown = (metrics.get("risk") or {}).get("max_drawdown")
    latest = metrics.get("latest_price")
    prediction = metrics.get("prediction") or {}
    d7_band = prediction.get("d7") or {}
    divergence = (metrics.get("divergence") or {}).get("signal")
    percentile = metrics.get("percentile")

    high_location = percentile is not None and percentile >= 0.75
    rising = ret7 is not None and ret7 > 0
    volume_up = vol_change is not None and vol_change > 0
    volume_soft = vol_change is not None and vol_change < 0

    action = "持有观察"
    conclusion = "没有形成明确的追涨或离场条件，维持现有仓位。"
    if ret30 is not None and ret30 < -0.20 and drawdown is not None and drawdown <= -0.40:
        action = "强卖出"
        conclusion = "30 日跌幅和回撤同时很深，先退出。"
    elif rising and ret7 > 0.20 and vol_change is not None and vol_change < -0.50:
        action = "卖出/减仓"
        conclusion = "短线已经涨得不少，成交量却缩掉一半以上，不适合继续拿着满仓。"
    elif rising and volume_soft and (high_location or ret7 > 0.15):
        action = "观望"
        conclusion = "价格在涨，但量能没跟上。高位或急涨时不追。"
    elif rising and ret30 is not None and ret30 < 0 and vol_change is not None and vol_change > -0.50 and not high_location:
        action = "强买入"
        conclusion = "30 日仍亏、7 日转正，价格也不在样本高位，这是回撤后的修复，可以分批。"
    elif rising and volume_up and not high_location:
        action = "买入"
        conclusion = "上涨有成交量配合，价格也不在样本高位，可以分批买，不是追已经涨高的。"
    elif rising and volume_up and high_location:
        action = "持有观察"
        conclusion = "涨势有量能确认，但价格已经在样本高位。已有仓位先拿着，新开仓等回调。"
    elif ret7 is not None and ret7 < -0.15 and volume_up:
        action = "观望"
        conclusion = "下跌同时放量，不因为价格看起来低就买。"
    elif rising:
        action = "观望"
        conclusion = "有上涨，但位置或量能不足以支持现在买。"

    reasons = _factor_lines(percentile, high_location, ret7, ret30, vol_change, divergence, drawdown)
    reasons.append(conclusion)
    if drawdown is not None and drawdown <= -0.40 and action in {"强买入", "买入"}:
        reasons.append(f"最大回撤已到 {_pct(drawdown)}，仓位按下限。")
    if metrics.get("warnings"):
        reasons.append("、".join(metrics["warnings"]) + "。")

    target = d7_band.get("high") if action == "强买入" and d7_band else None
    if target is None and latest:
        target = round(latest * (1.12 if action in {"卖出/减仓", "强卖出"} else 1.15), 2)

    if action == "强卖出":
        position = "降到 0–5%，不等待反弹"
        stop = latest
        take = None
    elif action == "卖出/减仓":
        position = "已有仓位减到一半以下"
        stop = round(latest * 0.92, 2) if latest else None
        take = target
    elif action == "强买入":
        position = "分 2–3 笔建到 15–25%"
        stop = round(latest * 0.88, 2) if latest else None
        take = target
    elif action == "买入":
        position = "回调时分批建到 10–15%"
        stop = round(latest * 0.88, 2) if latest else None
        take = target
    elif action == "观望":
        position = "不加仓；已有仓位先留着"
        stop = round(latest * 0.90, 2) if latest else None
        take = None
    else:
        position = "维持现有仓位，单卡不超过 10%"
        stop = round(latest * 0.88, 2) if latest else None
        take = target

    score = {
        "强买入": 80,
        "买入": 62,
        "持有观察": 45,
        "观望": 34,
        "卖出/减仓": 18,
        "强卖出": 8,
        "无法判断": 0,
    }[action]
    avg_active = (metrics.get("volume") or {}).get("avg_active") or 0
    score += min(10, avg_active * 1.5)
    if drawdown is not None:
        score -= min(20, abs(drawdown) * 30)
    pressure = ((metrics.get("population") or {}).get("pressure") or {}).get("score") or 0
    score -= pressure / 12
    heat = metrics.get("heat")
    if isinstance(heat, (int, float)) and heat > 1:
        score += 3

    return {
        "action": action,
        "score": round(score, 1),
        "reasons": reasons,
        "position": position,
        "take_profit": take,
        "stop_loss": stop,
        "target": target,
    }


def _factor_lines(percentile, high_location, ret7, ret30, vol_change, divergence, drawdown) -> list[str]:
    lines = []
    if percentile is None:
        lines.append("价格在样本里的位置还算不出来。")
    elif percentile > 1:
        lines.append("最新价已经高于剔掉极端成交后的样本高点。")
    else:
        place = "高位" if high_location else ("低位" if percentile <= 0.35 else "中位")
        lines.append(f"价格处在样本{place}，分位 {percentile * 100:.0f}%。")
    parts = []
    if ret7 is not None:
        parts.append(f"7 日 {_pct(ret7)}")
    if ret30 is not None:
        parts.append(f"30 日 {_pct(ret30)}")
    if parts:
        lines.append("、".join(parts) + "。")
    if vol_change is not None:
        lines.append(f"近 7 日成交量变化 {_pct(vol_change)}，{divergence or '量价样本不足'}。")
    if drawdown is not None and drawdown <= -0.25:
        lines.append(f"样本内最大回撤 {_pct(drawdown)}。")
    return lines


def _ret(metrics, key):
    block = (metrics.get("returns") or {}).get(key) or {}
    return block.get("return")


def _pct(value) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:+.1f}%"
