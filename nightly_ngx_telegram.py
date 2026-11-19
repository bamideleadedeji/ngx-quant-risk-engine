import os
import json
import math
import smtplib
from email.message import EmailMessage
from datetime import datetime, timezone, timedelta
import pandas as pd
from ngx_live_prices import fetch_official_ngx_closes

STATE_FILE = "ngx_portfolio_state.json"
ORDER_AUDIT_FILE = "ngx_trade_audit.csv"
PORTFOLIO_AUDIT_FILE = "ngx_portfolio_audit.csv"
GMAIL_USER = os.getenv("GMAIL_USER", "bamideleadedeji2000@gmail.com").strip()
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").strip().replace(" ", "")

DEFAULT_HOLDINGS = [
    {"Ticker": "BUAFOODS", "Company": "BUA Foods Plc", "Units": 50.0, "Avg_Cost": 700.00, "Live_Price": 760.60, "Target_Weight_Pct": 16.0},
    {"Ticker": "SEPLAT", "Company": "Seplat Energy Plc", "Units": 2.0, "Avg_Cost": 16000.10, "Live_Price": 16241.90, "Target_Weight_Pct": 16.0},
    {"Ticker": "GTCO", "Company": "Guaranty Trust Holding Co.", "Units": 200.0, "Avg_Cost": 120.90, "Live_Price": 117.00, "Target_Weight_Pct": 16.0},
    {"Ticker": "MTNN", "Company": "MTN Nigeria Comm. Plc", "Units": 15.0, "Avg_Cost": 825.00, "Live_Price": 837.00, "Target_Weight_Pct": 12.0},
    {"Ticker": "ZENITHBANK", "Company": "Zenith Bank Plc", "Units": 100.0, "Avg_Cost": 116.60, "Live_Price": 116.00, "Target_Weight_Pct": 12.0},
    {"Ticker": "OKOMUOIL", "Company": "Okomu Oil Palm Plc", "Units": 10.0, "Avg_Cost": 1148.60, "Live_Price": 1137.09, "Target_Weight_Pct": 10.0},
    {"Ticker": "UNILEVER", "Company": "Unilever Nigeria Plc", "Units": 90.0, "Avg_Cost": 111.92, "Live_Price": 112.20, "Target_Weight_Pct": 10.0},
    {"Ticker": "TRANSCOHOT", "Company": "Transcorp Hotels Plc", "Units": 20.0, "Avg_Cost": 275.30, "Live_Price": 290.50, "Target_Weight_Pct": 8.0},
]

DRIFT_BAND_PCT = 3.0
BUY_BUFFER_PCT = 1.25
SELL_BUFFER_PCT = 1.00
MIN_ORDER_FLOOR = 1500.0
FEE_RATE = 0.0155


def load_state() -> tuple[pd.DataFrame, float]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                df = pd.DataFrame(data.get("holdings", DEFAULT_HOLDINGS))
                cash = float(data.get("free_cash_ngn", 0.0))
                if not df.empty:
                    return df, cash
        except Exception:
            pass
    return pd.DataFrame(DEFAULT_HOLDINGS), 0.0


def save_state(df: pd.DataFrame, free_cash: float):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "free_cash_ngn": float(free_cash),
                "holdings": df.to_dict(orient="records"),
            }, f, indent=2)
    except Exception:
        pass


def send_email(subject: str, body: str):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("GMAIL_APP_PASSWORD not configured; skipping email dispatch.")
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = GMAIL_USER
    msg.set_content(body)
    smtp_host = ".".join(["smtp", "gmail", "com"])
    try:
        with smtplib.SMTP_SSL(smtp_host, 465, timeout=20) as smtp:
            smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        print(f"Email delivered successfully to {GMAIL_USER}!")
    except Exception as exc:
        print(f"Email dispatch error: {exc}")


def compute_rolling_30d_turnover(current_turnover_pct: float) -> float:
    if not os.path.exists(PORTFOLIO_AUDIT_FILE):
        return current_turnover_pct
    try:
        hist = pd.read_csv(PORTFOLIO_AUDIT_FILE)
        if "Timestamp_UTC" in hist.columns and "Turnover_Pct" in hist.columns:
            hist["Timestamp_UTC"] = pd.to_datetime(hist["Timestamp_UTC"], errors="coerce", utc=True)
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            recent = hist[hist["Timestamp_UTC"] >= cutoff]
            return float(recent["Turnover_Pct"].sum()) + current_turnover_pct
    except Exception:
        pass
    return current_turnover_pct

def run_nightly_rebalance_alert():
    utc_now = datetime.now(timezone.utc)
    wat_now = utc_now + timedelta(hours=1)
    df, free_cash = load_state()

    live_prices, feed_status = fetch_official_ngx_closes(df["Ticker"].tolist())
    if live_prices:
        df["Live_Price"] = df.apply(
            lambda r: live_prices.get(str(r["Ticker"]).strip().upper(), r["Live_Price"]), axis=1
        )
        save_state(df, free_cash)

    df["Cost_Value"] = df["Units"] * df["Avg_Cost"]
    df["Market_Value"] = df["Units"] * df["Live_Price"]
    df["Return_Pct"] = ((df["Live_Price"] - df["Avg_Cost"]) / df["Avg_Cost"].replace(0, 1)) * 100.0

    equity_total = float(df["Market_Value"].sum())
    total_portfolio = equity_total + free_cash
    total_pnl = equity_total - float(df["Cost_Value"].sum())

    weight_sum = float(df["Target_Weight_Pct"].sum())
    df["Norm_Target_Pct"] = (df["Target_Weight_Pct"] / weight_sum * 100.0) if weight_sum > 0 else 0.0
    df["Actual_Weight_Pct"] = (df["Market_Value"] / total_portfolio * 100.0) if total_portfolio > 0 else 0.0
    df["Drift_Pct"] = df["Actual_Weight_Pct"] - df["Norm_Target_Pct"]
    df["Dollar_Drift_NGN"] = df["Market_Value"] - (total_portfolio * (df["Norm_Target_Pct"] / 100.0))

    max_drift_before = float(df["Drift_Pct"].abs().max()) if not df.empty else 0.0
    mad_drift_before = float(df["Drift_Pct"].abs().mean()) if not df.empty else 0.0

    sell_tickets = []
    projected_cash = free_cash
    total_sell_gross = 0.0
    total_est_fees = 0.0
    projected_units = dict(zip(df["Ticker"], df["Units"]))

    overweight = df[df["Drift_Pct"] >= DRIFT_BAND_PCT].sort_values(by="Drift_Pct", ascending=False)
    for _, row in overweight.iterrows():
        excess_ngn = float(row["Dollar_Drift_NGN"])
        close_px = float(row["Live_Price"])
        limit_sell_px = round(close_px * (1.0 - SELL_BUFFER_PCT / 100.0), 2)
        shares_to_sell = min(int(math.floor(excess_ngn / close_px)), int(math.floor(float(row["Units"]))))
        gross_val = shares_to_sell * limit_sell_px
        if shares_to_sell >= 1 and gross_val >= MIN_ORDER_FLOOR:
            fee_amt = gross_val * FEE_RATE
            projected_cash += (gross_val - fee_amt)
            total_sell_gross += gross_val
            total_est_fees += fee_amt
            projected_units[row["Ticker"]] = max(0.0, float(projected_units[row["Ticker"]]) - shares_to_sell)
            sell_tickets.append({
                "Ticker": row["Ticker"],
                "Action": "SELL",
                "Units": shares_to_sell,
                "Ref_Close": close_px,
                "Limit_NGN": limit_sell_px,
                "Value_NGN": round(gross_val, 2),
                "Drift": f"{row['Drift_Pct']:+.2f}%",
            })

    buy_tickets = []
    total_buy_gross = 0.0
    post_rebalance_cash = projected_cash
    underweight = df[df["Drift_Pct"] <= -DRIFT_BAND_PCT].sort_values(by="Drift_Pct", ascending=True)
    total_deficit = float(abs(underweight["Dollar_Drift_NGN"]).sum()) if not underweight.empty else 0.0

    if projected_cash >= MIN_ORDER_FLOOR and total_deficit > 0:
        for _, row in underweight.iterrows():
            deficit_ngn = abs(float(row["Dollar_Drift_NGN"]))
            alloc_cash = projected_cash * (deficit_ngn / total_deficit)
            close_px = float(row["Live_Price"])
            limit_buy_px = round(close_px * (1.0 + BUY_BUFFER_PCT / 100.0), 2)
            shares_to_buy = int(math.floor(alloc_cash / (limit_buy_px * (1.0 + FEE_RATE))))
            est_val = shares_to_buy * limit_buy_px
            if shares_to_buy >= 1 and est_val >= MIN_ORDER_FLOOR:
                fee_amt = est_val * FEE_RATE
                total_buy_gross += est_val
                total_est_fees += fee_amt
                post_rebalance_cash = max(0.0, post_rebalance_cash - (est_val + fee_amt))
                projected_units[row["Ticker"]] = float(projected_units[row["Ticker"]]) + shares_to_buy
                buy_tickets.append({
                    "Ticker": row["Ticker"],
                    "Action": "BUY",
                    "Units": shares_to_buy,
                    "Ref_Close": close_px,
                    "Limit_NGN": limit_buy_px,
                    "Value_NGN": round(est_val, 2),
                    "Drift": f"{row['Drift_Pct']:+.2f}%",
                })

    df["Post_Units"] = df["Ticker"].map(projected_units)
    df["Post_Market_Value"] = df["Post_Units"] * df["Live_Price"]
    post_total_portfolio = float(df["Post_Market_Value"].sum()) + post_rebalance_cash
    df["Post_Weight_Pct"] = (df["Post_Market_Value"] / post_total_portfolio * 100.0) if post_total_portfolio > 0 else 0.0
    df["Post_Drift_Pct"] = df["Post_Weight_Pct"] - df["Norm_Target_Pct"]
    mad_drift_after = float(df["Post_Drift_Pct"].abs().mean()) if not df.empty else 0.0

    turnover_pct = ((total_sell_gross + total_buy_gross) / (2.0 * total_portfolio) * 100.0) if total_portfolio > 0 else 0.0
    rolling_30d_turnover = compute_rolling_30d_turnover(turnover_pct)
    fee_drag_pct = (total_est_fees / total_portfolio * 100.0) if total_portfolio > 0 else 0.0

    pd.DataFrame([{
        "Timestamp_UTC": utc_now.strftime("%Y-%m-%d %H:%M:%S"),
        "Timestamp_WAT": wat_now.strftime("%Y-%m-%d %H:%M:%S"),
        "Price_Feed_Status": feed_status,
        "Total_Portfolio_NGN": round(total_portfolio, 2),
        "Equities_Value_NGN": round(equity_total, 2),
        "Pre_Rebalance_Cash_NGN": round(free_cash, 2),
        "Post_Rebalance_Cash_NGN": round(post_rebalance_cash, 2),
        "Max_Drift_Before_Pct": round(max_drift_before, 2),
        "Mean_Abs_Drift_Before_Pct": round(mad_drift_before, 2),
        "Projected_Mean_Abs_Drift_After_Pct": round(mad_drift_after, 2),
        "Est_Brokerage_Fees_NGN": round(total_est_fees, 2),
        "Fee_Drag_Pct": round(fee_drag_pct, 3),
        "Cycle_Turnover_Pct": round(turnover_pct, 2),
        "Rolling_30D_Turnover_Pct": round(rolling_30d_turnover, 2),
        "Orders_Generated": len(sell_tickets) + len(buy_tickets),
    }]).to_csv(PORTFOLIO_AUDIT_FILE, mode="a", header=not os.path.exists(PORTFOLIO_AUDIT_FILE), index=False)

    lines = [
        "NGX MIDNIGHT BAMBOO ORDER TICKET & PORTFOLIO TELEMETRY",
        f"Timestamp: {wat_now.strftime('%Y-%m-%d %I:%M %p WAT')}",
        f"Price Feed: {feed_status}",
        f"Portfolio Value: NGN {total_portfolio:,.2f} ({total_pnl:+,.2f})",
        f"Cash (Pre -> Post Rebalance): NGN {free_cash:,.2f} -> NGN {post_rebalance_cash:,.2f}",
        f"Mean Abs Drift (Before -> After): {mad_drift_before:.2f}% -> {mad_drift_after:.2f}% (Max Drift: {max_drift_before:.2f}%)",
        f"Est. Brokerage Fees: NGN {total_est_fees:,.2f} ({fee_drag_pct:.3f}% of portfolio) | Turnover: {turnover_pct:.2f}% (30D: {rolling_30d_turnover:.2f}%)",
        "-" * 65,
    ]

    all_tickets = sell_tickets + buy_tickets
    if all_tickets:
        subject = f"NGX Midnight Order Ticket ({len(all_tickets)} Orders) - {wat_now.strftime('%d %b %Y')}"
        lines.append("Place these Limit Orders on Bamboo at 12:00 AM WAT:")
        for t in sell_tickets:
            lines.append(
                f"[SELL] {t['Units']} {t['Ticker']} | Close: NGN {t['Ref_Close']:,.2f} -> Limit: NGN {t['Limit_NGN']:,.2f} (~NGN {t['Value_NGN']:,.2f}) | Drift {t['Drift']}"
            )
        for t in buy_tickets:
            lines.append(
                f"[BUY]  {t['Units']} {t['Ticker']} | Close: NGN {t['Ref_Close']:,.2f} -> Limit: NGN {t['Limit_NGN']:,.2f} (~NGN {t['Value_NGN']:,.2f}) | Drift {t['Drift']}"
            )

        pd.DataFrame([
            {
                "Timestamp": utc_now.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "Ticker": t["Ticker"],
                "Side": t["Action"],
                "Units": t["Units"],
                "Limit_Price_NGN": t["Limit_NGN"],
                "Total_Value_NGN": t["Value_NGN"],
                "Status": "EMAIL_TICKET_SENT",
                "Rationale": f"Close NGN {t['Ref_Close']:,.2f} | Drift {t['Drift']}",
            }
            for t in all_tickets
        ]).to_csv(ORDER_AUDIT_FILE, mode="a", header=not os.path.exists(ORDER_AUDIT_FILE), index=False)
    else:
        subject = f"NGX Portfolio Balanced (0 Orders) - {wat_now.strftime('%d %b %Y')}"
        lines.append("Portfolio Balanced: All 8 NGX equities are within +/-3.0% drift. No orders needed tonight.")

    body = "\n".join(lines)
    print(body)
    send_email(subject, body)


if __name__ == "__main__":
    run_nightly_rebalance_alert()
