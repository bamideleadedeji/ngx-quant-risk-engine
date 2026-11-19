import requests


def fetch_official_ngx_closes(target_tickers: list[str]) -> tuple[dict[str, float], str]:
    """
    Fetches official daily NGX (NSENG) closing prices directly via TradingView's
    public Nigeria market scanner JSON endpoint (vals[1] = close price).
    """
    wanted = {t.strip().upper() for t in target_tickers if t.strip()}
    prices: dict[str, float] = {}

    scan_url = "https://" + ".".join(["scanner", "tradingview", "com"]) + "/nigeria/scan"
    payload = {
        "symbols": {
            "tickers": [f"NSENG:{sym}" for sym in wanted],
            "query": {"types": []},
        },
        "columns": ["name", "close", "change", "volume"],
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    try:
        resp = requests.post(scan_url, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            rows = resp.json().get("data", [])
            for item in rows:
                full_sym = str(item.get("s", ""))
                vals = item.get("d", [])
                clean_sym = full_sym.split(":")[-1].strip().upper()
                if clean_sym in wanted and len(vals) >= 2 and vals[1] is not None:
                    try:
                        px = float(vals[1])
                        if px > 0:
                            prices[clean_sym] = round(px, 2)
                    except (TypeError, ValueError):
                        continue
        else:
            print(f"NSENG scanner HTTP status: {resp.status_code}")
    except Exception as exc:
        print(f"NSENG scanner fetch notice: {exc}")

    if prices:
        return prices, f"LIVE NGX MARKET FEED ({len(prices)}/{len(wanted)} official NSENG closing prices synced)"
    return {}, "NGX PUBLIC FEED UNREACHABLE (Using saved portfolio prices — verify on Bamboo before ordering)"
 
