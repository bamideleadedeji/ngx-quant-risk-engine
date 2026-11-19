import os
import json
import math
from datetime import datetime, timezone, timedelta
import pandas as pd
import plotly.express as px
import streamlit as st
from ngx_live_prices import fetch_official_ngx_closes

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
ORDER_AUDIT_FILE = "ngx_trade_audit.csv"
PORTFOLIO_AUDIT_FILE = "ngx_portfolio_audit.csv"

DEFAULT_HOLDINGS = [
    {"Ticker": "BUAFOODS", "Company": "BUA Foods Plc", "Units": 50.0, "Avg_Cost": 700.00, "Live_Price": 760.60, "Target_Weight_Pct": 16.0},
    {"Ticker": "SEPLAT", "Company": "Seplat Energy Plc", "Units": 2.0, "Avg_Cost": 16000.10, "Live_Price": 16241.90, "Target_Weight_Pct": 16.0},
    {"Ticker": "GTCO", "Company": "Guaranty Trust Holding Co.", "Units": 200.0, "Avg_Cost": 120.90, "Live_Price": 117.00, "Target_Weight_Pct": 16.0},
    {"Ticker": "MTNN", "Company": "MTN Nigeria Comm. Plc", "Units": 15.0, "Avg_Cost": 825.00, "Live_Price": 837.00, "Target_Weight_Pct": 12.0},
    {"Ticker": "ZENITHBANK", "Company": "Zenith Bank Plc", "Units": 100.0, "Avg_Cost": 116.60, "Live_Price": 114.00, "Target_Weight_Pct": 12.0},
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
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "free_cash_ngn": float(free_cash_ngn),
                "holdings": df.to_dict(orient="records"),
            }, f, indent=2)
    except Exception:
        pass


def compute_rolling_30d_turnover(current_turnover_pct: float) -> float:
    if not os.path.exists(PORTFOLIO_AUDIT_FILE):
        return current_turnover_pct
    try:
        hist = pd.read_csv(PORTFOLIO_AUDIT_FILE)
        if "Timestamp_UTC" in hist.columns and "Cycle_Turnover_Pct" in hist.columns:
            hist["Timestamp_UTC"] = pd.to_datetime(hist["Timestamp_UTC"], errors="coerce", utc=True)
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            recent = hist[hist["Timestamp_UTC"] >= cutoff]
            return float(recent["Cycle_Turnover_Pct"].sum()) + current_turnover_pct
    except Exception:
        pass
    return current_turnover_pct


st.sidebar.title("🕹️ NGX Execution Controls")
st.sidebar.markdown("---")
st.sidebar.info("🚀 **Mode:** Live NSENG Closing Sync + Self-Funding Rebalancer")

free_cash_ngn = st.sidebar.number_input(
    "Cleared Bamboo NGN Cash / New Deposit (₦)",
    min_value=0.0,
    max_value=500000000.0,
    value=0.0,
    step=500.0,
    format="%.2f",
)

drift_threshold_pct = st.sidebar.slider("Rebalance Drift Trigger Band (%)", 1.5, 10.0, 3.0, 0.5)
buy_buffer_pct = st.sidebar.slider("12:00 AM Pre-Market Buy Limit Buffer (%)", 0.50, 3.00, 1.25, 0.25)
sell_buffer_pct = st.sidebar.slider("12:00 AM Pre-Market Sell Limit Buffer (%)", 0.00, 2.50, 1.00, 0.25)
min_order_floor = st.sidebar.number_input("Minimum Bamboo Order Value (₦)", 500.0, 25000.0, 1500.0, 250.0)

st.title("📈 NGX Self-Funding Portfolio & Midnight Bamboo Order Engine")
st.caption("Live NSENG Closing Feed | Internal Winner-Trimming & +1.25% Pre-Market Limit Execution | Institutional Fee & Turnover Telemetry")
st.markdown("---")

tab_rebalance, tab_telemetry, tab_ledger = st.tabs([
    "⚖️ Self-Funding Rebalancer & 12:00 AM Order Ticket",
    "📊 Portfolio Efficiency & 5-Metric Telemetry",
    "📋 Order Execution Audit Ledger (ngx_trade_audit.csv)",
])

with tab_rebalance:
    df_saved, saved_cash = load_portfolio_state()
    effective_cash = free_cash_ngn if free_cash_ngn > 0 else saved_cash

    if st.button("🔄 Sync Official NSENG Closing Prices (Live Feed)"):
        live_map, feed_status = fetch_official_ngx_closes(df_saved["Ticker"].tolist())
        if live_map:
            df_saved["Live_Price"] = df_saved.apply(
                lambda r: live_map.get(str(r["Ticker"]).strip().upper(), r["Live_Price"]), axis=1
            )
            save_portfolio_state(df_saved, effective_cash)
            st.success(f"✅ {feed_status}")
        else:
            st.warning(f"⚠️ {feed_status}")

    st.subheader("1. Live Bamboo / CSCS Holdings (Update Units After T+2 Settlement)")
    edited_df = st.data_editor(
        df_saved,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "Units": st.column_config.NumberColumn("Units Held", min_value=0.0, format="%.2f"),
            "Avg_Cost": st.column_config.NumberColumn("Avg Cost (₦)", min_value=0.0, format="%.2f"),
            "Live_Price": st.column_config.NumberColumn("Close Price (₦)", min_value=0.01, format="%.2f"),
            "Target_Weight_Pct": st.column_config.NumberColumn("Target Weight (%)", min_value=0.0, max_value=100.0, format="%.1f"),
        },
        key="ngx_holdings_editor",
    )

    if st.button("💾 Save Updated Holdings & Cash"):
        save_portfolio_state(edited_df, effective_cash)
        st.success("Saved updated holdings and cleared Naira cash balance.")

    calc_df = edited_df.copy()
    calc_df["Cost_Value"] = calc_df["Units"] * calc_df["Avg_Cost"]
    calc_df["Market_Value"] = calc_df["Units"] * calc_df["Live_Price"]
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

    max_drift_before = float(calc_df["Drift_Pct"].abs().max()) if not calc_df.empty else 0.0
    mad_drift_before = float(calc_df["Drift_Pct"].abs().mean()) if not calc_df.empty else 0.0

    fee_rate = 0.0155
    sell_tickets = []
    projected_cash = effective_cash
    total_sell_gross = 0.0
    total_est_fees = 0.0
    projected_units = dict(zip(calc_df["Ticker"], calc_df["Units"]))

    overweight = calc_df[calc_df["Drift_Pct"] >= drift_threshold_pct].sort_values(by="Drift_Pct", ascending=False)
    for _, row in overweight.iterrows():
        excess_ngn = float(row["Dollar_Drift_NGN"])
        close_px = float(row["Live_Price"])
        limit_sell_px = round(close_px * (1.0 - sell_buffer_pct / 100.0), 2)
        shares_to_sell = min(int(math.floor(excess_ngn / close_px)), int(math.floor(float(row["Units"]))))
        gross_val = shares_to_sell * limit_sell_px
        if shares_to_sell >= 1 and gross_val >= min_order_floor:
            fee_amt = gross_val * fee_rate
            projected_cash += (gross_val - fee_amt)
            total_sell_gross += gross_val
            total_est_fees += fee_amt
            projected_units[row["Ticker"]] = max(0.0, float(projected_units[row["Ticker"]]) - shares_to_sell)
            sell_tickets.append({
                "Phase": "1 - TRIM WINNER",
                "Ticker": row["Ticker"],
                "Action": "SELL",
                "Units": shares_to_sell,
                "Ref_Close_NGN": close_px,
                "Midnight_Limit_NGN": limit_sell_px,
                "Est_Order_Value_NGN": round(gross_val, 2),
                "Drift": f"{row['Drift_Pct']:+.2f}%",
            })

    buy_tickets = []
    total_buy_gross = 0.0
    post_rebalance_cash = projected_cash
    underweight = calc_df[calc_df["Drift_Pct"] <= -drift_threshold_pct].sort_values(by="Drift_Pct", ascending=True)
    total_deficit = float(abs(underweight["Dollar_Drift_NGN"]).sum()) if not underweight.empty else 0.0

    if projected_cash >= min_order_floor and total_deficit > 0:
        for _, row in underweight.iterrows():
            deficit_ngn = abs(float(row["Dollar_Drift_NGN"]))
            alloc_cash = projected_cash * (deficit_ngn / total_deficit)
            close_px = float(row["Live_Price"])
            limit_buy_px = round(close_px * (1.0 + buy_buffer_pct / 100.0), 2)
            shares_to_buy = int(math.floor(alloc_cash / (limit_buy_px * (1.0 + fee_rate))))
            est_val = shares_to_buy * limit_buy_px
            if shares_to_buy >= 1 and est_val >= min_order_floor:
                fee_amt = est_val * fee_rate
                total_buy_gross += est_val
                total_est_fees += fee_amt
                post_rebalance_cash = max(0.0, post_rebalance_cash - (est_val + fee_amt))
                projected_units[row["Ticker"]] = float(projected_units[row["Ticker"]]) + shares_to_buy
                buy_tickets.append({
                    "Phase": "2 - ACCUMULATE DIP",
                    "Ticker": row["Ticker"],
                    "Action": "BUY",
                    "Units": shares_to_buy,
                    "Ref_Close_NGN": close_px,
                    "Midnight_Limit_NGN": limit_buy_px,
                    "Est_Order_Value_NGN": round(est_val, 2),
                    "Drift": f"{row['Drift_Pct']:+.2f}%",
                })

    calc_df["Post_Units"] = calc_df["Ticker"].map(projected_units)
    calc_df["Post_Market_Value"] = calc_df["Post_Units"] * calc_df["Live_Price"]
    post_total_portfolio = float(calc_df["Post_Market_Value"].sum()) + post_rebalance_cash
    calc_df["Post_Weight_Pct"] = (calc_df["Post_Market_Value"] / post_total_portfolio * 100.0) if post_total_portfolio > 0 else 0.0
    calc_df["Post_Drift_Pct"] = calc_df["Post_Weight_Pct"] - calc_df["Norm_Target_Pct"]
    mad_drift_after = float(calc_df["Post_Drift_Pct"].abs().mean()) if not calc_df.empty else 0.0

    turnover_pct = ((total_sell_gross + total_buy_gross) / (2.0 * total_portfolio) * 100.0) if total_portfolio > 0 else 0.0
    rolling_30d_turnover = compute_rolling_30d_turnover(turnover_pct)
    fee_drag_pct = (total_est_fees / total_portfolio * 100.0) if total_portfolio > 0 else 0.0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total NGX Portfolio", f"₦{total_portfolio:,.2f}", delta=f"₦{total_pnl:+,.2f} Unrealized")
    m2.metric("Post-Rebalance Cash", f"₦{post_rebalance_cash:,.2f}", delta=f"Pre: ₦{effective_cash:,.2f}")
    m3.metric("Mean Abs Drift (Before → After)", f"{mad_drift_before:.2f}% → {mad_drift_after:.2f}%", delta=f"Max: {max_drift_before:.2f}%")
    m4.metric("Est. Brokerage Fees & Turnover", f"₦{total_est_fees:,.2f} ({fee_drag_pct:.2f}%)", delta=f"Turnover: {turnover_pct:.2f}%")

    st.markdown("---")
    st.subheader("2. Portfolio Weight Drift & Valuation Audit")

    c_left, c_right = st.columns([3, 2])
    with c_left:
        display_cols = calc_df[[
            "Ticker", "Units", "Live_Price", "Market_Value", "Return_Pct", "Actual_Weight_Pct", "Norm_Target_Pct", "Drift_Pct"
        ]].copy()
        display_cols.columns = [
            "Ticker", "Units", "Close (₦)", "Value (₦)", "Gain/Loss (%)", "Actual (%)", "Target (%)", "Drift (%)"
        ]
        st.dataframe(
            display_cols.style.format({
                "Units": "{:.2f}",
                "Close (₦)": "₦{:,.2f}",
                "Value (₦)": "₦{:,.2f}",
                "Gain/Loss (%)": "{:+.2f}%",
                "Actual (%)": "{:.2f}%",
                "Target (%)": "{:.2f}%",
                "Drift (%)": "{:+.2f}%",
            }),
            use_container_width=True,
        )
    with c_right:
        fig_alloc = px.pie(calc_df, names="Ticker", values="Market_Value", title="Current NGX Allocation", hole=0.42)
        st.plotly_chart(fig_alloc, use_container_width=True)

    st.markdown("---")
    st.subheader("3. Tonight's 12:00 AM WAT Bamboo Pre-Market Order Ticket (Self-Funding)")

    all_tickets = sell_tickets + buy_tickets
    if all_tickets:
        df_tickets = pd.DataFrame(all_tickets)
        st.success(
            f"Generated {len(sell_tickets)} Self-Funding SELL trim(s) and {len(buy_tickets)} BUY order(s) "
            f"(Projected Cash Pool: ₦{projected_cash:,.2f} | Post-Rebalance Residual Cash: ₦{post_rebalance_cash:,.2f})."
        )
        st.dataframe(
            df_tickets.style.format({
                "Ref_Close_NGN": "₦{:,.2f}",
                "Midnight_Limit_NGN": "₦{:,.2f}",
                "Est_Order_Value_NGN": "₦{:,.2f}",
            }),
            use_container_width=True,
        )

        if st.button("📝 Record Tonight's Order Ticket & Portfolio Telemetry"):
            utc_now = datetime.now(timezone.utc)
            wat_now = utc_now + timedelta(hours=1)
            pd.DataFrame([
                {
                    "Timestamp": utc_now.strftime("%Y-%m-%d %H:%M:%S UTC"),

"Ticker": t["Ticker"],
"Side": t["Action"],
"Units": t["Units"],
"Limit_Price_NGN": t["Midnight_Limit_NGN"],
"Total_Value_NGN": t["Est_Order_Value_NGN"],
"Status": "DASHBOARD_TICKET_LOGGED",
"Rationale": f"Close ₦{t['Ref_Close_NGN']:,.2f} | Drift {t['Drift']}",
}
for t in all_tickets
]).to_csv(ORDER_AUDIT_FILE, mode="a", header=not os.path.exists(ORDER_AUDIT_FILE), index=False)
pd.DataFrame([{
"Timestamp_UTC": utc_now.strftime("%Y-%m-%d %H:%M:%S"),
"Timestamp_WAT": wat_now.strftime("%Y-%m-%d %H:%M:%S"),
"Price_Feed_Status": "STREAMLIT_DASHBOARD_LOG",
"Total_Portfolio_NGN": round(total_portfolio, 2),
"Equities_Value_NGN": round(equity_total, 2),
"Pre_Rebalance_Cash_NGN": round(effective_cash, 2),
"Post_Rebalance_Cash_NGN": round(post_rebalance_cash, 2),
"Max_Drift_Before_Pct": round(max_drift_before, 2),
"Mean_Abs_Drift_Before_Pct": round(mad_drift_before, 2),
"Projected_Mean_Abs_Drift_After_Pct": round(mad_drift_after, 2),
"Est_Brokerage_Fees_NGN": round(total_est_fees, 2),
"Fee_Drag_Pct": round(fee_drag_pct, 3),
"Cycle_Turnover_Pct": round(turnover_pct, 2),
"Rolling_30D_Turnover_Pct": round(rolling_30d_turnover, 2),
"Orders_Generated": len(all_tickets),
}]).to_csv(PORTFOLIO_AUDIT_FILE, mode="a", header=not os.path.exists(PORTFOLIO_AUDIT_FILE), index=False)
st.success("Logged order ticket and 5-metric portfolio telemetry!")
else:
st.info("All 8 NGX holdings are currently balanced within your ±3.0% drift band. No overnight orders needed.")
with tab_telemetry:
st.subheader("📊 Historical Portfolio Value, Drift, Fee Drag & Turnover (ngx_portfolio_audit.csv)")
if os.path.exists(PORTFOLIO_AUDIT_FILE):
df_tel = pd.read_csv(PORTFOLIO_AUDIT_FILE)
st.dataframe(df_tel.sort_index(ascending=False), use_container_width=True)
if len(df_tel) >= 2 and "Timestamp_WAT" in df_tel.columns and "Total_Portfolio_NGN" in df_tel.columns:
fig_val = px.line(df_tel, x="Timestamp_WAT", y="Total_Portfolio_NGN", title="NGX Portfolio Value Over Time (₦)", markers=True)
st.plotly_chart(fig_val, use_container_width=True)
else:
st.info("No historical portfolio telemetry logged yet.")
with tab_ledger:
st.subheader("📋 NGX Rebalance & Midnight Order Audit Ledger (ngx_trade_audit.csv)")
if os.path.exists(ORDER_AUDIT_FILE):
df_log = pd.read_csv(ORDER_AUDIT_FILE)
st.dataframe(df_log.sort_index(ascending=False), use_container_width=True)
else:
st.info("No audit entries recorded yet.")
