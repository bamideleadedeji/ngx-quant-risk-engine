"""
===============================================================================
NGX Quantitative Engine — Phase 5: Automated Rebalancing & Execution Engine
File: src/execution_engine.py
===============================================================================
Description:
    Translates optimized portfolio target weights from Phase 4 into exact integer 
    share lots for listed equities on the Nigerian Exchange (NGX).

Features:
    - Calculates exact round-lot integer units based on live market ask prices
    - Computes SEC, CSCS, NSE, and broker fee breakdowns (~1.39% total buy cost)
    - Enforces micro-capital friendly order thresholds (₦1,000 min limit)
    - Dispatches instant 1-click execution notifications via Telegram (@ngx_quant_risk_bot)
    - Appends timestamped audit logs to persistent CSV ledger (`ngx_trade_audit.csv`)
===============================================================================
"""

import os
import json
import requests
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional


# =============================================================================
# NGX Transaction Fee & Duty Schedule
# =============================================================================
BROKER_COMMISSION_PCT = 0.0100  # 1.00% Brokerage Commission
SEC_FEE_PCT = 0.0030            # 0.30% Securities & Exchange Commission Fee
NSE_STAMP_DUTY_PCT = 0.00075    # 0.075% Stamp Duty
CSCS_FEE_PCT = 0.00015          # 0.015% Central Securities Clearing System Fee

TOTAL_BUY_FEE_PCT = BROKER_COMMISSION_PCT + SEC_FEE_PCT + NSE_STAMP_DUTY_PCT + CSCS_FEE_PCT  # ~1.39%

MIN_ORDER_VALUE_NGN = 1_000.0  # ₦1,000 minimum trade size for micro-capital trading


# =============================================================================
# Telegram Signal Dispatcher
# =============================================================================
def send_telegram_trade_signal(order: Dict[str, Any], cash_buffer_ngn: float) -> bool:
    """
    Dispatches live execution signals directly to your phone via Telegram bot.
    Reads credentials from Streamlit Secrets or Environment variables.
    """
    bot_token = None
    chat_id = None

    # 1. Try fetching from Streamlit secrets (Streamlit Cloud runtime)
    try:
        import streamlit as st
        bot_token = st.secrets.get("TELEGRAM_BOT_TOKEN")
        chat_id = st.secrets.get("TELEGRAM_CHAT_ID")
    except Exception:
        pass

    # 2. Fallback to os.environ (GitHub Actions / Local terminal)
    if not bot_token:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not chat_id:
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("⚠️ Telegram credentials missing in Streamlit secrets / os.environ.")
        return False

    message = (
        "🚀 *NGX QUANT ENGINE — LIVE TRADE SIGNAL*\n\n"
        f"📌 *Action:* `{order.get('action', 'BUY')}`\n"
        f"📈 *Ticker:* `{order.get('symbol')}`\n"
        f"🔢 *Units to Buy:* `{order.get('units', 0):,} shares`\n"
        f"💵 *Target Price:* `₦{order.get('unit_price_ngn', 0.0):,.2f}`\n"
        f"💰 *Gross Value:* `₦{order.get('gross_value_ngn', 0.0):,.2f}`\n"
        f"🧾 *Est. Fees (1.39%):* `₦{order.get('total_fee_ngn', 0.0):,.2f}`\n"
        f"💼 *Wallet Cash Remaining:* `₦{cash_buffer_ngn:,.2f}`\n\n"
        "📲 *Execution Steps:*\n"
        f"1. Open **Bamboo** app on your phone.\n"
        f"2. Search **{order.get('symbol')}**.\n"
        f"3. Tap **Buy** $\\rightarrow$ Enter **{order.get('units', 0)} shares** (₦{order.get('gross_value_ngn', 0.0):,.2f})."
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": str(chat_id),
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        print(f"❌ Failed to dispatch Telegram trade alert: {str(e)}")
        return False


# =============================================================================
# 5.1 Share Lot Calculation & Fee Deduction
# =============================================================================
def calculate_ngx_order_lots(
    target_weights: Dict[str, float],
    latest_prices: Dict[str, float],
    portfolio_value_ngn: float
) -> Tuple[List[Dict[str, Any]], float]:
    """
    Converts target percentage weights into exact discrete integer share units 
    and calculates fee breakdowns for NGX execution.
    """
    orders = []
    total_cash_required = 0.0

    for symbol, weight in target_weights.items():
        if weight <= 0.0 or symbol not in latest_prices:
            continue

        price = latest_prices[symbol]
        if price <= 0.0:
            continue

        target_allocation_ngn = portfolio_value_ngn * weight

        # Enforce Minimum Order Threshold
        if target_allocation_ngn < MIN_ORDER_VALUE_NGN:
            print(f"  ⚠️ Skipping {symbol}: Order value ₦{target_allocation_ngn:,.2f} < ₦1k minimum limit.")
            continue

        # Compute max integer units possible accounting for fee buffer
        gross_units = int(target_allocation_ngn // (price * (1.0 + TOTAL_BUY_FEE_PCT)))
        
        if gross_units <= 0:
            continue

        gross_value = gross_units * price
        
        # Fee Breakdown
        broker_fee = gross_value * BROKER_COMMISSION_PCT
        sec_fee = gross_value * SEC_FEE_PCT
        stamp_duty = gross_value * NSE_STAMP_DUTY_PCT
        cscs_fee = gross_value * CSCS_FEE_PCT
        total_fees = broker_fee + sec_fee + stamp_duty + cscs_fee

        net_cost = gross_value + total_fees
        total_cash_required += net_cost

        orders.append({
            "symbol": symbol.replace(".LG", "").replace(".NS", ""),
            "action": "BUY",
            "units": gross_units,
            "unit_price_ngn": price,
            "gross_value_ngn": round(gross_value, 2),
            "broker_fee_ngn": round(broker_fee, 2),
            "sec_fee_ngn": round(sec_fee, 2),
            "stamp_duty_ngn": round(stamp_duty, 2),
            "cscs_fee_ngn": round(cscs_fee, 2),
            "total_fee_ngn": round(total_fees, 2),
            "total_net_cost_ngn": round(net_cost, 2),
            "target_weight_pct": round(weight * 100, 2)
        })

    return orders, total_cash_required


# =============================================================================
# 5.2 Dispatcher & Audit Logging Engine
# =============================================================================
def dispatch_rebalance_orders(
    orders: List[Dict[str, Any]],
    cash_buffer_ngn: float,
    log_filepath: str = "ngx_trade_audit.csv"
) -> Dict[str, Any]:
    """
    Dispatches trade orders to Telegram and appends timestamped records 
    to persistent audit ledger.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    dispatched_records = []

    for order in orders:
        record = {
            "Timestamp": timestamp,
            "Symbol": order["symbol"],
            "Action": order["action"],
            "Units": order["units"],
            "UnitPrice_NGN": order["unit_price_ngn"],
            "GrossValue_NGN": order["gross_value_ngn"],
            "Fees_NGN": order["total_fee_ngn"],
            "NetCost_NGN": order["total_net_cost_ngn"],
            "TargetWeight_Pct": order["target_weight_pct"],
            "Status": "DISPATCHED_PENDING_FILL"
        }
        dispatched_records.append(record)

        # Dispatch live alert directly to Telegram phone app
        send_telegram_trade_signal(order, cash_buffer_ngn)

    # Append to CSV Ledger
    if dispatched_records:
        df_new = pd.DataFrame(dispatched_records)
        if os.path.exists(log_filepath):
            df_existing = pd.read_csv(log_filepath)
            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
            df_combined.to_csv(log_filepath, index=False)
        else:
            df_new.to_csv(log_filepath, index=False)

    total_gross = sum(o["gross_value_ngn"] for o in orders)
    total_fees = sum(o["total_fee_ngn"] for o in orders)

    return {
        "timestamp": timestamp,
        "orders_count": len(orders),
        "total_gross_allocated_ngn": round(total_gross, 2),
        "total_transaction_fees_ngn": round(total_fees, 2),
        "remaining_cash_buffer_ngn": round(cash_buffer_ngn, 2),
        "status": "COMPLETED" if orders else "NO_ORDERS_GENERATED"
    }


if __name__ == "__main__":
    print("🚀 Testing Phase 5 Automated Rebalancing & Execution Engine...")

    mock_weights = {"ZENITHBANK.LG": 0.50, "GTCO.LG": 0.50}
    mock_prices = {"ZENITHBANK.LG": 61.63, "GTCO.LG": 47.71}
    portfolio_capital = 14_850.0  # ₦14,850 Bamboo balance

    orders, req_cash = calculate_ngx_order_lots(mock_weights, mock_prices, portfolio_capital)
    summary = dispatch_rebalance_orders(orders, cash_buffer_ngn=portfolio_capital - req_cash)

    print("\n--- Order Dispatch Payload ---")
    print(json.dumps(orders, indent=2))
    print("\n--- Execution Audit Summary ---")
    print(json.dumps(summary, indent=2))
