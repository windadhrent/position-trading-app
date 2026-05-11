import pandas as pd
from config import (
    RULES, RULE_RATIOS, DCA_AMOUNT,
    PORTFOLIO_SYMBOLS, US_EQUITY_POOL, US_EQUITY_RULE4,
)


# ── State detection ───────────────────────────────────────────────────────────

def get_current_rule(above_200ma: bool, drawdown_pct: float) -> str:
    """
    Drawdown rules take priority over the 200MA rule.
    drawdown_pct is negative (e.g. -25 means 25% below peak).
    """
    abs_dd = abs(drawdown_pct)
    if abs_dd >= 40:
        return "rule4"
    if abs_dd >= 30:
        return "rule3"
    if abs_dd >= 20:
        return "rule2"
    if not above_200ma:
        return "rule1"
    return "bull"


def apply_confirmation_filter(raw_rules: "pd.Series", n_confirm: int = 3,
                              above_60ma: "pd.Series | None" = None) -> "pd.Series":
    """
    只有 bull→rule1（跌破 200MA）需要連續 n_confirm 日確認，且同時需跌破 60MA。
    其餘所有規則切換（回撤觸發 rule2/3/4 及任何返多頭）均為單日生效。
    """
    confirmed = []
    current = raw_rules.iloc[0]
    for i in range(len(raw_rules)):
        candidate = raw_rules.iloc[i]

        if current == "bull" and candidate == "rule1":
            # 唯一需要 N 日確認 + 60MA 的路徑
            if i >= n_confirm - 1:
                window = raw_rules.iloc[i - n_confirm + 1: i + 1]
                if window.nunique() == 1:
                    if above_60ma is None or not bool(above_60ma.iloc[i]):
                        current = candidate
            # 未滿 N 日或 60MA 仍撐住 → 維持 bull
        else:
            # 其餘切換：回撤規則、任何返多頭 → 單日生效
            current = candidate

        confirmed.append(current)
    return pd.Series(confirmed, index=raw_rules.index)


# ── Target allocation builder ─────────────────────────────────────────────────

def build_target_allocation(rule_key: str,
                             us_weights: dict[str, float] | None = None
                             ) -> dict[str, float]:
    """
    Return {symbol: weight} that sums to 1.0.
    CASH is included as a symbol.

    us_weights: custom split for Rules 1-3 US equity (must sum to 1.0).
                Ignored for BULL (uses 006208+00911) and Rule 4 (00757 only).
    """
    if rule_key == "bull":
        return {"006208.TW": 0.50, "009811.TW": 0.50, "CASH": 0.00}

    ratios = RULE_RATIOS[rule_key]
    alloc_lev = ratios["leverage"]
    alloc_us  = ratios["us"]
    alloc_csh = ratios["cash"]

    result: dict[str, float] = {}
    result["00675L.TW"] = alloc_lev

    if rule_key == "rule4":
        # US target must be 00757 only
        result[US_EQUITY_RULE4] = alloc_us
    else:
        # Rules 1-3: split US equity per us_weights (default equal)
        if us_weights is None:
            n = len(US_EQUITY_POOL)
            us_weights = {s: 1 / n for s in US_EQUITY_POOL}
        for sym, w in us_weights.items():
            result[sym] = alloc_us * w

    result["CASH"] = alloc_csh
    return result


# ── Unit-based rebalance ──────────────────────────────────────────────────────

LOT_SIZE = 1000  # 台股 1 張 = 1000 股，yfinance 報的是每股價格


def compute_rebalance(
    target_alloc: dict[str, float],
    current_units: dict[str, float],  # 單位：張
    current_cash: float,
    prices: dict[str, float],         # 單位：每股 TWD（yfinance 原始值）
) -> tuple[float, list[dict]]:
    """
    Compute exact 張 to buy/sell.
    current_units 為張數，prices 為每股價格，value = 張 × 1000 × 股價。
    """
    equity_value = sum(
        current_units.get(sym, 0) * prices.get(sym, 0) * LOT_SIZE
        for sym in PORTFOLIO_SYMBOLS
    )
    total_value = equity_value + current_cash

    rows = []

    for sym in PORTFOLIO_SYMBOLS:
        price          = prices.get(sym, 0)
        price_per_lot  = price * LOT_SIZE          # 每張成本
        cur_zhang      = int(current_units.get(sym, 0))
        cur_val        = cur_zhang * price_per_lot

        target_w       = target_alloc.get(sym, 0.0)
        target_val     = total_value * target_w
        target_zhang   = int(target_val / price_per_lot) if price_per_lot > 0 else 0

        delta_zhang    = target_zhang - cur_zhang
        delta_val      = delta_zhang * price_per_lot

        if delta_zhang > 0:
            action = "BUY"
        elif delta_zhang < 0:
            action = "SELL"
        else:
            action = "HOLD"

        rows.append({
            "symbol":       sym,
            "price":        price,
            "price_per_lot": price_per_lot,
            "cur_units":    cur_zhang,
            "cur_value":    cur_val,
            "target_pct":   target_w * 100,
            "target_value": target_val,
            "target_units": target_zhang,
            "delta_units":  delta_zhang,
            "delta_value":  delta_val,
            "action":       action,
        })

    # Cash row
    target_cash_w   = target_alloc.get("CASH", 0.0)
    target_cash_val = total_value * target_cash_w
    delta_cash      = target_cash_val - current_cash

    rows.append({
        "symbol":        "CASH",
        "price":         1.0,
        "price_per_lot": 1.0,
        "cur_units":     int(current_cash),
        "cur_value":     current_cash,
        "target_pct":    target_cash_w * 100,
        "target_value":  target_cash_val,
        "target_units":  int(target_cash_val),
        "delta_units":   int(delta_cash),
        "delta_value":   delta_cash,
        "action":        "ADD" if delta_cash > 100 else ("REDUCE" if delta_cash < -100 else "HOLD"),
    })

    return total_value, rows


# ── DCA instruction ───────────────────────────────────────────────────────────

def get_dca_instruction(rule_key: str,
                         prices: dict[str, float],
                         us_weights: dict[str, float] | None = None,
                         dca_amount: float = DCA_AMOUNT) -> list[dict]:
    """
    DCA 永遠是 006208 + 009811 各 50%，與市場規則無關。
    唯一例外：規則四觸發時改為 00675L + 00757 各 50%（同時出清 006208）。
    """
    if rule_key == "rule4":
        dca_alloc = {"00675L.TW": 0.5, "00757.TW": 0.5}
    else:
        dca_alloc = {"006208.TW": 0.5, "009811.TW": 0.5}

    result = []
    for sym, w in dca_alloc.items():
        amount        = dca_amount * w
        price         = prices.get(sym, 0)
        price_per_lot = price * LOT_SIZE
        zhang         = int(amount / price_per_lot) if price_per_lot > 0 else 0
        shares        = int(amount / price) if price > 0 else 0
        result.append({
            "symbol": sym,
            "amount": amount,
            "price":  price,
            "units":  zhang,
            "shares": shares,
        })

    return result
