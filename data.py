import math
import yfinance as yf
import pandas as pd
import streamlit as st
from config import TAIEX_SYMBOL, PORTFOLIO_SYMBOLS


@st.cache_data(ttl=900)
def fetch_taiex() -> pd.DataFrame:
    """Pull 5 years of TAIEX daily OHLCV via Ticker.history (more reliable on cloud)."""
    df = yf.Ticker(TAIEX_SYMBOL).history(period="5y", interval="1d")
    if df.empty:
        raise RuntimeError("無法取得 TAIEX 資料，請稍後再試")
    # 移除時區資訊，避免雲端環境 tz-aware index 問題
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df = df.dropna(subset=["Close"])
    return df


@st.cache_data(ttl=900)
def fetch_etf_prices() -> dict[str, float]:
    """Latest close price for each ETF — fetched individually for reliability."""
    prices: dict[str, float] = {}
    for sym in PORTFOLIO_SYMBOLS:
        try:
            hist = yf.Ticker(sym).history(period="3d")
            prices[sym] = float(hist["Close"].dropna().iloc[-1]) if not hist.empty else 0.0
        except Exception:
            prices[sym] = 0.0
    return prices


def compute_indicators(df: pd.DataFrame) -> dict:
    """Derive 200MA, 60MA, 52-week high, drawdown from TAIEX dataframe."""
    if df.empty or "Close" not in df.columns:
        raise RuntimeError("無法取得 TAIEX 資料，請稍後再試")
    df = df.copy()
    df["MA200"] = df["Close"].rolling(200).mean()
    df["MA60"]  = df["Close"].rolling(60).mean()

    price  = float(df["Close"].iloc[-1])
    ma200  = float(df["MA200"].iloc[-1])
    ma60   = float(df["MA60"].iloc[-1])

    lookback = df["Close"].iloc[-252:] if len(df) >= 252 else df["Close"]
    high_52w = float(lookback.max())

    drawdown_pct = (price - high_52w) / high_52w * 100  # negative

    above_200ma = (not math.isnan(ma200)) and (price > ma200)
    above_60ma  = (not math.isnan(ma60))  and (price > ma60)

    return {
        "price":        price,
        "ma200":        ma200,
        "ma60":         ma60,
        "high_52w":     high_52w,
        "drawdown_pct": drawdown_pct,
        "above_200ma":  above_200ma,
        "above_60ma":   above_60ma,
        "df":           df,
    }
