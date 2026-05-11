import streamlit as st

def _get_secret(key: str, fallback: str = "") -> str:
    try:
        return st.secrets[key]
    except Exception:
        return fallback

LINE_TOKEN   = _get_secret("LINE_TOKEN")
LINE_USER_ID = _get_secret("LINE_USER_ID")

TAIEX_SYMBOL = "^TWII"
DCA_AMOUNT = 10_000  # TWD/month

PORTFOLIO_SYMBOLS = ["006208.TW", "00675L.TW", "00757.TW", "009811.TW"]

SYMBOL_NAMES = {
    "006208.TW": "富邦台50",
    "00675L.TW": "台灣正2",
    "00757.TW":  "統一FANG+",
    "009811.TW":  "統一美國50",
    "CASH":      "現金 (TWD)",
}

# Rules state machine（台股配色：多頭紅、空頭綠）
RULES = {
    "bull": {
        "label": "多頭",
        "desc": "多頭市場 — 價格站上年線（200MA）連續 3 日",
        "color": "#c62828",          # 台股紅
        "vrect_opacity": 0.12,
        "drawdown_threshold": None,
        "requires_below_200ma": False,
    },
    "rule1": {
        "label": "規則一",
        "desc": "趨勢轉弱 — 價格同時跌破 200MA 與 60MA，連續 3 日",
        "color": "#66bb6a",          # 亮淺綠
        "vrect_opacity": 0.18,
        "drawdown_threshold": None,
        "requires_below_200ma": True,
    },
    "rule2": {
        "label": "規則二",
        "desc": "修正盤 — 從高點回撤 ≥ 20%（單日生效）",
        "color": "#388e3c",          # 中綠
        "vrect_opacity": 0.30,
        "drawdown_threshold": 20.0,
    },
    "rule3": {
        "label": "規則三",
        "desc": "空頭市場 — 從高點回撤 ≥ 30%（單日生效）",
        "color": "#1b5e20",          # 深綠
        "vrect_opacity": 0.45,
        "drawdown_threshold": 30.0,
    },
    "rule4": {
        "label": "規則四",
        "desc": "恐慌殺盤 — 從高點回撤 ≥ 40%（單日生效）",
        "color": "#00c853",          # 螢光綠（極度警示）
        "vrect_opacity": 0.60,
        "drawdown_threshold": 40.0,
        "special_action": "出清全部 006208 → 買入 00675L；美股目標鎖定 00757",
    },
}

# Leverage + US/Global ratios per rule
RULE_RATIOS = {
    "bull":  {"leverage": 0.00, "us": 0.00, "cash": 0.00},  # handled separately
    "rule1": {"leverage": 0.20, "us": 0.20, "cash": 0.60},
    "rule2": {"leverage": 0.30, "us": 0.30, "cash": 0.40},
    "rule3": {"leverage": 0.40, "us": 0.40, "cash": 0.20},
    "rule4": {"leverage": 0.50, "us": 0.50, "cash": 0.00},
}

# US equity symbols for Rules 1-3 (configurable split); Rule 4 = 00757 only
US_EQUITY_POOL = ["00757.TW", "009811.TW"]
US_EQUITY_RULE4 = "00757.TW"
