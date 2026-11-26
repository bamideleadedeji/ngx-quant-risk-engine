import os, json, math, smtplib
from email.message import EmailMessage
from datetime import datetime, timezone, timedelta
import pandas as pd
from ngx_live_prices import fetch_official_ngx_closes

STATE_FILE = "ngx_portfolio_state.json"
ORDER_AUDIT_FILE = "ngx_trade_audit.csv"
PORTFOLIO_AUDIT_FILE = "ngx_portfolio_audit.csv"
GMAIL_USER = os.getenv("GMAIL_USER", "bamideleadedeji2000@gmail.com").strip()
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").strip().replace(" ", "")

DEFAULT_CS = [
    {"Ticker": "ZENITHBANK", "Company": "Zenith Bank Plc", "Units": 111.0, "Avg_Cost": 105.57, "Live_Price": 102.00, "Target_Weight_Pct": 25.0},
    {"Ticker": "OKOMUOIL", "Company": "Okomu Oil Palm Plc", "Units": 9.0, "Avg_Cost": 1039.72, "Live_Price": 1137.10, "Target_Weight_Pct": 25.0},
    {"Ticker": "TRANSCOHOT", "Company": "Transcorp Hotels Plc", "Units": 32.0, "Avg_Cost": 272.29, "Live_Price": 290.50, "Target_Weight_Pct": 22.0},
    {"Ticker": "MTNN", "Company": "MTN Nigeria Comm. Plc", "Units": 8.0, "Avg_Cost": 815.49, "Live_Price": 796.50, "Target_Weight_Pct": 18.0},
    {"Ticker": "UNILEVER", "Company": "Unilever Nigeria Plc", "Units": 33.0, "Avg_Cost": 103.61, "Live_Price": 101.00, "Target_Weight_Pct": 10.0},
]

MAX_TRIM_PCT = 15.0
BUY_BUF = 1.25
SELL_BUF = 1.00
MIN_FLOOR = 100.0
FEE_RATE = 0.0155


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        df = pd.DataFrame(d.get("holdings", DEFAULT_CS))
        cash = float(d.get("free_cash_ngn", 267.64))
        vdf = pd.DataFrame(d.get("apex_legacy_vault_readonly", []))
        lim = float(d.get("max_concentration_trim_pct", MAX_TRIM_PCT))
        return df, cash, vdf, lim
    return pd.DataFrame(DEFAULT_CS), 267.64, pd.DataFrame(), MAX_TRIM_PCT


def rolling_30d(cur):
    if os.path.exists(PORTFOLIO_AUDIT_FILE):
        try:
            h = pd.read_csv(PORTFOLIO_AUDIT_FILE)
            if "Cycle_Turnover_Pct" in h.columns and not h.empty:
                return float(h["Cycle_Turnover_Pct"].tail(29).sum() + cur)
        except Exception:
            pass
    return cur


def send_email(subject, body):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("GMAIL credentials missing; skipping email dispatch.")
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"NGX Quant Risk Desk <{GMAIL_USER}>"
    msg["To"] = GMAIL_USER
    msg.set_content(body)
    with smtplib.SMTP_SSL("://gmail.com", 465, timeout=15) as s:
        s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        s.send_message(msg)
    print(f"Email dispatched -> {subject}")


def run_nightly_rebalance_alert():
    utc_now = datetime.now(timezone.utc)
    wat_now = utc_now + timedelta(hours=1)
    df, cash, vdf, trim_lim = load_state()

    tickers = sorted(set(df["Ticker"].tolist() + (vdf["Ticker"].tolist() if not vdf.empty else [])))
    res = fetch_official_ngx_closes(tickers)
    closes = res[0] if isinstance(res, tuple) else res
    matched = sum(1 for t in tickers if t in closes)
    feed = f"LIVE NGX MARKET FEED ({matched}/{len(tickers)} official NSENG closes)"

    df["Close_NGN"] = df.apply(lambda r: float(closes.get(r["Ticker"], r["Live_Price"])), axis=1)
    df["Cost_Basis"] = df["Units"] * df["Avg_Cost"]
    df["Market_Value"] = df["Units"] * df["Close_NGN"]
    eq_tot = float(df["Market_Value"].sum())
    cs_pnl = eq_tot - float(df["Cost_Basis"].sum())
    cs_tot = eq_tot + cash

    v_tot = 0.0
    if not vdf.empty:
        v_tot = float((vdf["Units"] * vdf["Ticker"].map(lambda t: float(closes.get(t, 0.0)))).sum())

    df["Act_W"] = (df["Market_Value"] / cs_tot * 100.0) if cs_tot > 0 else 0.0
    df["Drift"] = df["Act_W"] - df["Target_Weight_Pct"]
    max_d = float(df["Drift"].abs().max()) if not df.empty else 0.0
    mad_b = float(df["Drift"].abs().mean()) if not df.empty else 0.0

    sells, buys = [], []
    w_cash = cash
    proj = dict(zip(df["Ticker"], df["Market_Value"]))

    for _, r in df.sort_values("Drift", ascending=False).iterrows():
        if r["Drift"] >= trim_lim and r["Units"] >= 2:
            lpx = round(r["Close_NGN"] * (1.0 - SELL_BUF / 100.0), 2)
            u = min(int(r["Units"]) - 1, math.floor(((r["Drift"] / 100.0) * cs_tot) / max(lpx, 0.01)))
            val = round(u * lpx, 2)
            if u >= 1 and val >= MIN_FLOOR:
                fee = round(val * FEE_RATE, 2)
                w_cash += (val - fee)
                proj[r["Ticker"]] -= val
                sells.append({"Action": "SELL", "Ticker": r["Ticker"], "Units": u, "Ref_Close": r["Close_NGN"], "Limit_NGN": lpx, "Value_NGN": val, "Fee_NGN": fee, "Drift": f"{r['Drift']:+.2f}%"})

    if w_cash >= MIN_FLOOR:
        for _, r in df.sort_values("Drift", ascending=True).iterrows():
            if r["Drift"] < -0.5 and w_cash >= MIN_FLOOR:
                lpx = round(r["Close_NGN"] * (1.0 + BUY_BUF / 100.0), 2)
                shortfall = max(0.0, ((r['Target_Weight_Pct'] / 100.0) * cs_tot) - proj[r['Ticker']])
                u = math.floor(min(w_cash / (1.0 + FEE_RATE), shortfall) / max(lpx, 0.01))
                val = round(u * lpx, 2)
                fee = round(val * FEE_RATE, 2)
                if u >= 1 and val >= MIN_FLOOR and (val + fee) <= w_cash:
                    w_cash -= (val + fee)
                    proj[r["Ticker"]] += val
                    buys.append({"Action": "BUY", "Ticker": r["Ticker"], "Units": u, "Ref_Close": r["Close_NGN"], "Limit_NGN": lpx, "Value_NGN": val, "Fee_NGN": fee, "Drift": f"{r['Drift']:+.2f}%"})

    fees = round(sum(t["Fee_NGN"] for t in sells + buys), 2)
    turn = (sum(t["Value_NGN"] for t in sells + buys) / cs_tot * 100.0) if cs_tot > 0 else 0.0
    post_c = round(w_cash, 2)
    mad_a = float(sum(abs(((proj[r["Ticker"]] / cs_tot * 100.0) if cs_tot > 0 else 0.0) - r["Target_Weight_Pct"]) for _, r in df.iterrows()) / len(df))
    r30 = rolling_30d(turn)
    fdrag = (fees / cs_tot * 100.0) if cs_tot > 0 else 0.0

    pd.DataFrame([{"Timestamp_UTC": utc_now.strftime("%Y-%m-%d %H:%M:%S"), "Timestamp_WAT": wat_now.strftime("%Y-%m-%d %H:%M:%S"), "Price_Feed_Status": feed, "Total_Portfolio_NGN": round(cs_tot, 2), "Equities_Value_NGN": round(eq_tot, 2), "Pre_Rebalance_Cash_NGN": round(cash, 2), "Post_Rebalance_Cash_NGN": post_c, "Max_Drift_Before_Pct": round(max_d, 2), "Mean_Abs_Drift_Before_Pct": round(mad_b, 2), "Projected_Mean_Abs_Drift_After_Pct": round(mad_a, 2), "Est_Brokerage_Fees_NGN": fees, "Fee_Drag_Pct": round(fdrag, 3), "Cycle_Turnover_Pct": round(turn, 2), "Rolling_30D_Turnover_Pct": round(r30, 2), "Orders_Generated": len(sells) + len(buys)}]).to_csv(PORTFOLIO_AUDIT_FILE, mode="a", header=not os.path.exists(PORTFOLIO_AUDIT_FILE), index=False)

    lines = [
        "NGX MIDNIGHT CARDINALSTONE (0138062119) CASH-DEPLOYMENT & RISK REPORT",
        f"Timestamp: {wat_now.strftime('%Y-%m-%d %I:%M %p WAT')}",
        f"Price Feed: {feed}",
        f"CardinalStone Active: NGN {cs_tot:,.2f} (Equities: NGN {eq_tot:,.2f} | Cash: NGN {cash:,.2f} | Return: NGN {cs_pnl:+,.2f})",
        f"Apex Legacy Vault (Read-Only): NGN {v_tot:,.2f} | Combined NGX Net Worth: NGN {cs_tot + v_tot:,.2f}",
        f"Drift & Guard: Max Drift {max_d:.2f}% (Trim Limit +/-{trim_lim:.0f}%) | MAD: {mad_b:.2f}% -> {mad_a:.2f}%",
        f"Est. NGX Fees: NGN {fees:,.2f} ({fdrag:.3f}%) | Turnover: {turn:.2f}% (30D: {r30:.2f}%)",
        "-" * 65,
    ]

    tickets = sells + buys
    if tickets:
        subject = f"CardinalStone Order Ticket ({len(tickets)} Orders) - {wat_now.strftime('%d %b %Y')}"
        lines.append("Executable Limit Orders on CardinalStone (0138062119):")
        for t in sells:
            lines.append(f"[TRIM SELL] {t['Units']} {t['Ticker']} | Close: NGN {t['Ref_Close']:,.2f} -> Limit: NGN {t['Limit_NGN']:,.2f} (~NGN {t['Value_NGN']:,.2f}) | {t['Drift']}")
        for t in buys:
            lines.append(f"[CASH BUY]  {t['Units']} {t['Ticker']} | Close: NGN {t['Ref_Close']:,.2f} -> Limit: NGN {t['Limit_NGN']:,.2f} (~NGN {t['Value_NGN']:,.2f}) | {t['Drift']}")
        pd.DataFrame([{"Timestamp": utc_now.strftime("%Y-%m-%d %H:%M:%S UTC"), "Ticker": t["Ticker"], "Side": t["Action"], "Units": t["Units"], "Limit_Price_NGN": t["Limit_NGN"], "Total_Value_NGN": t["Value_NGN"], "Status": "EMAIL_TICKET_SENT", "Rationale": f"Close NGN {t['Ref_Close']:,.2f} | Drift {t['Drift']}"} for t in tickets]).to_csv(ORDER_AUDIT_FILE, mode="a", header=not os.path.exists(ORDER_AUDIT_FILE), index=False)
    else:
        subject = f"CardinalStone Hold Cash (0 Orders) - {wat_now.strftime('%d %b %Y')}"
        lines.append(f"HOLD CASH (0 Orders): Cash NGN {cash:,.2f} cannot buy 1+ underweight share above NGN {MIN_FLOOR:,.2f} floor; all 5 positions within +/-{trim_lim:.0f}%.")

    body = "\n".join(lines)
    print(body)
    send_email(subject, body)


if __name__ == "__main__":
    run_nightly_rebalance_alert()
