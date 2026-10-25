"""
===============================================================================
NGX Quantitative Engine — Master Predictive Pipeline Orchestrator
File: src/predictive_models.py
===============================================================================
Description:
    Combines econometric GARCH volatility forecasting and PyTorch deep learning
    (LSTM & Transformer) return models across ingested NGX price series.
===============================================================================
"""

import pandas as pd
from typing import Dict, Any

# Dynamic import supporting both flat (src/) and subfolder (src/models/) structures
try:
    from src.models.deep_forecaster import train_lstm_forecaster, train_transformer_forecaster, generate_directional_signal_score
    from src.models.econometric_volatility import forecast_volatility_horizon
except ModuleNotFoundError:
    try:
        from src.deep_forecaster import train_lstm_forecaster, train_transformer_forecaster, generate_directional_signal_score
        from src.econometric_volatility import forecast_volatility_horizon
    except ModuleNotFoundError:
        from deep_forecaster import train_lstm_forecaster, train_transformer_forecaster, generate_directional_signal_score
        from econometric_volatility import forecast_volatility_horizon


def run_predictive_pipeline(ohlcv_dict: Dict[str, pd.DataFrame]) -> Dict[str, float]:
    """
    Master pipeline entry-point called by GitHub Actions workflow & Streamlit app.
    
    Parameters:
        ohlcv_dict (dict): Dictionary mapping stock tickers to OHLCV DataFrames.
        
    Returns:
        dict: Ticker to normalized signal scores S_i in [-1.0, +1.0].
    """
    signals = {}
    print(f"🚀 Running Predictive Pipeline on {len(ohlcv_dict)} tickers...")

    for symbol, df in ohlcv_dict.items():
        if df is None or df.empty or len(df) < 30:
            print(f"  ⚠️ Skipping {symbol}: Insufficient historical data.")
            signals[symbol] = 0.0
            continue

        returns = df["Log_Return"] if "Log_Return" in df.columns else df["Close"].pct_change().dropna()

        # 1. Econometric GARCH Volatility Forecast
        vol_res = forecast_volatility_horizon(returns, horizon_days=20)
        garch_vol = vol_res.get("1D_predicted_vol_pct", float(returns.std()))

        # 2. PyTorch Deep Learning Return Models
        _, lstm_pred = train_lstm_forecaster(returns, epochs=5)
        _, trans_pred = train_transformer_forecaster(returns, epochs=5)

        # 3. Composite Signal Score
        sig_info = generate_directional_signal_score(
            returns=returns,
            garch_vol_pred=garch_vol,
            lstm_return_pred=lstm_pred,
            transformer_return_pred=trans_pred
        )

        signals[symbol] = sig_info["signal_score"]
        print(f"  📈 {symbol}: Signal = {sig_info['signal_score']:.4f} ({sig_info['recommended_action']})")

    return signals
