"""
===============================================================================
NGX Quantitative Engine — Phase 6: Streamlit Web Dashboard & Control Center
File: app.py
===============================================================================
Description:
    Interactive executive intelligence dashboard for monitoring NGX equity 
    forecasting, GARCH volatility metrics, 1-Day 95% VaR risk caps, and automated
    rebalancing audit logs.

Features:
    - Real-time parameter controls (Portfolio Capital, VaR Confidence, SEC Fee Limits)
    - Interactive Plotly visualizations for volatility curves and portfolio weights
    - Isolated audit ledger table viewer for `ngx_trade_audit.csv`
    - Execution trigger button connecting Phases 1 through 5 seamlessly
===============================================================================
"""

import os
import json
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# Import Custom Engineering Modules (Phases 1 - 5)
from src.data_ingestion import run_phase_1_pipeline, DEFAULT_NGX_WATCHLIST
from src.feature_engineering import build_feature_matrix
from src.models.econometric_volatility import fit_gjr_garch, forecast_volatility_horizon
from src.models.deep_forecaster import train_lstm_forecaster, train_transformer_forecaster, generate_directional_signal_score
from src.risk_engine import apply_ngx_liquidity_and_friction_filter, optimize_ngx_portfolio_weights
from src.execution_engine import calculate_ngx_order_lots, dispatch_rebalance_orders


# =============================================================================
# Streamlit App Configuration & Styling
# =============================================================================
st.set_page_config(
    page_title="NGX Quant Risk Engine",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling for Financial Terminal Aesthetic
st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    .stMetric { background-color: #1e222d; padding: 15px; border-radius: 8px; border: 1px solid #2a2e39; }
    .stButton>button { width: 100%; background-color: #00c853; color: white; font-weight: bold; border-radius: 6px; }
    </style>
""", unsafe_allow_html=True)


# =============================================================================
# Sidebar: Terminal Controls & Parameters
# =============================================================================
st.sidebar.title("🕹️ NGX Control Panel")
st.sidebar.markdown("---")

# Execution Context
execution_mode = st.sidebar.radio(
    "Target Execution Mode",
    ["Paper Simulation", "Live Broker API"],
    index=0
)

st.sidebar.markdown("### 💰 Capital & Risk Controls")
portfolio_capital_ngn = st.sidebar.number_input(
    "Total Portfolio Capital (₦)",
    min_value=100000.0,
    max_value=1000000000.0,
    value=10000000.0,
    step=500000.0,
    format="%.2f"
)

var_confidence = st.sidebar.select_slider(
    "VaR Confidence Level (%)",
    options=[90.0, 95.0, 99.0],
    value=95.0
)

max_single_stock_cap = st.sidebar.slider(
    "Max Single Stock Cap (%)",
    min_value=10.0,
    max_value=50.0,
    value=30.0,
    step=5.0
) / 100.0

sec_fee_hurdle = st.sidebar.slider(
    "Min Required 30D Return (SEC Hurdle %)",
    min_value=1.0,
    max_value=10.0,
    value=3.0,
    step=0.5
) / 100.0

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔬 Model Parameters")
selected_symbols = st.sidebar.multiselect(
    "Select Target NGX Equities",
    options=DEFAULT_NGX_WATCHLIST,
    default=["DANGCEM.LG", "ZENITHBANK.LG", "CADBURY.LG", "GTCO.LG", "MTNN.LG"]
)

epochs_count = st.sidebar.slider("Deep Learning Training Epochs", min_value=5, max_value=50, value=10)


# =============================================================================
# Dashboard Main Header
# =============================================================================
st.title("📈 NGX Quantitative Stock Forecasting & Risk Engine")
st.caption("Institutional-grade GARCH Volatility, PyTorch Deep Learning, and 1-Day 95% VaR Execution Suite for the Nigerian Exchange")

st.markdown("---")


# =============================================================================
# Section 1: Executive KPI Summary Cards
# =============================================================================
col1, col2, col3, col4 = st.columns(4)

col1.metric("Portfolio Capital", f"₦{portfolio_capital_ngn:,.2f}")
col2.metric("Execution Mode", execution_mode, delta="Active" if execution_mode == "Live Broker API" else "Simulated")
col3.metric("Selected Universe", f"{len(selected_symbols)} Stocks")
col4.metric("Fee Hurdle Limit", f"{sec_fee_hurdle * 100:.1f}%")

st.markdown("---")


# =============================================================================
# Main Action: Run Quantitative Pipeline Button
# =============================================================================
if st.button("🚀 Execute Quantitative Pipeline & Risk Rebalance"):
    with st.spinner("Executing Phase 1 to Phase 5 Quantitative Pipeline..."):
        
        # Step 1: Data Ingestion
        st.subheader("1. Ingesting NGX Equities & CBN Macro Data")
        raw_data = run_phase_1_pipeline(symbols=selected_symbols)
        ohlcv_dict = raw_data["ohlcv_series"]
        macro_df = raw_data["macro_indicators"]
        
        st.success(f"Ingested {len(ohlcv_dict)} OHLCV series & CBN Macro Drivers successfully.")

        # Step 2 & 3: Feature Engineering, GARCH Volatility & Deep Learning Signals
        st.subheader("2. Predictive Model Signals & Volatility Forecasts")
        
        signals_map = {}
        market_data_for_risk = {}
        latest_prices = {}
        
        model_results_list = []

        for sym, df_ohlcv in ohlcv_dict.items():
            if df_ohlcv.empty:
                continue

            # Feature Matrix
            feat_df = build_feature_matrix(df_ohlcv, macro_df)
            market_data_for_risk[sym] = df_ohlcv
            latest_price = float(df_ohlcv["Close"].iloc[-1])
            latest_prices[sym] = latest_price

            # Econometric GJR-GARCH Fit
            garch_params, cond_vol = fit_gjr_garch(feat_df["Log_Return"])
            vol_forecast = forecast_volatility_horizon(feat_df["Log_Return"], horizon_days=20)
            garch_vol_1d = vol_forecast["1D_predicted_vol_pct"]

            # PyTorch Deep Learning Models
            _, lstm_pred = train_lstm_forecaster(feat_df["Log_Return"], epochs=epochs_count)
            _, trans_pred = train_transformer_forecaster(feat_df["Log_Return"], epochs=epochs_count)

            # Unified Signal Score [-1, +1]
            signal_res = generate_directional_signal_score(
                returns=feat_df["Log_Return"],
                garch_vol_pred=garch_vol_1d,
                lstm_return_pred=lstm_pred,
                transformer_return_pred=trans_pred
            )

            signals_map[sym] = signal_res

            model_results_list.append({
                "Symbol": sym.replace(".LG", ""),
                "Latest Price (₦)": f"₦{latest_price:,.2f}",
                "LSTM Return Pred": f"{lstm_pred * 100:.2f}%",
                "Transformer Pred": f"{trans_pred * 100:.2f}%",
                "1D GARCH Vol": f"{garch_vol_1d * 100:.2f}%",
                "Signal Score S_i": f"{signal_res['signal_score']:.3f}",
                "Action Signal": signal_res["recommended_action"]
            })

        st.dataframe(pd.DataFrame(model_results_list), use_container_width=True)

        # Step 4: Liquidity Screening & Risk Optimization
        st.subheader("3. Risk Management & Portfolio Optimization")
        
        eligible_tickers, rejections = apply_ngx_liquidity_and_friction_filter(
            market_data_for_risk, 
            signals_map
        )

        st.info(f"**Eligible Equities Cleared:** {eligible_tickers}")
        if rejections:
            st.warning(f"**Screening Rejections:** {rejections}")

        # Combine returns for optimization
        returns_comb = pd.DataFrame({
            sym: market_data_for_risk[sym]["Close"].pct_change()
            for sym in eligible_tickers
            if sym in market_data_for_risk
        }).dropna()

        opt_results = optimize_ngx_portfolio_weights(
            eligible_tickers=eligible_tickers,
            returns_df=returns_comb,
            signal_scores=signals_map,
            portfolio_value_ngn=portfolio_capital_ngn,
            max_single_stock_weight=max_single_stock_cap,
            max_portfolio_var_pct=0.025
        )

        # Render Allocation Breakdown Charts
        opt_col1, opt_col2 = st.columns(2)

        with opt_col1:
            st.markdown("#### Optimized Capital Allocation")
            weights_data = opt_results["stock_weights"].copy()
            weights_data["Liquid NGN Cash Buffer"] = opt_results["cash_weight"]

            fig_pie = px.pie(
                names=list(weights_data.keys()),
                values=list(weights_data.values()),
                title="Target Portfolio Weights",
                hole=0.4
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        with opt_col2:
            st.markdown("#### Risk Metrics")
            st.metric("1-Day 95% Parametric VaR (₦)", f"₦{opt_results['1D_95_VaR_NGN']:,.2f}")
            st.metric("Allocated Capital (₦)", f"₦{opt_results['allocated_capital_ngn']:,.2f}")
            st.metric("Liquid Cash Buffer (₦)", f"₦{opt_results['cash_buffer_ngn']:,.2f}")

        # Step 5: Execution & Order Dispatch
        st.subheader("4. Order Generation & Audit Dispatch")
        
        orders, req_cash = calculate_ngx_order_lots(
            target_weights=opt_results["stock_weights"],
            latest_prices=latest_prices,
            portfolio_value_ngn=portfolio_capital_ngn
        )

        if orders:
            st.markdown("##### Generated Trade Orders Payload")
            st.dataframe(pd.DataFrame(orders), use_container_width=True)

            dispatch_res = dispatch_rebalance_orders(
                orders=orders,
                cash_buffer_ngn=opt_results["cash_buffer_ngn"]
            )
            st.success(f"✅ Rebalance Dispatch Complete! Logged {dispatch_res['orders_count']} orders to audit ledger.")
        else:
            st.warning("⚠️ No trade orders generated. Capital preserved in NGN liquid buffer.")


# =============================================================================
# Section 2: Audit Ledger Inspection Tab
# =============================================================================
st.markdown("---")
st.subheader("📋 Execution Audit Ledger (`ngx_trade_audit.csv`)")

audit_filename = "ngx_trade_audit.csv"
if os.path.exists(audit_filename):
    df_audit = pd.read_csv(audit_filename)
    st.dataframe(df_audit.sort_index(ascending=False), use_container_width=True)
else:
    st.info("No execution audit records found yet. Click the button above to run your first rebalance cycle.")
