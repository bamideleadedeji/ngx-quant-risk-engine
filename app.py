"""
NGX Quantitative Engine - Self-Funding Cashless Rebalancer & Midnight Bamboo Order-Ticket Generator
Tracks live CSCS/Bamboo holdings, trims overweight gainers to fund underweight blue-chips without external cash,
and computes +1.25% pre-market limit prices for 12:00 AM WAT execution.
"""

import os
import json
import math
from datetime import datetime
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(
    page_title="NGX Quant Risk Engine",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main { background-color: #0e1117; }
    .stMetric { background-color: #1e222d; padding: 15px; border-radius: 8px; border: 1px solid #2a2e39; }
    .stButton>button { width: 100%; background-color: #00c853; color: white; font-weight: bold; border-radius: 6px; }
    </style>
    """,
    unsafe_allow_html=True,
)

STATE_FILE = "ngx_portfolio_state.json"
AUDIT_FILE = "ngx_trade_audit.csv"

DEFAULT_HOLDINGS = [
    {"Ticker": "BUAFOODS", "Company": "BUA Foods Plc", "Units": 50.0, "Avg_Cost": 700.00, "Live_Price": 760.60, "Target_Weight_Pct": 16.0},
    {"Ticker": "SEPLAT", "Company": "Seplat Energy Plc", "Units": 2.0, "Avg_Cost": 16000.10, "Live_Price": 16241.90, "Target_Weight_Pct": 16.0},
    {"Ticker": "GTCO", "Company": "Guaranty Trust Holding Co.", "Units": 200.0, "Avg_Cost": 120.90, "Live_Price": 117.00, "Target_Weight_Pct": 16.0},
    {"Ticker": "MTNN", "Company": "MTN Nigeria Comm. Plc", "Units": 15.0, "Avg_Cost": 825.00, "Live_Price": 837.00, "Target_Weight_Pct": 12.0},
    {"Ticker": "ZENITHBANK", "Company": "Zenith Bank Plc", "Units": 100.0, "Avg_Cost": 116.60, "Live_Price": 116.00, "Target_Weight_Pct": 12.0},
    {"Ticker": "OKOMUOIL", "Company": "Okomu Oil Palm Plc", "Units": 10.0, "Avg_Cost": 1148.60, "Live_Price": 1137.09, "Target_Weight_Pct": 10.0},
    {"Ticker": "UNILEVER", "Company": "Unilever Nigeria Plc", "Units": 90.0, "Avg_Cost": 111.92, "Live_Price": 112.20, "Target_Weight_Pct": 10.0},
    {"Ticker": "TRANSCOHOT", "Company": "Transcorp Hotels Plc", "Units": 20.0, "Avg_Cost": 275.30, "Live_Price": 290.50, "Target_Weight_Pct": 8.0},
]


def load_portfolio_state() -> tuple[pd.DataFrame, float]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                df = pd.DataFrame(data.get("holdings", DEFAULT_HOLDINGS))
                cash = float(data.get("free_cash_ngn", 0.0))
                if not df.empty:
                    return df, cash
        except Exception:
            pass
    return pd.DataFrame(DEFAULT_HOLDINGS), 0.0


def save_portfolio_state(df: pd.DataFrame, free_cash_ngn: float):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "free_cash_ngn": float(free_cash_ngn),
                "holdings": df.to_dict(orient="records"),
            }, f, indent=2)
    except Exception:
        pass


def fetch_latest_ngx_prices(tickers: list[str]) -> dict[str, float]:
    prices = {}
    try:
        import yfinance as yf
        for t in tickers:
            clean = t.strip().upper()
            for suffix in (".LG", ".NS", ""):
                try:
                    hist = yf.Ticker(f"{clean}{suffix}").history(period="5d")
                    if not hist.empty:
                        val = float(hist["Close"].iloc[-1])
                        if val > 0:
                            prices[clean] = round(val, 2)
                            break
                except Exception:
                    continue
    except Exception:
        pass
    return prices


st.sidebar.title("🕹️ NGX Execution Controls")
st.sidebar.markdown("---")
st.sidebar.info("🚀 **Mode:** Self-Funding Cashless Rebalancer + 12:00 AM WAT Bamboo Order Ticket")

free_cash_ngn = st.sidebar.number_input(
    "Cleared Bamboo NGN Cash / New Deposit (₦)",
    min_value=0.0,
    max_value=500000000.0,
    value=0.0,
    step=500.0,
    format="%.2f",
    help="Set to ₦0.00 for 100% self-funding internal rebalancing, or enter any new deposit you added."
)

drift_threshold_pct = st.sidebar.slider(
    "Rebalance Drift Trigger Band (%)",
    min_value=1.5,
    max_value=10.0,
    value=3.0,
    step=0.5,
)

buy_buffer_pct = st.sidebar.slider(
    "12:00 AM Pre-Market Buy Limit Buffer (%)",
    min_value=0.50,
    max_value=3.00,
    value=1.25,
    step=0.25,
    help="Adds +1.25% (e.g., ₦24.00 -> ₦24.30) to clear NGX/SEC/CSCS fees (~1.5%) & 10:00 AM opening auction."
)

sell_buffer_pct = st.sidebar.slider(
    "12:00 AM Pre-Market Sell Limit Buffer (%)",
    min_value=0.00,
    max_value=2.50,
    value=1.00,
    step=0.25,
    help="Subtracts 1.00% from close price so overweight trim orders fill reliably at market open."
)

min_order_floor = st.sidebar.number_input(
    "Minimum Bamboo Order Value (₦)",
    min_value=500.0,
    max_value=25000.0,
    value=1500.0,
    step=250.0,
)

st.title("📈 NGX Self-Funding Portfolio & Midnight Bamboo Order Engine")
st.caption("CSCS-Verified Nigerian Exchange Rebalancer | Internal Winner-Trimming & +1.25% Pre-Market Limit Execution")
st.markdown("---")

tab_rebalance, tab_ledger = st.tabs([
    "⚖️ Self-Funding Rebalancer & 12:00 AM Order Ticket",
    "📋 Execution Audit Ledger (ngx_trade_audit.csv)",
])

with tab_rebalance:
    df_saved, saved_cash = load_portfolio_state()
    effective_cash = free_cash_ngn if free_cash_ngn > 0 else saved_cash

    col_btn1, col_btn2 = st.columns([1, 2])
    with col_btn1:
        if st.button("🔄 Sync Latest Yahoo NGX Prices"):
            live_map = fetch_latest_ngx_prices(df_saved["Ticker"].tolist())
            if live_map:
                df_saved["Live_Price"] = df_saved.apply(
                    lambda r: live_map.get(r["Ticker"].upper(), r["Live_Price"]), axis=1
                )
                save_portfolio_state(df_saved, effective_cash)
                st.success(f"Synced {len(live_map)} NGX prices from market feed.")
            else:
                st.warning("Yahoo NGX feed returned delayed/empty quotes; edit Live_Price directly in the table below from your Bamboo app.")

    st.subheader("1. Live Bamboo / CSCS Holdings (Edit Units or Prices Anytime)")
    edited_df = st.data_editor(
        df_saved,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "Units": st.column_config.NumberColumn("Units Held", min_value=0.0, format="%.2f"),
            "Avg_Cost": st.column_config.NumberColumn("Avg Cost (₦)", min_value=0.0, format="%.2f"),
            "Live_Price": st.column_config.NumberColumn("Current Price (₦)", min_value=0.01, format="%.2f"),
            "Target_Weight_Pct": st.column_config.NumberColumn("Target Weight (%)", min_value=0.0, max_value=100.0, format="%.1f"),
        },
        key="ngx_holdings_editor",
    )

    if st.button("💾 Save Updated Holdings & Cash"):
        save_portfolio_state(edited_df, effective_cash)
        st.success("Saved updated holdings and cash balance.")

    calc_df = edited_df.copy()
    calc_df["Cost_Value"] = calc_df["Units"] * calc_df["Avg_Cost"]
    calc_df["Market_Value"] = calc_df["Units"] * calc_df["Live_Price"]
    calc_df["Unrealized_PnL"] = calc_df["Market_Value"] - calc_df["Cost_Value"]
    calc_df["Return_Pct"] = ((calc_df["Live_Price"] - calc_df["Avg_Cost"]) / calc_df["Avg_Cost"].replace(0, 1)) * 100.0

    equity_total = float(calc_df["Market_Value"].sum())
    cost_total = float(calc_df["Cost_Value"].sum())
    total_portfolio = equity_total + effective_cash
    total_pnl = equity_total - cost_total

    weight_sum = float(calc_df["Target_Weight_Pct"].sum())
    calc_df["Norm_Target_Pct"] = (calc_df["Target_Weight_Pct"] / weight_sum * 100.0) if weight_sum > 0 else 0.0
    calc_df["Actual_Weight_Pct"] = (calc_df["Market_Value"] / total_portfolio * 100.0) if total_portfolio > 0 else 0.0
    calc_df["Drift_Pct"] = calc_df["Actual_Weight_Pct"] - calc_df["Norm_Target_Pct"]
    calc_df["Target_Value_NGN"] = total_portfolio * (calc_df["Norm_Target_Pct"] / 100.0)
    calc_df["Dollar_Drift_NGN"] = calc_df["Market_Value"] - calc_df["Target_Value_NGN"]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total NGX Portfolio", f"₦{total_portfolio:,.2f}", delta=f"₦{total_pnl:+,.2f} Unrealized")
    m2.metric("Equities Market Value", f"₦{equity_total:,.2f}")
    m3.metric("Cleared / External NGN Cash", f"₦{effective_cash:,.2f}")
    m4.metric("Rebalance Drift Band", f"±{drift_threshold_pct:.1f}%")

    st.markdown("---")
    st.subheader("2. Portfolio Weight Drift & Valuation Audit")

    c_left, c_right = st.columns([3, 2])
    with c_left:
        display_cols = calc_df[[
            "Ticker", "Units", "Live_Price", "Market_Value", "Return_Pct", "Actual_Weight_Pct", "Norm_Target_Pct", "Drift_Pct"
        ]].copy()
        display_cols.columns = [
            "Ticker", "Units", "Price (₦)", "Value (₦)", "Gain/Loss (%)", "Actual (%)", "Target (%)", "Drift (%)"
        ]
        st.dataframe(
            display_cols.style.format({
                "Units": "{:.2f}",
                "Price (₦)": "₦{:,.2f}",
                "Value (₦)": "₦{:,.2f}",
                "Gain/Loss (%)": "{:+.2f}%",
                "Actual (%)": "{:.2f}%",
                "Target (%)": "{:.2f}%",
                "Drift (%)": "{:+.2f}%",
            }),
            use_container_width=True,
        )
    with c_right:
        fig_alloc = px.pie(
            calc_df,
            names="Ticker",
            values="Market_Value",
            title="Current NGX Allocation",
            hole=0.42,
        )
        st.plotly_chart(fig_alloc, use_container_width=True)

    st.markdown("---")
    st.subheader("3. Tonight's 12:00 AM WAT Bamboo Pre-Market Order Ticket (Self-Funding)")

    fee_rate = 0.0155
    sell_tickets = []
    projected_cash = effective_cash

    overweight = calc_df[calc_df["Drift_Pct"] >= drift_threshold_pct].sort_values(by="Drift_Pct", ascending=False)
    for _, row in overweight.iterrows():
        excess_ngn = float(row["Dollar_Drift_NGN"])
        close_px = float(row["Live_Price"])
        limit_sell_px = round(close_px * (1.0 - sell_buffer_pct / 100.0), 2)
        shares_to_sell = min(int(math.floor(excess_ngn / close_px)), int(math.floor(float(row["Units"]))))
        gross_val = shares_to_sell * limit_sell_px
        if shares_to_sell >= 1 and gross_val >= min_order_floor:
            net_proceeds = gross_val * (1.0 - fee_rate)
            projected_cash += net_proceeds
            sell_tickets.append({
                "Phase": "1 - TRIM WINNER",
                "Ticker": row["Ticker"],
                "Action": "SELL",
                "Units": shares_to_sell,
                "Ref_Close_NGN": close_px,
                "Midnight_Limit_NGN": limit_sell_px,
                "Est_Order_Value_NGN": round(gross_val, 2),
                "Rationale": f"Overweight by {row['Drift_Pct']:+.2f}% (Gain: {row['Return_Pct']:+.2f}%)"
            })

    buy_tickets = []
    underweight = calc_df[calc_df["Drift_Pct"] <= -drift_threshold_pct].sort_values(by="Drift_Pct", ascending=True)
    total_deficit = float(abs(underweight["Dollar_Drift_NGN"]).sum()) if not underweight.empty else 0.0

    if projected_cash >= min_order_floor and total_deficit > 0:
        for _, row in underweight.iterrows():
            deficit_ngn = abs(float(row["Dollar_Drift_NGN"]))
            alloc_cash = projected_cash * (deficit_ngn / total_deficit)
            close_px = float(row["Live_Price"])
            limit_buy_px = round(close_px * (1.0 + buy_buffer_pct / 100.0), 2)
            effective_unit_cost = limit_buy_px * (1.0 + fee_rate)
            shares_to_buy = int(math.floor(alloc_cash / effective_unit_cost))
            est_val = shares_to_buy * limit_buy_px
            if shares_to_buy >= 1 and est_val >= min_order_floor:
                buy_tickets.append({
                    "Phase": "2 - ACCUMULATE DIP",
                    "Ticker": row["Ticker"],
                    "Action": "BUY",
                    "Units": shares_to_buy,
                    "Ref_Close_NGN": close_px,
                    "Midnight_Limit_NGN": limit_buy_px,
                    "Est_Order_Value_NGN": round(est_val, 2),
                    "Rationale": f"Underweight by {row['Drift_Pct']:+.2f}% (+{buy_buffer_pct:.2f}% fee/auction buffer)"
                })

    all_tickets = sell_tickets + buy_tickets
    if all_tickets:
        df_tickets = pd.DataFrame(all_tickets)
        st.success(
            f"Generated {len(sell_tickets)} Self-Funding SELL trim(s) and {len(buy_tickets)} BUY order(s) "
            f"(Projected Cash Pool: ₦{projected_cash:,.2f}). Place these Limit Orders on Bamboo around 12:00 AM WAT:"
        )
        st.dataframe(
            df_tickets.style.format({
                "Ref_Close_NGN": "₦{:,.2f}",
                "Midnight_Limit_NGN": "₦{:,.2f}",
                "Est_Order_Value_NGN": "₦{:,.2f}",
            }),
            use_container_width=True,
        )

        if st.button("📝 Record Tonight's Order Ticket to Audit Ledger (`ngx_trade_audit.csv`)"):
            now_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
            log_rows = pd.DataFrame([
                {
                    "Timestamp": now_utc,
                    "Ticker": t["Ticker"],
                    "Side": t["Action"],
                    "Units": t["Units"],
                    "Limit_Price_NGN": t["Midnight_Limit_NGN"],
                    "Total_Value_NGN": t["Est_Order_Value_NGN"],
                    "Status": "TICKET_READY_12AM_WAT",
                    "Rationale": t["Rationale"],
                }
                for t in all_tickets
            ])
            log_rows.to_csv(AUDIT_FILE, mode="a", header=not os.path.exists(AUDIT_FILE), index=False)
            st.success("Order ticket recorded to ngx_trade_audit.csv!")
    else:
        st.info("All 8 NGX holdings are currently balanced within your ±3.0% drift band. No overnight orders needed.")

with tab_ledger:
    st.subheader("📋 NGX Rebalance & Midnight Order Audit Ledger")
    if os.path.exists(AUDIT_FILE):
        df_log = pd.read_csv(AUDIT_FILE)
        st.dataframe(df_log.sort_index(ascending=False), use_container_width=True)
    else:
        st.info("No audit entries recorded yet.")
