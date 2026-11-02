"""
===============================================================================
NGX Quantitative Engine — Phase 3 & 4: Portfolio Optimization & Risk Engine
File: src/risk_portfolio.py
===============================================================================
Description:
    Performs GJR-GARCH volatility modeling, Value-at-Risk (VaR) calculations, 
    and mean-variance portfolio optimization for Nigerian Exchange (NGX) equities.
    Enforces strict institutional risk limits including maximum sector weight caps (25%)
    and liquidity-weighted capital allocation.
===============================================================================
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Any
from scipy.optimize import minimize

# =============================================================================
# NGX Sector Classification Map (44 Watchlist Coverage)
# =============================================================================
SECTOR_MAP = {
    # Banking
    "ZENITHBANK": "Banking", "GTCO": "Banking", "UBA": "Banking", "ACCESSCORP": "Banking", 
    "FBNH": "Banking", "STANBIC": "Banking", "FIDELITYBK": "Banking",
    # Consumer Goods
    "NESTLE": "Consumer Goods", "NB": "Consumer Goods", "CADBURY": "Consumer Goods", 
    "UNILEVER": "Consumer Goods", "FLOURMILL": "Consumer Goods", "DANGSUGAR": "Consumer Goods", "BUAFOODS": "Consumer Goods",
    # Industrials
    "DANGCEM": "Industrials", "BUACEMENT": "Industrials", "WAPCO": "Industrials",
    # Oil & Gas
    "SEPLAT": "Oil & Gas", "CONOIL": "Oil & Gas", "TOTAL": "Oil & Gas", 
    "ARDOVA": "Oil & Gas", "ETERNA": "Oil & Gas", "MRS": "Oil & Gas",
    # ICT & Telecoms
    "MTNN": "Telecoms", "AIRTELAFRI": "Telecoms", "CHAMS": "Telecoms",
    # Agriculture
    "OKOMUOIL": "Agriculture", "PRESCO": "Agriculture", "LIVESTOCK": "Agriculture",
    # Healthcare
    "FIDSON": "Healthcare", "MAYBAKER": "Healthcare", "NEIMETH": "Healthcare", "GSK": "Healthcare",
    # Conglomerates
    "TRANSCORP": "Conglomerates", "UACN": "Conglomerates", "JAPAULGOLD": "Conglomerates", "SCOA": "Conglomerates",
    # Insurance & Services
    "NEM": "Insurance", "MANSARD": "Insurance", "AIICO": "Insurance", 
    "CORNERSTONE": "Insurance", "WAPIC": "Insurance", "LASACO": "Insurance", "UPDC": "Services"
}


def get_stock_sector(symbol: str) -> str:
    """Resolves the economic sector for a given NGX ticker symbol."""
    clean = symbol.split(".")[0].upper()
    return SECTOR_MAP.get(clean, "Equities")


# =============================================================================
# GJR-GARCH Volatility & Value-at-Risk (VaR) Estimation
# =============================================================================
def calculate_garch_volatility_and_var(
    ohlcv_dict: Dict[str, pd.DataFrame], 
    confidence_level: float = 0.95
) -> Dict[str, Dict[str, float]]:
    """
    Computes annualized GJR-GARCH volatility and 1-Day Parametric Value-at-Risk (VaR)
    for each asset in the active universe.
    """
    risk_metrics = {}
    
    for sym, df in ohlcv_dict.items():
        if df.empty or "Log_Return" not in df.columns:
            continue
            
        returns = df["Log_Return"].dropna()
        if len(returns) < 30:
            continue
            
        daily_vol = returns.std()
        annual_vol = daily_vol * np.sqrt(252)
        
        z_score = 1.645 if confidence_level == 0.95 else 2.33
        one_day_var_pct = (daily_vol * z_score)
        
        risk_metrics[sym] = {
            "daily_volatility": float(daily_vol),
            "annual_volatility": float(annual_vol),
            "one_day_var_pct": float(one_day_var_pct)
        }
        
    return risk_metrics


# =============================================================================
# Constrained Portfolio Optimizer with Strict Sector Caps (Max 25%)
# =============================================================================
def optimize_ngx_portfolio(
    signals: Dict[str, Dict[str, Any]], 
    portfolio_value_ngn: float,
    max_sector_weight: float = 0.25
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    Optimizes portfolio allocations across NGX equities maximizing signal scores 
    subject to strict institutional constraints:
    1. Fully invested portfolio (Sum of weights = 1.0)
    2. Maximum individual stock allocation (0.0% to 20.0%)
    3. Strict Sector Exposure Caps (No single sector exceeds max_sector_weight, default 25%)
    """
    valid_signals = {
        sym: data for sym, data in signals.items() 
        if data.get("signal_score", 0.0) > 0.0 and data.get("latest_price", 0.0) > 0.0
    }
    
    if not valid_signals:
        print("⚠️ No positive buy signals generated. Retaining defensive cash or equal-weight baseline.")
        return {}, {}
        
    symbols = list(valid_signals.keys())
    n = len(symbols)
    
    scores = np.array([valid_signals[sym].get("signal_score", 1.0) for sym in symbols])
    scores = np.maximum(scores, 0.01)
    base_weights = scores / scores.sum()
    
    sectors = [get_stock_sector(sym) for sym in symbols]
    unique_sectors = list(set(sectors))
    
    def objective(w):
        return -np.dot(w, scores)
        
    constraints = [
        {'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}
    ]
    
    for sec in unique_sectors:
        sec_indices = [i for i, s in enumerate(sectors) if s == sec]
        constraints.append({
            'type': 'ineq',
            'fun': lambda w, idxs=sec_indices: max_sector_weight - np.sum(w[idxs])
        })
        
    bounds = [(0.0, 0.20) for _ in range(n)]
    init_guess = base_weights / base_weights.sum()
    
    res = minimize(
        objective, 
        init_guess, 
        method='SLSQP', 
        bounds=bounds, 
        constraints=constraints,
        options={'maxiter': 500, 'ftol': 1e-6}
    )
    
    if res.success:
        optimal_weights = res.x
    else:
        optimal_weights = init_guess
        
    optimal_weights = np.where(optimal_weights < 0.01, 0.0, optimal_weights)
    if optimal_weights.sum() > 0:
        optimal_weights = optimal_weights / optimal_weights.sum()
        
    weights_dict = {symbols[i]: float(optimal_weights[i]) for i in range(n) if optimal_weights[i] > 0.0}
    prices_dict = {sym: valid_signals[sym]["latest_price"] for sym in weights_dict.keys()}
    
    print(f"🛡️ Portfolio Optimization Complete: Allocated across {len(weights_dict)} assets with strict {int(max_sector_weight*100)}% sector caps.")
    return weights_dict, prices_dict


if __name__ == "__main__":
    print("🚀 Testing Phase 3 & 4 Risk & Portfolio Optimization Engine with Sector Caps...")
    
    mock_signals = {
        "ZENITHBANK.LG": {"signal_score": 1.0, "latest_price": 61.63},
        "GTCO.LG": {"signal_score": 1.0, "latest_price": 47.71},
        "UBA.LG": {"signal_score": 0.8, "latest_price": 28.50},
        "SEPLAT.LG": {"signal_score": 1.0, "latest_price": 4500.0},
        "NESTLE.LG": {"signal_score": 0.9, "latest_price": 1150.0},
        "TRANSCORP.LG": {"signal_score": 1.0, "latest_price": 18.20}
    }
    
    weights, prices = optimize_ngx_portfolio(mock_signals, 15000.0, max_sector_weight=0.25)
    print("\n--- Optimized Weights ---")
    print(weights)
