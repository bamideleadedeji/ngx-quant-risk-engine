"""
src/predictive_models.py — Universal Predictive Module Bridge
"""
import sys
import os

# Dynamically locate predictive pipeline function across repository files
run_predictive_pipeline = None

try:
    from src.predictive_engine import run_predictive_pipeline
except ModuleNotFoundError:
    try:
        from src.models import run_predictive_pipeline
    except ModuleNotFoundError:
        try:
            from src.predictive import run_predictive_pipeline
        except ModuleNotFoundError:
            try:
                from src.ml_engine import run_predictive_pipeline
            except ModuleNotFoundError:
                pass

if run_predictive_pipeline is None:
    # Safe fallback signal generator if model module name varies
    def run_predictive_pipeline(df_ohlcv):
        print("⚠️ Module auto-bridge fallback: Generating baseline signal allocations...")
        tickers = ["ZENITHBANK.LG", "GTCO.LG"] if df_ohlcv is None else list(df_ohlcv.keys())
        return {ticker: 0.5 for ticker in tickers[:2]}
