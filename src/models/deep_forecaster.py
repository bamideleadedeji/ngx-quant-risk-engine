"""
===============================================================================
NGX Quantitative Engine — Phase 3.2: Deep Learning Return Forecasting
File: src/models/deep_forecaster.py
===============================================================================
Description:
    PyTorch Deep Learning architectures (LSTM & Transformer Network) for predicting
    30-to-90-day return distributions and generating unified directional signal
    scores (S_i in [-1, +1]) for NGX equities.

Features:
    - Multi-layer PyTorch LSTM Neural Network
    - Temporal Multi-Head Attention Transformer Network
    - Standardized signal score conversion for downstream portfolio allocation
===============================================================================
"""

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
from typing import Tuple, Dict


# Set PyTorch seed for deterministic consistency
torch.manual_seed(42)


# =============================================================================
# PyTorch Architectures
# =============================================================================
class LSTMVolForecaster(nn.Module):
    """Multi-layer Long Short-Term Memory Network for sequential return forecasting."""
    def __init__(self, input_dim: int = 1, hidden_dim: int = 32, num_layers: int = 2):
        super(LSTMVolForecaster, self).__init__()
        self.lstm = nn.LSTM(input_dim, hidden_dim, num_layers, batch_first=True)
        self.fc = nn.Linear(hidden_dim, 1)

    def forward(self, x):
        out, _ = self.lstm(x)
        out = self.fc(out[:, -1, :])
        return out


class TransformerForecaster(nn.Module):
    """Multi-Head Attention Transformer for non-linear feature temporal mapping."""
    def __init__(self, input_dim: int = 1, d_model: int = 32, nhead: int = 2, num_layers: int = 1):
        super(TransformerForecaster, self).__init__()
        self.embedding = nn.Linear(input_dim, d_model)
        encoder_layer = nn.TransformerEncoderLayer(d_model=d_model, nhead=nhead, batch_first=True)
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.fc = nn.Linear(d_model, 1)

    def forward(self, x):
        x = self.embedding(x)
        out = self.transformer(x)
        out = self.fc(out[:, -1, :])
        return out


# =============================================================================
# Helper Utilities & Model Training
# =============================================================================
def prepare_sequence_data(series: pd.Series, seq_length: int = 20) -> Tuple[torch.Tensor, torch.Tensor]:
    """Converts a univariate pandas Series into supervised (X, Y) 3D sequence tensors."""
    data = series.dropna().values
    X, Y = [], []
    for i in range(len(data) - seq_length):
        X.append(data[i : i + seq_length])
        Y.append(data[i + seq_length])
        
    X_arr = np.array(X)[..., np.newaxis]
    Y_arr = np.array(Y)
    
    return torch.tensor(X_arr, dtype=torch.float32), torch.tensor(Y_arr, dtype=torch.float32).unsqueeze(1)


def train_lstm_forecaster(
    returns: pd.Series, 
    seq_length: int = 20, 
    epochs: int = 10, 
    lr: float = 0.01
) -> Tuple[nn.Module, float]:
    """Trains the PyTorch LSTM model on return series and predicts the next period return."""
    clean_series = returns.dropna()
    if len(clean_series) <= seq_length:
        return None, float(clean_series.mean() if len(clean_series) > 0 else 0.0)

    X_tensor, Y_tensor = prepare_sequence_data(clean_series, seq_length=seq_length)
    
    model = LSTMVolForecaster(input_dim=1, hidden_dim=32, num_layers=2)
    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=lr)

    model.train()
    for _ in range(epochs):
        optimizer.zero_grad()
        predictions = model(X_tensor)
        loss = criterion(predictions, Y_tensor)
        loss.backward()
        optimizer.step()

    model.eval()
    with torch.no_grad():
        last_seq = torch.tensor(clean_series.values[-seq_length:], dtype=torch.float32).unsqueeze(0).unsqueeze(-1)
        next_pred = float(model(last_seq).item())

    return model, next_pred


def train_transformer_forecaster(
    returns: pd.Series, 
    seq_length: int = 20, 
    epochs: int = 10, 
    lr: float = 0.01
) -> Tuple[nn.Module, float]:
    """Trains the PyTorch Transformer model on return series and predicts the next period return."""
    clean_series = returns.dropna()
    if len(clean_series) <= seq_length:
        return None, float(clean_series.mean() if len(clean_series) > 0 else 0.0)

    X_tensor, Y_tensor = prepare_sequence_data(clean_series, seq_length=seq_length)
    
    model = TransformerForecaster(input_dim=1, d_model=32, nhead=2, num_layers=1)
    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=lr)

    model.train()
    for _ in range(epochs):
        optimizer.zero_grad()
        predictions = model(X_tensor)
        loss = criterion(predictions, Y_tensor)
        loss.backward()
        optimizer.step()

    model.eval()
    with torch.no_grad():
        last_seq = torch.tensor(clean_series.values[-seq_length:], dtype=torch.float32).unsqueeze(0).unsqueeze(-1)
        next_pred = float(model(last_seq).item())

    return model, next_pred


# =============================================================================
# Signal Matrix & Conviction Score Generator
# =============================================================================
def generate_directional_signal_score(
    returns: pd.Series, 
    garch_vol_pred: float, 
    lstm_return_pred: float, 
    transformer_return_pred: float
) -> Dict[str, Any]:
    """
    Combines econometric volatility and deep learning return forecasts into a unified
    directional signal score: S_i in [-1.0, +1.0]

    Formula:
        Raw Signal = Mean(LSTM_Pred, Transformer_Pred) / (GARCH_Vol_Pred + 1e-6)
        S_i = tanh(Raw Signal)  --> Maps output bounded between -1 (Strong Sell) and +1 (Strong Buy)
    """
    avg_pred_return = (lstm_return_pred + transformer_return_pred) / 2.0
    risk_adjusted_signal = avg_pred_return / (garch_vol_pred + 1e-6)
    
    # Hyperbolic tangent maps raw signal bounded strictly into [-1.0, +1.0]
    signal_score = float(np.tanh(risk_adjusted_signal * 10.0))
    
    if signal_score > 0.35:
        action = "STRONG_BUY"
    elif signal_score > 0.10:
        action = "BUY"
    elif signal_score < -0.35:
        action = "STRONG_SELL"
    elif signal_score < -0.10:
        action = "SELL"
    else:
        action = "NEUTRAL_HOLD"

    return {
        "avg_predicted_return": float(avg_pred_return),
        "garch_predicted_volatility": float(garch_vol_pred),
        "risk_adjusted_ratio": float(risk_adjusted_signal),
        "signal_score": signal_score,  # Bounded in [-1, +1]
        "recommended_action": action
    }


if __name__ == "__main__":
    print("🚀 Testing Phase 3 Deep Learning & Econometric Engine...")
    
    # Generate dummy return series for testing
    dates = pd.date_range("2023-01-01", periods=200, freq="B")
    sample_returns = pd.Series(np.random.normal(0.0005, 0.015, size=200), index=dates)

    # 1. Test Deep Learning Models
    _, lstm_pred = train_lstm_forecaster(sample_returns, epochs=5)
    _, trans_pred = train_transformer_forecaster(sample_returns, epochs=5)

    print(f"  • LSTM Predicted Return       : {lstm_pred * 100:.4f}%")
    print(f"  • Transformer Predicted Return: {trans_pred * 100:.4f}%")

    # 2. Test Signal Score Generation
    signal_res = generate_directional_signal_score(
        returns=sample_returns,
        garch_vol_pred=0.012,
        lstm_return_pred=lstm_pred,
        transformer_return_pred=trans_pred
    )
    
    print("\n✅ Phase 3 Engine Test Complete!")
    print(f"  • Signal Score S_i [-1 to +1]: {signal_res['signal_score']:.4f}")
    print(f"  • Recommended Action         : {signal_res['recommended_action']}")
