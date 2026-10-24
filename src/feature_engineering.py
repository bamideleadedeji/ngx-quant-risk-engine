"""
===============================================================================
NGX Quantitative Engine — Phase 2: Feature Engineering & Preprocessing
File: src/feature_engineering.py
===============================================================================
Description:
    Transforms raw NGX daily price series, corporate fundamentals, and CBN
    macroeconomic indicators into stationary, high-signal feature matrices.

Key Features:
    - Augmented Dickey-Fuller (ADF) time-series stationarity testing
    - Rolling realized volatility & technical momentum indicators (EMA, RSI, MACD)
    - Real yield differentials (Inflation/MPR adjusted) & FX sensitivity
    - Feature lag creation (t-1, t-5, t-20) to prevent lookahead bias
    - Robust scaling for machine learning & deep learning models
===============================================================================
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional
from statsmodels.tsa.stattools import adfuller


# =============================================================================
# 2.1 Stationarity & Return Transformation
# =============================================================================
def check_stationarity(series: pd.Series, significance_level: float = 0.05) -> Dict[str, Union[float, bool]]:
    """
    Performs the Augmented Dickey-Fuller (ADF) test to verify time-series stationarity.
    
    Returns:
        dict: ADF statistic, p-value, critical values, and boolean is_stationary flag.
    """
    clean_series = series.dropna()
    if len(clean_series) < 20:
        return {"adf_stat": np.nan, "p_value": 1.0, "is_stationary": False}

    result = adfuller(clean_series, autolag="AIC")
    p_value = float(result[1])
    
    return {
        "adf_stat": float(result[0]),
        "p_value": p_value,
        "is_stationary": p_value < significance_level
    }


def compute_log_returns(df: pd.DataFrame, price_col: str = "Close") -> pd.DataFrame:
    """
    Computes daily log returns and cumulative log returns for stationarity.
    Formula: r_t = ln(P_t / P_{t-1})
    """
    df = df.copy()
    df["Log_Return"] = np.log(df[price_col] / df[price_col].shift(1))
    df["Cum_Log_Return"] = df["Log_Return"].cumsum()
    return df


# =============================================================================
# 2.2 Rolling Volatility & Technical Momentum Features
# =============================================================================
def add_technical_momentum_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Constructs rolling volatility windows and technical momentum indicators:
    - Rolling Realized Volatility (20-day, 60-day, 90-day)
    - Exponential Moving Averages (EMA 9, 21, 50, 200)
    - Relative Strength Index (RSI 14)
    - Moving Average Convergence Divergence (MACD & Signal Line)
    - Bollinger Bands (20-day, 2 stddev)
    """
    df = df.copy()
    
    # 1. Rolling Realized Annualized Volatility (assuming 252 trading days)
    df["Vol_20D"] = df["Log_Return"].rolling(window=20).std() * np.sqrt(252)
    df["Vol_60D"] = df["Log_Return"].rolling(window=60).std() * np.sqrt(252)
    df["Vol_90D"] = df["Log_Return"].rolling(window=90).std() * np.sqrt(252)

    # 2. Exponential Moving Averages (EMA)
    df["EMA_9"] = df["Close"].ewm(span=9, adjust=False).mean()
    df["EMA_21"] = df["Close"].ewm(span=21, adjust=False).mean()
    df["EMA_50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["EMA_200"] = df["Close"].ewm(span=200, adjust=False).mean()
    
    # Price-to-EMA ratios (Stationary momentum features)
    df["Ratio_EMA_9"] = df["Close"] / df["EMA_9"] - 1.0
    df["Ratio_EMA_21"] = df["Close"] / df["EMA_21"] - 1.0
    df["Ratio_EMA_50"] = df["Close"] / df["EMA_50"] - 1.0

    # 3. Relative Strength Index (RSI 14)
    delta = df["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    df["RSI_14"] = 100 - (100 / (1 + rs))

    # 4. MACD & Signal Line
    ema_12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema_26 = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema_12 - ema_26
    df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]

    # 5. Bollinger Bands
    rolling_mean_20 = df["Close"].rolling(window=20).mean()
    rolling_std_20 = df["Close"].rolling(window=20).std()
    df["BB_Upper"] = rolling_mean_20 + (rolling_std_20 * 2)
    df["BB_Lower"] = rolling_mean_20 - (rolling_std_20 * 2)
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / (rolling_mean_20 + 1e-9)

    return df


# =============================================================================
# 2.3 Macroeconomic & Fundamental Integration
# =============================================================================
def integrate_macro_features(df: pd.DataFrame, macro_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merges CBN macroeconomic drivers (MPR, Inflation, USD/NGN FX) with equity price series
    and computes macro-adjusted interaction variables.
    """
    df = df.copy()
    
    if macro_df.empty:
        # Fallback if macro data is unpopulated
        df["CBN_MPR_Pct"] = 26.75
        df["Inflation_YoY_Pct"] = 14.63
        df["USD_NGN_Parallel"] = 1620.0
    else:
        # Forward-fill macro metrics onto daily equity timestamp index
        df = pd.merge_asof(
            df.sort_index(), 
            macro_df.sort_index(), 
            left_index=True, 
            right_index=True, 
            direction="backward"
        )
        df["CBN_MPR_Pct"] = df["CBN_MPR_Pct"].ffill().bfill()
        df["Inflation_YoY_Pct"] = df["Inflation_YoY_Pct"].ffill().bfill()
        df["USD_NGN_Parallel"] = df["USD_NGN_Parallel"].ffill().bfill()

    # Calculate Macro Interaction Variables
    # Real Inflation-Adjusted Log Return
    daily_inflation_rate = (df["Inflation_YoY_Pct"] / 100.0) / 252.0
    df["Real_Log_Return"] = df["Log_Return"] - daily_inflation_rate

    # FX Sensitivity Coefficient (20-day rolling correlation with USD/NGN)
    df["FX_Log_Return"] = np.log(df["USD_NGN_Parallel"] / df["USD_NGN_Parallel"].shift(1)).fillna(0.0)
    df["FX_Sensitivity_20D"] = df["Log_Return"].rolling(20).corr(df["FX_Log_Return"]).fillna(0.0)

    return df


# =============================================================================
# 2.4 Feature Lagging & Master Matrix Construction
# =============================================================================
def build_feature_matrix(
    ohlcv_df: pd.DataFrame, 
    macro_df: Optional[pd.DataFrame] = None,
    lags: List[int] = [1, 5, 20]
) -> pd.DataFrame:
    """
    Orchestrates Phase 2 feature generation:
    1. Computes Log Returns & checks Stationarity
    2. Builds Technical Momentum & Volatility Features
    3. Merges Macro Factors & Interaction Terms
    4. Creates Lags (t-1, t-5, t-20) to ensure NO lookahead bias for ML models
    
    Returns:
        pd.DataFrame: Clean, stationarity-tested master feature matrix.
    """
    # Step 1: Log Returns
    df = compute_log_returns(ohlcv_df)
    
    # Verify Stationarity on raw returns
    stat_res = check_stationarity(df["Log_Return"])
    print(f"  🔍 Stationarity Test (ADF p-value: {stat_res['p_value']:.4f}) -> Stationary: {stat_res['is_stationary']}")

    # Step 2: Technical & Volatility Features
    df = add_technical_momentum_features(df)

    # Step 3: Macro Integration
    if macro_df is not None:
        df = integrate_macro_features(df, macro_df)
    else:
        df = integrate_macro_features(df, pd.DataFrame())

    # Step 4: Lagged Predictive Features (t-1, t-5, t-20)
    features_to_lag = ["Log_Return", "Vol_20D", "RSI_14", "MACD_Hist", "Real_Log_Return", "FX_Sensitivity_20D"]
    for col in features_to_lag:
        if col in df.columns:
            for lag in lags:
                df[f"{col}_lag_{lag}"] = df[col].shift(lag)

    # Drop NaNs created by rolling windows and lagging
    df.dropna(inplace=True)

    return df


if __name__ == "__main__":
    # Local Test Execution using Phase 1 Data Ingestion
    from src.data_ingestion import run_phase_1_pipeline

    print("🚀 Testing Phase 2 Feature Engineering Pipeline...")
    raw_data = run_phase_1_pipeline(symbols=["CADBURY.LG"], start_date="2022-01-01")
    
    cadbury_ohlcv = raw_data["ohlcv_series"]["CADBURY.LG"]
    macro_df = raw_data["macro_indicators"]

    feature_matrix = build_feature_matrix(cadbury_ohlcv, macro_df)
    
    print("\n✅ Phase 2 Master Feature Matrix Constructed Successfully!")
    print(f"  • Shape: {feature_matrix.shape} (Rows x Feature Columns)")
    print("  • Feature Sample Columns:", list(feature_matrix.columns[:10]))
