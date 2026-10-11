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

    action = "持有观察"
    reasons = []
    if ret30 is not None and ret30 < -0.20 and drawdown is not None and drawdown <= -0.40:
        action = "强卖出"
        reasons.append(f"30 日收益 {_pct(ret30)}，最大回撤 {_pct(drawdown)}，趋势和回撤同时恶化。")
    elif ret7 is not None and ret7 > 0.20 and vol_change is not None and vol_change < -0.50:
        action = "卖出/减仓"
        reasons.append(f"7 日收益 {_pct(ret7)}，但成交量变化 {_pct(vol_change)}，属于放量不足的急涨。")
    elif ret7 is not None and ret7 > 0 and ret30 is not None and ret30 < 0 and vol_change is not None and vol_change > -0.50:
        action = "强买入"
        reasons.append(f"30 日收益 {_pct(ret30)} 仍为负，7 日收益 {_pct(ret7)} 转正，且量能没有崩掉。")
    elif ret7 is not None and ret7 > 0 and vol_change is not None and vol_change < -0.60:
        action = "观望"
        reasons.append(f"价格上涨但 7 日成交量变化 {_pct(vol_change)}，缩量过深。")
    elif ret7 is not None and ret7 > 0 and vol_change is not None and vol_change > -0.50:
        action = "买入"
        reasons.append(f"7 日收益 {_pct(ret7)}，量价关系为{divergence}。")
    else:
        if divergence:
            reasons.append(f"当前量价信号是{divergence}，没有触发明确的进出场规则。")
        else:
            reasons.append("窗口数据还不够形成方向判断。")

    if drawdown is not None and drawdown <= -0.40 and action in {"强买入", "买入"}:
        reasons.append(f"最大回撤已到 {_pct(drawdown)}，这是反弹信号，仓位按下限。")
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


def _ret(metrics, key):
    block = (metrics.get("returns") or {}).get(key) or {}
    return block.get("return")


def _pct(value) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:+.1f}%"
