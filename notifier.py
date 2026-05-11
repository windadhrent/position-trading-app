import json
import os
import requests
from config import LINE_TOKEN, LINE_USER_ID, RULES

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_rule": None, "last_non_bull_rule": None}


def get_last_non_bull_rule() -> str | None:
    return load_state().get("last_non_bull_rule")


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def send_line(message: str) -> bool:
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": message}]}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def track_rule_change(current_rule: str) -> bool:
    """持久化規則切換狀態，無論 LINE 是否啟用都執行。回傳是否有切換。"""
    state = load_state()
    last_rule = state.get("last_rule")
    if last_rule == current_rule:
        return False
    if last_rule and last_rule != "bull":
        state["last_non_bull_rule"] = last_rule
    state["last_rule"] = current_rule
    save_state(state)
    return True


def check_and_notify(current_rule: str, indicators: dict) -> bool:
    """Send LINE alert when rule changes. Returns True if sent."""
    state = load_state()
    last_rule = state.get("last_rule")

    if last_rule == current_rule:
        return False

    rule_info  = RULES[current_rule]
    prev_label = RULES[last_rule]["label"] if last_rule in RULES else "—"

    msg = (
        f"[存股操作 再平衡警示]\n"
        f"{prev_label} → {rule_info['label']}\n"
        f"條件：{rule_info['desc']}\n\n"
        f"TAIEX：{indicators['price']:,.0f}\n"
        f"200MA：{indicators['ma200']:,.0f}\n"
        f"52W高點：{indicators['high_52w']:,.0f}\n"
        f"回撤：{indicators['drawdown_pct']:.1f}%"
    )
    if "special_action" in rule_info:
        msg += f"\n\n⚠ {rule_info['special_action']}"

    send_line(msg)
    return True
