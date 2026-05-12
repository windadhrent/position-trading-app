from __future__ import annotations
import json
import os
import requests
from config import LINE_TOKEN, LINE_USER_ID, RULES, RULE_SEVERITY

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_rule": None, "last_non_bull_rule": None, "deepest_rule": None}


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_last_non_bull_rule() -> str | None:
    return load_state().get("last_non_bull_rule")


def get_deepest_rule() -> str | None:
    return load_state().get("deepest_rule")


def send_line(message: str) -> bool:
    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"messages": [{"type": "text", "text": message}]}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def track_rule_change(current_rule: str) -> tuple[bool, str, str | None]:
    """
    更新持久狀態，回傳 (changed, direction, prev_rule)。
    direction: "deepen"（加深/新循環）| "recover"（恢復）| "same"（未變）

    加深規則：bull→rule1, rule1→rule2, rule2→rule3, rule3→rule4
    恢復規則：rule4→rule3, rule3→rule2, rule2→rule1, rule1→bull
    新循環：回到多頭後再次觸發 rule1 → reset deepest_rule
    """
    state = load_state()
    prev_rule = state.get("last_rule")

    if prev_rule == current_rule:
        return False, "same", prev_rule

    prev_sev = RULE_SEVERITY.get(prev_rule or "bull", 0)
    curr_sev = RULE_SEVERITY.get(current_rule, 0)
    direction = "deepen" if curr_sev > prev_sev else "recover"

    # 新循環：多頭再次進入規則一 → reset deepest_rule
    if (prev_rule == "bull" or prev_rule is None) and current_rule == "rule1":
        state["deepest_rule"] = "rule1"
        direction = "deepen"
    elif direction == "deepen":
        # 更新最深艙位記錄
        deepest = state.get("deepest_rule")
        deepest_sev = RULE_SEVERITY.get(deepest or "bull", 0)
        if curr_sev > deepest_sev:
            state["deepest_rule"] = current_rule
    # 恢復方向：deepest_rule 維持不變

    if prev_rule and prev_rule != "bull":
        state["last_non_bull_rule"] = prev_rule
    state["last_rule"] = current_rule
    save_state(state)
    return True, direction, prev_rule


def check_and_notify(current_rule: str, prev_rule: str | None,
                     direction: str, indicators: dict) -> bool:
    """依據切換方向發送 LINE 通知。"""
    if direction == "same":
        return False

    state = load_state()
    rule_info  = RULES[current_rule]
    prev_label = RULES[prev_rule]["label"] if prev_rule and prev_rule in RULES else "—"
    deepest    = state.get("deepest_rule") or current_rule

    if direction == "deepen":
        action_line = f"▶ 請再平衡至{rule_info['label']}配置"
    else:
        action_line = f"▶ 維持{RULES[deepest]['label']}持倉，不調整"

    msg = (
        f"[存股操作 再平衡警示]\n"
        f"{prev_label} → {rule_info['label']}\n"
        f"條件：{rule_info['desc']}\n\n"
        f"TAIEX：{indicators['price']:,.0f}\n"
        f"200MA：{indicators['ma200']:,.0f}\n"
        f"52W高點：{indicators['high_52w']:,.0f}\n"
        f"回撤：{indicators['drawdown_pct']:.1f}%\n\n"
        f"{action_line}"
    )
    if direction == "deepen" and "special_action" in rule_info:
        msg += f"\n\n⚠ {rule_info['special_action']}"

    send_line(msg)
    return True
