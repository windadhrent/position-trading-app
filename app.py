import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

from data import fetch_taiex, fetch_etf_prices, compute_indicators
from strategy import get_current_rule, apply_confirmation_filter, build_target_allocation, get_dca_instruction
from notifier import check_and_notify, track_rule_change, get_last_non_bull_rule
from config import RULES, PORTFOLIO_SYMBOLS, SYMBOL_NAMES, DCA_AMOUNT

st.set_page_config(
    page_title="存股操作 Position Trading APP",
    page_icon="📊",
    layout="wide",
)

st.markdown("""
<style>
    footer { visibility: hidden; }
    .main .block-container {
        padding-bottom: 20rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    /* Mobile: wrap columns and reduce font */
    @media screen and (max-width: 640px) {
        [data-testid="stHorizontalBlock"] {
            flex-wrap: wrap;
            gap: 0.5rem;
        }
        [data-testid="stHorizontalBlock"] > [data-testid="stVerticalBlockBorderWrapper"],
        [data-testid="stHorizontalBlock"] > div {
            min-width: 45% !important;
            flex: 1 1 45% !important;
        }
        [data-testid="stMetric"] label { font-size: 0.75rem !important; }
        [data-testid="stMetricValue"] { font-size: 1.1rem !important; }
        .main .block-container { padding-left: 0.5rem; padding-right: 0.5rem; }
    }
</style>
""", unsafe_allow_html=True)

# ── Sidebar (controls only — allocation added after rule computed) ─────────────
with st.sidebar:
    st.title("存股操作 設定")

    st.subheader("K 線顯示天數")
    candle_days = st.slider("天數", 60, 300, 150, step=10)

    st.divider()
    auto_notify = st.toggle("切換規則時推播 LINE", value=True)
    if st.button("手動重新整理"):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    test_mode = st.toggle("測試模式", value=False)
    if test_mode:
        test_rule = st.selectbox(
            "模擬規則",
            options=["rule1", "rule2", "rule3", "rule4"],
            format_func=lambda k: {
                "rule1": "規則一：跌破200MA",
                "rule2": "規則二：回撤 ≥ 20%",
                "rule3": "規則三：回撤 ≥ 30%",
                "rule4": "規則四：回撤 ≥ 40%",
            }[k],
        )

# ── Fetch data ────────────────────────────────────────────────────────────────
with st.spinner("載入市場資料..."):
    df_raw   = fetch_taiex()
    etf_px   = fetch_etf_prices()
    ind      = compute_indicators(df_raw)

df_chart = df_raw.iloc[-candle_days:].copy()
price        = ind["price"]
ma200        = ind["ma200"]
high_52w     = ind["high_52w"]
drawdown_pct = ind["drawdown_pct"]
above_200ma  = ind["above_200ma"]

us_weights = {"00757.TW": 0.5, "009811.TW": 0.5}
eff_us_w   = us_weights

# ── 3 日確認濾波（過濾假突破）────────────────────────────────────────────────
_N_CONFIRM = 3
_df_conf = ind["df"].copy()
_df_conf["MA60"]    = _df_conf["Close"].rolling(60, min_periods=1).mean()
_df_conf["High52W"] = _df_conf["Close"].rolling(252, min_periods=1).max()
_df_conf["DD"]      = (_df_conf["Close"] - _df_conf["High52W"]) / _df_conf["High52W"] * 100
_df_conf["AbvMA"]   = _df_conf["Close"] > _df_conf["MA200"]
_df_conf["AbvMA60"] = _df_conf["Close"] > _df_conf["MA60"]
_df_conf["RawRule"] = _df_conf.apply(
    lambda r: get_current_rule(bool(r["AbvMA"]), float(r["DD"])), axis=1
)
_df_conf["ConfRule"] = apply_confirmation_filter(
    _df_conf["RawRule"], _N_CONFIRM, above_60ma=_df_conf["AbvMA60"]
)
rule_key = _df_conf["ConfRule"].iloc[-1]

if test_mode:
    rule_key = test_rule
    _sim = {"rule1": (-5.0, False), "rule2": (-22.0, False),
            "rule3": (-32.0, False), "rule4": (-42.0, False)}
    drawdown_pct, above_200ma = _sim[test_rule]

rule_info  = RULES[rule_key]

track_rule_change(rule_key)
if auto_notify:
    check_and_notify(rule_key, ind)

# ── Sidebar (allocation panel — rendered after rule is known) ─────────────────
_ALLOC_LABELS = {
    "006208.TW": "富邦台50 (006208)",
    "00675L.TW": "台灣正2 (00675L)",
    "00757.TW":  "統一FANG+ (00757)",
    "009811.TW": "統一美國50 (009811)",
    "CASH":      "現金",
}
_ALLOC_ORDER = ["006208.TW", "00675L.TW", "00757.TW", "009811.TW", "CASH"]

with st.sidebar:
    st.divider()
    st.subheader(f"配置說明 ({rule_info['label']})")
    target_alloc_sidebar = build_target_allocation(rule_key, eff_us_w)

    # DCA 永遠固定，與規則無關
    st.caption("每月 DCA 投入（固定）")
    _dca_syms = ["00675L.TW", "00757.TW"] if rule_key == "rule4" else ["006208.TW", "009811.TW"]
    for sym in _dca_syms:
        col_l, col_r = st.columns([3, 1])
        col_l.caption(_ALLOC_LABELS[sym])
        col_r.markdown("**50%**")

    st.divider()

    # 原持倉 / 持倉目標：全部以規則定義顯示
    if rule_key == "bull":
        # 從歷史確認序列往回掃，找最近一次非多頭規則（不依賴 state.json）
        _hist_non_bull = [r for r in _df_conf["ConfRule"] if r != "bull"]
        prev_rule = _hist_non_bull[-1] if _hist_non_bull else get_last_non_bull_rule()
        if prev_rule:
            prev_alloc = build_target_allocation(prev_rule, eff_us_w)
            st.caption(f"原持倉（{RULES[prev_rule]['label']} 配置，持有不調整）")
            for sym in ["00675L.TW", "00757.TW", "009811.TW", "CASH"]:
                pct = prev_alloc.get(sym, 0.0) * 100
                col_l, col_r = st.columns([3, 1])
                col_l.caption(_ALLOC_LABELS[sym])
                col_r.markdown(f"**{pct:.0f}%**")
        else:
            st.caption("原持倉（尚未觸發過規則）")
            for sym in ["00675L.TW", "00757.TW", "CASH"]:
                col_l, col_r = st.columns([3, 1])
                col_l.caption(_ALLOC_LABELS[sym])
                col_r.markdown("**—**")
    else:
        st.caption("持倉目標比例（再平衡基準）")
        for sym in ["00675L.TW", "00757.TW", "009811.TW", "CASH"]:
            pct = target_alloc_sidebar.get(sym, 0.0) * 100
            col_l, col_r = st.columns([3, 1])
            col_l.caption(_ALLOC_LABELS[sym])
            col_r.markdown(f"**{pct:.0f}%**")

# ── Header ────────────────────────────────────────────────────────────────────
st.title("存股操作 Position Trading APP")
st.caption(f"資料更新每 15 分鐘 ｜ TAIEX 最後收盤：{df_raw.index[-1].strftime('%Y-%m-%d')}")

# ── KPI Row ───────────────────────────────────────────────────────────────────
k1, k2 = st.columns(2)
k1.metric("TAIEX", f"{price:,.0f}")
k2.metric("200MA", f"{ma200:,.0f}", delta=f"{price - ma200:+,.0f}")
k3, k4, k5 = st.columns(3)
k3.metric("52W 高點", f"{high_52w:,.0f}")
k4.metric("回撤 %", f"{drawdown_pct:.1f}%")
k5.metric("200MA 相對位置",
          "上方 ✓" if above_200ma else "下方 ✗",
          delta_color="normal" if above_200ma else "inverse")


# ── State Banner ──────────────────────────────────────────────────────────────
st.divider()
banner_col, status_col = st.columns([1, 3])

with banner_col:
    st.markdown(
        f"""<div style="background:{rule_info['color']};padding:24px 16px;
            border-radius:12px;text-align:center;">
            <div style="font-size:2.2rem;font-weight:900;color:white;
                text-shadow:0 2px 4px rgba(0,0,0,.4);">{rule_info['label']}</div>
        </div>""",
        unsafe_allow_html=True,
    )

with status_col:
    st.markdown(f"### {rule_info['desc']}")
    if "special_action" in rule_info:
        st.error(f"⚠ {rule_info['special_action']}")

    abs_dd = abs(drawdown_pct)
    checks = [
        ("價格跌破年線（規則一）",  not above_200ma,  None),
        ("回撤 ≥ 20%（規則二）",    abs_dd >= 20,     20.0),
        ("回撤 ≥ 30%（規則三）",    abs_dd >= 30,     30.0),
        ("回撤 ≥ 40%（規則四）",    abs_dd >= 40,     40.0),
    ]
    for label, triggered, threshold in checks:
        if triggered:
            st.markdown(f"✅ **{label}** — 已觸發")
        else:
            note = f"（現 {abs_dd:.1f}% / 需 {threshold:.0f}%）" if threshold else ""
            st.markdown(f"⬜ {label} — 未觸發 {note}")

# ── K-Line Chart ──────────────────────────────────────────────────────────────
st.divider()
st.subheader("TAIEX K 線圖")

fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                    row_heights=[0.75, 0.25], vertical_spacing=0.03)

fig.add_trace(go.Candlestick(
    x=df_chart.index,
    open=df_chart["Open"], high=df_chart["High"],
    low=df_chart["Low"],   close=df_chart["Close"],
    name="TAIEX",
    increasing_line_color="#ef5350",
    decreasing_line_color="#26a69a",
), row=1, col=1)

ma200_series = df_chart["Close"].rolling(200, min_periods=1).mean()
fig.add_trace(go.Scatter(
    x=df_chart.index, y=ma200_series,
    name="200MA", line=dict(color="#ff9800", width=2),
), row=1, col=1)

fig.add_hline(y=high_52w, line_dash="dot", line_color="#9c27b0",
              annotation_text=f"52W High {high_52w:,.0f}", row=1, col=1)

fig.add_trace(go.Bar(
    x=df_chart.index, y=df_chart["Volume"],
    name="成交量", marker_color="#78909c", opacity=0.6,
), row=2, col=1)

fig.update_layout(height=520, xaxis_rangeslider_visible=False,
                  template="plotly_dark",
                  legend=dict(orientation="h", y=1.02),
                  margin=dict(l=0, r=0, t=30, b=0))
st.plotly_chart(fig, use_container_width=True)

# ── DCA Instruction ───────────────────────────────────────────────────────────
st.divider()
st.subheader(f"本月 DCA 指令  （預算 TWD {DCA_AMOUNT:,}）")

dca_rows = get_dca_instruction(rule_key, etf_px, eff_us_w, DCA_AMOUNT)
if dca_rows:
    dca_cols = st.columns(len(dca_rows))
    for col, row in zip(dca_cols, dca_rows):
        sym      = row["symbol"]
        cn_name  = SYMBOL_NAMES.get(sym, sym)
        ticker   = sym.replace(".TW", "") if sym != "CASH" else ""
        label    = f"{cn_name}（{ticker}）" if ticker else cn_name
        if sym == "CASH":
            col.metric(label, f"TWD {row['amount']:,.0f}", "保留現金")
        else:
            zhang  = row["units"]
            shares = row.get("shares", 0)
            if zhang >= 1:
                unit_str = f"約 {zhang} 張"
            else:
                unit_str = f"0 張（零股 {shares} 股）"
            col.metric(
                label,
                f"TWD {row['amount']:,.0f}",
                f"{unit_str}  @每張 ${row['price'] * 1000:,.0f}",
            )

    if rule_key == "rule4":
        st.error("規則四：DCA 改為 台灣正2（00675L）+ 統一FANG+（00757）各 50%；出清全部 006208")
    else:
        st.info("無論多空：每月固定 DCA 富邦台50（006208）$5,000 + 統一美國50（009811）$5,000")


# ── Rules Reference ───────────────────────────────────────────────────────────
with st.expander("所有規則對照表"):
    ref = []
    for key, r in RULES.items():
        from config import RULE_RATIOS
        ratio = RULE_RATIOS[key]
        us_note = "僅 00757" if key == "rule4" else "00757 / 009811"
        ref.append({
            "規則": r["label"],
            "觸發條件": r["desc"],
            "操作說明": "僅每月 DCA，不調整持倉" if key == "bull" else "調整整體持倉至目標比例",
            "台灣正2 (00675L)": f"{ratio['leverage']*100:.0f}%",
            "美股 ETF": f"{ratio['us']*100:.0f}%（{us_note}）" if key != "bull" else "DCA 006208 + 009811 各50%",
            "現金": f"{ratio['cash']*100:.0f}%",
            "富邦台50 (006208)": "DCA 50%" if key == "bull" else ("出清" if key == "rule4" else "—"),
            "統一美國50 (009811)": "DCA 50%" if key == "bull" else "—",
        })
    st.dataframe(pd.DataFrame(ref), use_container_width=True, hide_index=True)
    st.caption("⏱ 時間過濾：僅「多頭 → 規則一」（跌破 200MA）需連續 3 個交易日確認，且同時跌破 60MA 才觸發；回撤規則（規則二/三/四）及所有返多頭切換均為單日生效。")

# ── Backtest ──────────────────────────────────────────────────────────────────
with st.expander("📅 規則回測（歷史觸發紀錄）"):
    # 對全部歷史資料滾動計算指標
    df_bt = df_raw.copy()
    df_bt["MA200"]     = df_bt["Close"].rolling(200, min_periods=1).mean()
    df_bt["MA60"]      = df_bt["Close"].rolling(60,  min_periods=1).mean()
    df_bt["High52W"]   = df_bt["Close"].rolling(252, min_periods=1).max()
    df_bt["DD"]        = (df_bt["Close"] - df_bt["High52W"]) / df_bt["High52W"] * 100
    df_bt["AboveMA"]   = df_bt["Close"] > df_bt["MA200"]
    df_bt["AboveMA60"] = df_bt["Close"] > df_bt["MA60"]
    df_bt["RawRule"] = df_bt.apply(
        lambda r: get_current_rule(bool(r["AboveMA"]), float(r["DD"])), axis=1
    )
    df_bt["Rule"] = df_bt["RawRule"]  # 無濾波原始規則

    # 篩選顯示範圍（預設 2025 全年）
    col_bt1, col_bt2 = st.columns([2, 3])
    with col_bt1:
        bt_year = st.selectbox("顯示年度", [2025, 2024, 2023, 2022], index=0, key="bt_year")
    with col_bt2:
        use_filter = st.toggle("啟用 3 日確認濾波", value=True, key="bt_use_filter",
                               help="連續 3 個交易日出現同一信號才切換規則，過濾假突破")
    df_show = df_bt[df_bt.index.year == bt_year].copy()

    if df_show.empty:
        st.warning("該年度無資料")
    else:
        # 計算濾波後規則（3 日確認 + 60MA 入場條件）
        df_show["FilteredRule"] = apply_confirmation_filter(
            df_show["RawRule"], n_confirm=3, above_60ma=df_show["AboveMA60"]
        )
        active_rule_col = "FilteredRule" if use_filter else "Rule"

        def _count_transitions(series: "pd.Series") -> list[dict]:
            rows, prev = [], None
            for dt, r in series.items():
                if r != prev:
                    if prev is not None:
                        rows.append({
                            "日期":       dt.strftime("%Y-%m-%d"),
                            "切換":       f"{RULES[prev]['label']} → {RULES[r]['label']}",
                            "TAIEX":     f"{df_show.loc[dt, 'Close']:,.0f}",
                            "回撤%":     f"{df_show.loc[dt, 'DD']:.1f}%",
                            "200MA上方": "✓" if df_show.loc[dt, "AboveMA"] else "✗",
                        })
                    prev = r
            return rows

        raw_trans      = _count_transitions(df_show["Rule"])
        filtered_trans = _count_transitions(df_show["FilteredRule"])
        active_trans   = filtered_trans if use_filter else raw_trans

        # ── K 線圖 + 規則色帶 ──
        fig_bt = make_subplots(rows=2, cols=1, shared_xaxes=True,
                               row_heights=[0.75, 0.25], vertical_spacing=0.03)
        fig_bt.add_trace(go.Candlestick(
            x=df_show.index,
            open=df_show["Open"], high=df_show["High"],
            low=df_show["Low"],   close=df_show["Close"],
            name="TAIEX",
            increasing_line_color="#ef5350",
            decreasing_line_color="#26a69a",
            showlegend=False,
        ), row=1, col=1)
        fig_bt.add_trace(go.Scatter(
            x=df_show.index, y=df_show["MA200"],
            name="200MA", line=dict(color="#ff9800", width=1.5),
        ), row=1, col=1)
        fig_bt.add_trace(go.Bar(
            x=df_show.index, y=df_show["Volume"],
            name="成交量", marker_color="#78909c", opacity=0.5, showlegend=False,
        ), row=2, col=1)

        # 規則色帶（依選擇的欄位）
        rule_run_start = df_show.index[0]
        rule_run_key   = df_show[active_rule_col].iloc[0]
        for dt, row in df_show.iterrows():
            if row[active_rule_col] != rule_run_key:
                fig_bt.add_vrect(
                    x0=rule_run_start, x1=dt,
                    fillcolor=RULES[rule_run_key]["color"],
                    opacity=RULES[rule_run_key].get("vrect_opacity", 0.15),
                    line_width=0, row=1, col=1,
                )
                rule_run_start = dt
                rule_run_key   = row[active_rule_col]
        fig_bt.add_vrect(
            x0=rule_run_start, x1=df_show.index[-1],
            fillcolor=RULES[rule_run_key]["color"],
            opacity=RULES[rule_run_key].get("vrect_opacity", 0.15),
            line_width=0, row=1, col=1,
        )

        fig_bt.update_layout(
            height=480, xaxis_rangeslider_visible=False,
            template="plotly_dark",
            legend=dict(orientation="h", y=1.02),
            margin=dict(l=0, r=0, t=30, b=0),
        )
        st.plotly_chart(fig_bt, use_container_width=True)

        # ── 切換統計比較 ──
        c1, c2 = st.columns(2)
        c1.metric("原始切換次數（無濾波）", len(raw_trans))
        c2.metric("濾波後切換次數（3日確認）", len(filtered_trans),
                  delta=len(filtered_trans) - len(raw_trans),
                  delta_color="inverse")

        # ── 切換紀錄表 ──
        if active_trans:
            st.caption(f"{'濾波後' if use_filter else '原始'} 共 {len(active_trans)} 次規則切換（alarm）")
            st.dataframe(pd.DataFrame(active_trans), use_container_width=True, hide_index=True)
        else:
            st.info(f"{bt_year} 全年維持同一規則，無切換。")

# ── 外部工具連結 ──────────────────────────────────────────────────────────────
st.divider()
st.link_button("台股投資組合計算器", "https://tool.yp-finance.com/twportfolio/0abfed7d-1d2c-4f25-b4ae-08ed5f9ba1b8")

# ── 底部空白（確保可捲動到底）────────────────────────────────────────────────
st.markdown("<br>" * 8, unsafe_allow_html=True)
