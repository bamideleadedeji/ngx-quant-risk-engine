import re
import requests
from bs4 import BeautifulSoup


def fetch_official_ngx_closes(target_tickers: list[str]) -> tuple[dict[str, float], str]:
    """
    Fetches official daily NGX closing prices from public Nigerian Exchange data feeds
    (AFX Kwayisi NGX & African Markets NGX).
    AFX table layout: Ticker (0) | Name (1) | Volume (2) | Price (3) | Change (4).
    """
    wanted = {t.strip().upper() for t in target_tickers if t.strip()}
    prices: dict[str, float] = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    afx_url = "https://" + "afx.kwayisi.org" + "/ngx/"
    try:
        resp = requests.get(afx_url, headers=headers, timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for row in soup.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) >= 4:
                    sym = cells[0].strip().upper()
                    if sym in wanted:
                        raw_price = re.sub(r"[^\d.]", "", cells[3])
                        if raw_price and raw_price.count(".") <= 1:
                            try:
                                px = float(raw_price)
                                if px > 0:
                                    prices[sym] = round(px, 2)
                            except ValueError:
                                pass
    except Exception as exc:
        print(f"AFX NGX fetch notice: {exc}")

    missing = wanted - set(prices.keys())
    if missing:
        am_url = "https://" + "://african-markets.com" + "/en/stock-markets/ngse/listed-companies"
        try:
            resp = requests.get(am_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for row in soup.find_all("tr"):
                    cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
                    if len(cells) >= 3:
                        row_text_upper = " ".join(cells[:2]).upper()
                        for sym in list(missing):
                            if re.search(rf"\b{re.escape(sym)}\b", row_text_upper):
                                for cell_val in cells[2:5]:
                                    cleaned = re.sub(r"[^\d.]", "", cell_val)
                                    if cleaned and cleaned.count(".") <= 1 and "." in cleaned:
                                        try:
                                            px = float(cleaned)
                                            if px > 0:
                                                prices[sym] = round(px, 2)
                                                missing.discard(sym)
                                                break
                                        except ValueError:
                                            continue
        except Exception as exc:
            print(f"African Markets NGX fetch notice: {exc}")

    if prices:
        return prices, f"LIVE NGX MARKET FEED ({len(prices)}/{len(wanted)} official closing prices synced)"
    return {}, "NGX PUBLIC FEED UNREACHABLE (Using saved portfolio prices — verify on Bamboo before ordering)"
 
