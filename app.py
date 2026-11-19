import os
import json
import math
from datetime import datetime, timezone, timedelta
import pandas as pd
import plotly.express as px
import streamlit as st
from ngx_live_prices import fetch_official_ngx_closes

st.set_page_config(page_title="NGX Quant Risk Engine", page_icon="📈", layout="wide")

STATE_FILE = "ngx_portfolio_state.json"
ORDER_AUDIT_FILE = "ngx_trade_audit.csv"
PORTFOLIO_AUDIT_FILE = "ngx_portfolio_audit.csv"
FEE_RATE = 0.0155

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


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                df = pd.DataFrame(data.get("holdings", DEFAULT_HOLDINGS))
                if not df.empty:
                    return df, float(data.get("free_cash_ngn", 0.0))
        except Exception:
            pass
    return pd.DataFrame(DEFAULT_HOLDINGS), 0.0


def save_state(df, cash):
    payload = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "free_cash_ngn": float(cash),
        "holdings": df.to_dict(orient="records"),
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def rolling_30d_turnover(curr):
    if not os.path.exists(PORTFOLIO_AUDIT_FILE):
        return curr
    try:
        h = pd.read_csv(PORTFOLIO_AUDIT_FILE)
        h["Timestamp_UTC"] = pd.to_datetime(h["Timestamp_UTC"], errors="coerce", utc=True)
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        recent = h[h["Timestamp_UTC"] >= cutoff]
        return float(recent["Cycle_Turnover_Pct"].sum()) + curr
    except Exception:
        return curr
def log_audit_records(tickets, m, eff_cash):
    utc_now = datetime.now(timezone.utc)
    wat_now = utc_now + timedelta(hours=1)
    order_rows = []
    for t in tickets:
        order_rows.append({
            "Timestamp": utc_now.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "Ticker": t["Ticker"],
            "Side": t["Action"],
            "Units": t["Units"],
            "Limit_Price_NGN": t["Limit_NGN"],
            "Total_Value_NGN": t["Value_NGN"],
            "Status": "DASHBOARD_LOGGED",
            "Rationale": t["Drift"],
        })
    pd.DataFrame(order_rows).to_csv(
        ORDER_AUDIT_FILE, mode="a", header=not os.path.exists(ORDER_AUDIT_FILE), index=False
    )
    tel_row = [{
        "Timestamp_UTC": utc_now.strftime("%Y-%m-%d %H:%M:%S"),
        "Timestamp_WAT": wat_now.strftime("%Y-%m-%d %H:%M:%S"),
        "Price_Feed_Status": "STREAMLIT_LOG",
        "Total_Portfolio_NGN": round(m["tot_port"], 2),
        "Equities_Value_NGN": round(m["eq_val"], 2),
        "Pre_Rebalance_Cash_NGN": round(eff_cash, 2),
        "Post_Rebalance_Cash_NGN": round(m["post_cash"], 2),
        "Max_Drift_Before_Pct": round(m["max_drift"], 2),
        "Mean_Abs_Drift_Before_Pct": round(m["mad_before"], 2),
        "Projected_Mean_Abs_Drift_After_Pct": round(m["mad_after"], 2),
        "Est_Brokerage_Fees_NGN": round(m["fees"], 2),
        "Fee_Drag_Pct": round(m["fee_pct"], 3),
        "Cycle_Turnover_Pct": round(m["turnover"], 2),
        "Rolling_30D_Turnover_Pct": round(m["turn_30d"], 2),
        "Orders_Generated": len(tickets),
    }]
    pd.DataFrame(tel_row).to_csv(
        PORTFOLIO_AUDIT_FILE, mode="a", header=not os.path.exists(PORTFOLIO_AUDIT_FILE), index=False
    )


def compute_rebalance(df_in, cash_in, drift_band, buy_buf, sell_buf, min_floor):
    df = df_in.copy()
    df["Cost_Value"] = df["Units"] * df["Avg_Cost"]
    df["Market_Value"] = df["Units"] * df["Live_Price"]
    df["Return_Pct"] = ((df["Live_Price"] - df["Avg_Cost"]) / df["Avg_Cost"].replace(0, 1)) * 100.0
    eq_val = float(df["Market_Value"].sum())
    tot_port = eq_val + cash_in
    w_sum = float(df["Target_Weight_Pct"].sum())
    df["Norm_Target_Pct"] = (df["Target_Weight_Pct"] / w_sum * 100.0) if w_sum > 0 else 0.0
    df["Actual_Weight_Pct"] = (df["Market_Value"] / tot_port * 100.0) if tot_port > 0 else 0.0
    df["Drift_Pct"] = df["Actual_Weight_Pct"] - df["Norm_Target_Pct"]
    df["Dollar_Drift_NGN"] = df["Market_Value"] - (tot_port * (df["Norm_Target_Pct"] / 100.0))

    sells, buys = [], []
    proj_cash = cash_in
    sell_gross, buy_gross, fees = 0.0, 0.0, 0.0
    proj_units = dict(zip(df["Ticker"], df["Units"]))

    ow = df[df["Drift_Pct"] >= drift_band].sort_values("Drift_Pct", ascending=False)
    for _, r in ow.iterrows():
        px = float(r["Live_Price"])
        lim = round(px * (1.0 - sell_buf / 100.0), 2)
        qty = min(int(math.floor(float(r["Dollar_Drift_NGN"]) / px)), int(math.floor(float(r["Units"]))))
        val = qty * lim
        if qty >= 1 and val >= min_floor:
            f = val * FEE_RATE
            proj_cash += (val - f)
            sell_gross += val
            fees += f
            proj_units[r["Ticker"]] = max(0.0, float(proj_units[r["Ticker"]]) - qty)
            sells.append({
                "Phase": "1-TRIM", "Ticker": r["Ticker"], "Action": "SELL",
                "Units": qty, "Close_NGN": px, "Limit_NGN": lim,
                "Value_NGN": round(val, 2), "Drift": f"{r['Drift_Pct']:+.2f}%",
            })

    post_cash = proj_cash
    uw = df[df["Drift_Pct"] <= -drift_band].sort_values("Drift_Pct", ascending=True)
    tot_def = float(abs(uw["Dollar_Drift_NGN"]).sum()) if not uw.empty else 0.0
    if proj_cash >= min_floor and tot_def > 0:
        for _, r in uw.iterrows():
            alloc = proj_cash * (abs(float(r["Dollar_Drift_NGN"])) / tot_def)
            px = float(r["Live_Price"])
            lim = round(px * (1.0 + buy_buf / 100.0), 2)
            qty = int(math.floor(alloc / (lim * (1.0 + FEE_RATE))))
            val = qty * lim
            if qty >= 1 and val >= min_floor:
                f = val * FEE_RATE
                buy_gross += val
                fees += f
                post_cash = max(0.0, post_cash - (val + f))
                proj_units[r["Ticker"]] = float(proj_units[r["Ticker"]]) + qty
                buys.append({
                    "Phase": "2-BUY", "Ticker": r["Ticker"], "Action": "BUY",
                    "Units": qty, "Close_NGN": px, "Limit_NGN": lim,
                    "Value_NGN": round(val, 2), "Drift": f"{r['Drift_Pct']:+.2f}%",
                })

    df["Post_Market_Value"] = df["Ticker"].map(proj_units) * df["Live_Price"]
    post_tot = float(df["Post_Market_Value"].sum()) + post_cash
    post_wt = (df["Post_Market_Value"] / post_tot * 100.0) if post_tot > 0 else 0.0
    df["Post_Drift_Pct"] = post_wt - df["Norm_Target_Pct"]
    turnover = ((sell_gross + buy_gross) / (2.0 * tot_port) * 100.0) if tot_port > 0 else 0.0
    metrics = {
        "tot_port": tot_port,
        "eq_val": eq_val,
        "pnl": eq_val - float(df["Cost_Value"].sum()),
        "proj_cash": proj_cash,
        "post_cash": post_cash,
        "max_drift": float(df["Drift_Pct"].abs().max()),
        "mad_before": float(df["Drift_Pct"].abs().mean()),
        "mad_after": float(df["Post_Drift_Pct"].abs().mean()),
        "fees": fees,
        "fee_pct": (fees / tot_port * 100.0) if tot_port > 0 else 0.0,
        "turnover": turnover,
        "turn_30d": rolling_30d_turnover(turnover),
    }
    return df, sells + buys, metrics
st.sidebar.title("🕹️ NGX Execution Controls")
cash_in = st.sidebar.number_input("Cleared Bamboo NGN Cash (₦)", 0.0, 500000000.0, 0.0, 500.0, format="%.2f")
drift_band = st.sidebar.slider("Rebalance Drift Band (%)", 1.5, 10.0, 3.0, 0.5)
buy_buf = st.sidebar.slider("12:00 AM Buy Buffer (%)", 0.50, 3.00, 1.25, 0.25)
sell_buf = st.sidebar.slider("12:00 AM Sell Buffer (%)", 0.00, 2.50, 1.00, 0.25)
min_floor = st.sidebar.number_input("Min Bamboo Order (₦)", 500.0, 25000.0, 1500.0, 250.0)

st.title("📈 NGX Self-Funding Portfolio & Midnight Bamboo Order Engine")
tab1, tab2, tab3 = st.tabs(["⚖️ Rebalancer & Order Ticket", "📊 5-Metric Portfolio Telemetry", "📋 Trade Audit Ledger"])

with tab1:
    df_saved, saved_cash = load_state()
    eff_cash = cash_in if cash_in > 0 else saved_cash
    if st.button("🔄 Sync Official NSENG Closing Prices"):
        live_map, msg = fetch_official_ngx_closes(df_saved["Ticker"].tolist())
        if live_map:
            df_saved["Live_Price"] = df_saved.apply(lambda r: live_map.get(str(r["Ticker"]).upper(), r["Live_Price"]), axis=1)
            save_state(df_saved, eff_cash)
            st.success(msg)
        if not live_map:
            st.warning(msg)

    edited_df = st.data_editor(df_saved, use_container_width=True, num_rows="dynamic", key="ngx_ed")
    if st.button("💾 Save Updated Holdings & Cash"):
        save_state(edited_df, eff_cash)
        st.success("Saved updated holdings and cash.")

    calc_df, tickets, m = compute_rebalance(edited_df, eff_cash, drift_band, buy_buf, sell_buf, min_floor)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total NGX Portfolio", f"₦{m['tot_port']:,.2f}", delta=f"₦{m['pnl']:+,.2f}")
    c2.metric("Post-Rebalance Cash", f"₦{m['post_cash']:,.2f}", delta=f"Pre: ₦{eff_cash:,.2f}")
    c3.metric("Mean Drift (Before → After)", f"{m['mad_before']:.2f}% → {m['mad_after']:.2f}%", delta=f"Max: {m['max_drift']:.2f}%")
    c4.metric("Est. Fees & Turnover", f"₦{m['fees']:,.2f} ({m['fee_pct']:.2f}%)", delta=f"Turn: {m['turnover']:.2f}%")

    col_a, col_b = st.columns(2)
    with col_a:
        cols_show = ["Ticker", "Units", "Live_Price", "Market_Value", "Actual_Weight_Pct", "Norm_Target_Pct", "Drift_Pct"]
        st.dataframe(calc_df[cols_show], use_container_width=True)
    with col_b:
        fig_pie = px.pie(calc_df, names="Ticker", values="Market_Value", title="Current NGX Allocation", hole=0.4)
        st.plotly_chart(fig_pie, use_container_width=True)

    st.subheader("Tonight's 12:00 AM WAT Bamboo Order Ticket")
    if tickets:
        st.dataframe(pd.DataFrame(tickets), use_container_width=True)
        if st.button("📝 Record Order Ticket & Portfolio Telemetry"):
            log_audit_records(tickets, m, eff_cash)
            st.success("Recorded to audit ledgers!")
    if not tickets:
        st.info("Portfolio balanced within drift band.")

with tab2:
    if os.path.exists(PORTFOLIO_AUDIT_FILE):
        st.dataframe(pd.read_csv(PORTFOLIO_AUDIT_FILE).sort_index(ascending=False), use_container_width=True)
    if not os.path.exists(PORTFOLIO_AUDIT_FILE):
        st.info("No telemetry logged yet.")

with tab3:
    if os.path.exists(ORDER_AUDIT_FILE):
        st.dataframe(pd.read_csv(ORDER_AUDIT_FILE).sort_index(ascending=False), use_container_width=True)
    if not os.path.exists(ORDER_AUDIT_FILE):
        st.info("No orders logged yet.")
