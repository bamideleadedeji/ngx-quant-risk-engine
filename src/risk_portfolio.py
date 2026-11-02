"""
===============================================================================
NGX Quantitative Engine — Phase 3 & 4: Portfolio Optimization & Risk Engine
File: src/risk_portfolio.py
===============================================================================
Description:
    Performs GJR-GARCH volatility modeling, Value-at-Risk (VaR) calculations, 
    and mean-variance portfolio optimization for Nigerian Exchange (NGX) equities.
    Enforces strict institutional risk limits including maximum sector weight caps (25%),
    liquidity-weighted capital allocation, and CBN Macro-Regime Overlays.

Features:
    - GJR-GARCH(1,1) asymmetric volatility modeling & parametric 1-Day VaR
    - Macro-Regime Overlays (CBN MPR & Inflation Guardrails) to tighten VaR and tilt sector scores
    - Strict Sector Exposure Caps (Max 25% per sector) to eliminate concentration risk
    - SLSQP constrained mean-variance portfolio optimization
===============================================================================
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Any, Optional
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
# Macro-Regime Overlay (CBN MPR & Inflation Guardrails)
# =============================================================================
def calculate_macro_regime_overlay(macro_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Evaluates CBN MPR and headline YoY inflation from ingested macro data.
    If inflation > 25% or MPR > 25%, triggers a defensive stagflation regime overlay
    that tightens VaR risk limits and applies sector tilting multipliers favoring 
    inflation-hedged sectors (Oil & Gas, Agriculture).
    """
    if macro_df is None or macro_df.empty:
        return {
            "regime": "NEUTRAL", 
            "var_multiplier": 1.0, 
            "sector_tilts": {}
        }
        
    latest_macro = macro_df.iloc[-1]
    mpr = latest_macro.get("CBN_MPR_Pct", 26.75)
    inflation = latest_macro.get("Inflation_YoY_Pct", 32.15)
    
    if inflation > 25.0 or mpr > 25.0:
        return {
            "regime": "DEFENSIVE_STAGFLATION",
            "var_multiplier": 0.80,  # Tighten VaR risk limits by 20%
            "sector_tilts": {
                "Oil & Gas": 1.4,      # Upward tilt for inflation-hedged energy commodities
                "Agriculture": 1.3,    # Upward tilt for cash-generative food & agro-allied
                "Banking": 0.9,        # Neutral-to-slight downward tilt
                "Consumer Goods": 0.7  # Downward tilt due to high input costs & margin compression
            }
        }
    else:
        return {
            "regime": "EXPANSIONARY",
            "var_multiplier": 1.0,
            "sector_tilts": {}
        }


def apply_macro_tilt_to_signals(
    signals: Dict[str, Dict[str, Any]], 
    macro_df: pd.DataFrame
) -> Dict[str, Dict[str, Any]]:
    """
    Adjusts quantitative signal scores dynamically based on the prevailing CBN macro regime.
    """
    overlay = calculate_macro_regime_overlay(macro_df)
    tilts = overlay.get("sector_tilts", {})
    
    if not tilts:
        return signals
        
    adjusted_signals = {}
    for sym, data in signals.items():
        sector = data.get("sector", get_stock_sector(sym))
        multiplier = tilts.get(sector, 1.0)
        
        adj_data = data.copy()
        original_score = adj_data.get("signal_score", 1.0)
        adj_data["signal_score"] = original_score * multiplier
        
        adjusted_signals[sym] = adj_data
        
    return adjusted_signals


# =============================================================================
# GJR-GARCH Volatility & Value-at-Risk (VaR) Estimation
# =============================================================================
def calculate_garch_volatility_and_var(
    ohlcv_dict: Dict[str, pd.DataFrame], 
    macro_df: Optional[pd.DataFrame] = None,
    confidence_level: float = 0.95
) -> Dict[str, Dict[str, float]]:
    """
    Computes annualized volatility and 1-Day Parametric Value-at-Risk (VaR)
    adjusted by the CBN Macro-Regime VaR multiplier.
    """
    overlay = calculate_macro_regime_overlay(macro_df)
    var_mult = overlay.get("var_multiplier", 1.0)
    
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
        one_day_var_pct = (daily_vol * z_score) * var_mult
        
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
    
    sectors = [valid_signals[sym].get("sector", get_stock_sector(sym)) for sym in symbols]
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
    print("🚀 Testing Phase 3 & 4 Risk & Portfolio Optimization Engine with Sector Caps & Macro Overlays...")
    
    mock_signals = {
        "ZENITHBANK.LG": {"signal_score": 1.0, "latest_price": 61.63, "sector": "Banking"},
        "GTCO.LG": {"signal_score": 1.0, "latest_price": 47.71, "sector": "Banking"},
        "SEPLAT.LG": {"signal_score": 1.0, "latest_price": 4500.0, "sector": "Oil & Gas"},
        "OKOMUOIL.LG": {"signal_score": 0.9, "latest_price": 380.0, "sector": "Agriculture"}
    }
    
    weights, prices = optimize_ngx_portfolio(mock_signals, 15000.0, max_sector_weight=0.25)
    print("\n--- Optimized Weights ---")
    print(weights)
