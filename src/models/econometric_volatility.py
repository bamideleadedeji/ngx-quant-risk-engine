"""
===============================================================================
NGX Quantitative Engine — Phase 3.1: Econometric Volatility Modeling
File: src/models/econometric_volatility.py
===============================================================================
Description:
    Parameterizes symmetric and asymmetric GARCH models (GARCH, GJR-GARCH, EGARCH)
    to model conditional volatility clustering and leverage shocks across 
    NGX equity log returns.

Features:
    - Standard GARCH(1,1) for baseline volatility dynamics
    - GJR-GARCH(1,1,1) for asymmetric leverage shocks
    - Exponential GARCH (EGARCH) for log-volatility persistence
    - Out-of-sample multi-period volatility forecasting horizon
===============================================================================
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, Any
from arch import arch_model


def fit_standard_garch(
    returns: pd.Series, 
    p: int = 1, 
    q: int = 1
) -> Tuple[Dict[str, float], pd.Series]:
    """
    Fits a symmetric GARCH(p,q) model with Student's t-distribution.
    Formula: \sigma_t^2 = \omega + \alpha \epsilon_{t-1}^2 + \beta \sigma_{t-1}^2
    """
    clean_returns = returns.dropna() * 100.0  # Scale returns to percentage for solver stability
    
    try:
        am = arch_model(clean_returns, vol="Garch", p=p, q=q, dist="StudentsT", rescale=False)
        res = am.fit(disp="off")
        
        params = {
            "omega": float(res.params.get("omega", 0.0)),
            "alpha": float(res.params.get("alpha[1]", 0.0)),
            "beta": float(res.params.get("beta[1]", 0.0)),
            "persistence": float(res.params.get("alpha[1]", 0.0) + res.params.get("beta[1]", 0.0)),
            "aic": float(res.aic),
            "bic": float(res.bic)
        }
        
        # Unscale conditional volatility back to decimal
        cond_vol = pd.Series(res.conditional_volatility / 100.0, index=clean_returns.index)
        return params, cond_vol
    except Exception as e:
        print(f"⚠️ Standard GARCH fit warning: {str(e)}")
        # Fallback to rolling historical volatility
        rolling_vol = returns.rolling(20).std().fillna(returns.std())
        return {}, rolling_vol


def fit_gjr_garch(
    returns: pd.Series, 
    p: int = 1, 
    o: int = 1, 
    q: int = 1
) -> Tuple[Dict[str, float], pd.Series]:
    """
    Fits an asymmetric GJR-GARCH(p,o,q) model to capture asymmetry (leverage effect).
    In emerging markets like NGX, bad news often increases volatility more than good news.
    """
    clean_returns = returns.dropna() * 100.0
    
    try:
        am = arch_model(clean_returns, vol="GARCH", p=p, o=o, q=q, dist="StudentsT", rescale=False)
        res = am.fit(disp="off")
        
        params = {
            "omega": float(res.params.get("omega", 0.0)),
            "alpha": float(res.params.get("alpha[1]", 0.0)),
            "gamma_asymmetry": float(res.params.get("gamma[1]", 0.0)),
            "beta": float(res.params.get("beta[1]", 0.0)),
            "aic": float(res.aic),
            "bic": float(res.bic)
        }
        
        cond_vol = pd.Series(res.conditional_volatility / 100.0, index=clean_returns.index)
        return params, cond_vol
    except Exception as e:
        print(f"⚠️ GJR-GARCH fit warning: {str(e)}")
        rolling_vol = returns.rolling(20).std().fillna(returns.std())
        return {}, rolling_vol


def fit_egarch(
    returns: pd.Series, 
    p: int = 1, 
    q: int = 1
) -> Tuple[Dict[str, float], pd.Series]:
    """
    Fits an Exponential GARCH (EGARCH) model.
    Models log-volatility to ensure conditional variance is strictly positive.
    """
    clean_returns = returns.dropna() * 100.0
    
    try:
        am = arch_model(clean_returns, vol="EGARCH", p=p, q=q, dist="StudentsT", rescale=False)
        res = am.fit(disp="off")
        
        params = {
            "omega": float(res.params.get("omega", 0.0)),
            "alpha": float(res.params.get("alpha[1]", 0.0)),
            "beta": float(res.params.get("beta[1]", 0.0)),
            "aic": float(res.aic),
            "bic": float(res.bic)
        }
        
        cond_vol = pd.Series(res.conditional_volatility / 100.0, index=clean_returns.index)
        return params, cond_vol
    except Exception as e:
        print(f"⚠️ EGARCH fit warning: {str(e)}")
        rolling_vol = returns.rolling(20).std().fillna(returns.std())
        return {}, rolling_vol


def forecast_volatility_horizon(
    returns: pd.Series, 
    horizon_days: int = 20
) -> Dict[str, Any]:
    """
    Generates out-of-sample multi-day volatility projections across models.
    """
    clean_returns = returns.dropna() * 100.0
    
    try:
        am = arch_model(clean_returns, vol="GARCH", p=1, o=1, q=1, dist="StudentsT", rescale=False)
        res = am.fit(disp="off")
        forecasts = res.forecast(horizon=horizon_days)
        
        # Extract variance forecasts and convert to annualized volatility decimal
        var_forecasts = forecasts.variance.iloc[-1].values
        vol_forecasts_annualized = (np.sqrt(var_forecasts) / 100.0) * np.sqrt(252)
        
        return {
            "forecast_horizon_days": horizon_days,
            "1D_predicted_vol_pct": float(np.sqrt(var_forecasts[0]) / 100.0),
            "annualized_horizon_vol_pct": float(vol_forecasts_annualized[-1]),
            "volatility_curve": vol_forecasts_annualized.tolist()
        }
    except Exception as e:
        print(f"⚠️ Volatility forecast warning: {str(e)}")
        hist_vol = float(returns.std() * np.sqrt(252))
        return {
            "forecast_horizon_days": horizon_days,
            "1D_predicted_vol_pct": float(returns.std()),
            "annualized_horizon_vol_pct": hist_vol,
            "volatility_curve": [hist_vol] * horizon_days
        }
