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
    - Computes SEC, CSCS, NSE, and broker fee breakdowns (~1.35% total buy cost)
    - Enforces minimum transaction order thresholds to prevent fee erosion
    - Generates dispatchable trade execution payloads and CSV rebalance logs
===============================================================================
"""

import os
import json
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional


# =============================================================================
# NGX Transaction Fee & Duty Schedule
# =============================================================================
BROKER_COMMISSION_PCT = 0.0100  # 1.00% Brokerage Commission
SEC_FEE_PCT = 0.0030           # 0.30% Securities & Exchange Commission Fee
NSE_STAMP_DUTY_PCT = 0.00075   # 0.075% Stamp Duty
CSCS_FEE_PCT = 0.00015         # 0.015% Central Securities Clearing System Fee

TOTAL_BUY_FEE_PCT = BROKER_COMMISSION_PCT + SEC_FEE_PCT + NSE_STAMP_DUTY_PCT + CSCS_FEE_PCT  # ~1.39%

MIN_ORDER_VALUE_NGN = 50_000.0  # ₦50,000 minimum trade size to prevent fee erosion


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
    
    Returns:
        orders (list): List of order specification dicts.
        total_cash_required (float): Total capital required including transaction fees.
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
            print(f"  ⚠️ Skipping {symbol}: Order value ₦{target_allocation_ngn:,.2f} < ₦50k minimum limit.")
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
            "symbol": symbol.replace(".LG", ""),
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
    Simulates or dispatches trade orders and appends timestamped records 
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

    mock_weights = {"DANGCEM.LG": 0.25, "ZENITHBANK.LG": 0.20}
    mock_prices = {"DANGCEM.LG": 280.0, "ZENITHBANK.LG": 35.0}
    portfolio_capital = 10_000_000.0  # ₦10 Million NGN

    orders, req_cash = calculate_ngx_order_lots(mock_weights, mock_prices, portfolio_capital)
    summary = dispatch_rebalance_orders(orders, cash_buffer_ngn=portfolio_capital - req_cash)

    print("\n--- Order Dispatch Payload ---")
    print(json.dumps(orders, indent=2))
    print("\n--- Execution Audit Summary ---")
    print(json.dumps(summary, indent=2))
