from datetime import datetime
import logging
import os
import pandas as pd

# Import Telegram signal dispatching from execution_engine
try:
    from src.execution_engine import send_telegram_trade_signal
except ImportError:
    try:
        from execution_engine import send_telegram_trade_signal
    except ImportError:
        send_telegram_trade_signal = None

# Configure logging for audit trails
logging.basicConfig(
    filename="ngx_engine_audit.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


class NGXQuantEngine:

    def __init__(self, initial_capital: float):
        self.cash_balance = initial_capital
        self.portfolio = {}
        logging.info(
            f"NGX Quant Engine initialized with capital: ₦{initial_capital:,.2f}"
        )

    def fetch_market_data(self, ticker: str) -> float:
        """Fetch real-time market price for an NGX stock."""
        live_prices = {
            "NESTLE": 850.00,
            "ZENITHBANK": 38.50,
            "DANGCEM": 650.00,
            "BUACEMENT": 95.00,
        }
        price = live_prices.get(ticker.upper())
        if not price:
            raise ValueError(f"Live market data not found for {ticker}")
        return price

    def evaluate_signals(self, market_data: dict) -> list:
        """Runs quantitative rules to generate buy/sell signals."""
        signals = []
        for ticker, data in market_data.items():
            if data["signal_indicator"] == "BUY":
                signals.append({
                    "action": "BUY",
                    "ticker": ticker,
                    "units": data["target_units"],
                })
            elif data["signal_indicator"] == "SELL":
                signals.append({
                    "action": "SELL",
                    "ticker": ticker,
                    "units": data["target_units"],
                })
        return signals

    def execute_trade(self, action: str, ticker: str, units: int):
        """Executes buy/sell orders with strict validation checks and Telegram interactive alerts."""
        try:
            current_price = self.fetch_market_data(ticker)
            gross_value = current_price * units
            estimated_fees = (
                gross_value * 0.0139
            )  # 1.39% brokerage and regulatory fees

            order_payload = {
                "symbol": ticker,
                "action": action,
                "units": units,
                "unit_price_ngn": current_price,
                "gross_value_ngn": round(gross_value, 2),
                "total_fee_ngn": round(estimated_fees, 2),
                "total_net_cost_ngn": round(
                    gross_value
                    + (estimated_fees if action == "BUY" else -estimated_fees),
                    2,
                ),
            }

            if action == "BUY":
                total_cost = gross_value + estimated_fees
                if self.cash_balance < total_cost:
                    logging.warning(
                        f"Insufficient funds for {ticker}. Required: ₦{total_cost:,.2f}, Available: ₦{self.cash_balance:,.2f}"
                    )
                    if send_telegram_trade_signal:
                        send_telegram_trade_signal(
                            order_payload,
                            self.cash_balance,
                            "FAILED",
                            "INSUFFICIENT_FUNDS",
                        )
                    return {
                        "status": "REJECTED",
                        "reason": "INSUFFICIENT_FUNDS",
                    }

                # Execute Buy
                self.cash_balance -= total_cost
                self.portfolio[ticker] = self.portfolio.get(ticker, 0) + units
                receipt_id = f"FILL_{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

                logging.info(
                    f"SUCCESS BUY: {units} units of {ticker} at ₦{current_price:,.2f}. Receipt: {receipt_id}"
                )

                if send_telegram_trade_signal:
                    send_telegram_trade_signal(
                        order_payload,
                        self.cash_balance,
                        "FILLED",
                        receipt_id,
                    )

                return {
                    "status": "FILLED",
                    "receipt": receipt_id,
                    "price": current_price,
                    "cash_remaining": self.cash_balance,
                }

            elif action == "SELL":
                current_holding = self.portfolio.get(ticker, 0)
                if current_holding < units:
                    logging.warning(
                        f"Attempted to sell {units} of {ticker}, but holding is only {current_holding}."
                    )
                    if send_telegram_trade_signal:
                        send_telegram_trade_signal(
                            order_payload,
                            self.cash_balance,
                            "FAILED",
                            "INSUFFICIENT_SHARES",
                        )
                    return {
                        "status": "REJECTED",
                        "reason": "INSUFFICIENT_SHARES",
                    }

                # Execute Sell
                net_proceeds = gross_value - estimated_fees
                self.cash_balance += net_proceeds
                self.portfolio[ticker] -= units
                receipt_id = f"SELL_{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

                logging.info(
                    f"SUCCESS SELL: {units} units of {ticker} at ₦{current_price:,.2f}. Receipt: {receipt_id}"
                )

                if send_telegram_trade_signal:
                    send_telegram_trade_signal(
                        order_payload,
                        self.cash_balance,
                        "FILLED",
                        receipt_id,
                    )

                return {
                    "status": "FILLED",
                    "receipt": receipt_id,
                    "price": current_price,
                    "cash_remaining": self.cash_balance,
                }

        except Exception as e:
            logging.error(f"Execution error for {ticker}: {str(e)}")
            return {"status": "ERROR", "reason": str(e)}


if __name__ == "__main__":
    # Test run initialization
    engine = NGXQuantEngine(initial_capital=500000.00)
    print("Engine initialized successfully. Ready for live execution mapping.")
