import re
import requests
from bs4 import BeautifulSoup

# Map canonical NGX tickers to Investing.com Nigeria company name patterns
INVESTING_NAME_MAP = {
    "BUAFOODS": ["BUA FOODS"],
    "SEPLAT": ["SEPLAT ENERGY", "SEPLAT PETROLEUM"],
    "GTCO": ["GUARANTY TRUST", "GTCO"],
    "MTNN": ["MTN NIGERIA"],
    "ZENITHBANK": ["ZENITH BANK"],
    "OKOMUOIL": ["OKOMU OIL"],
    "UNILEVER": ["UNILEVER NIGERIA"],
    "TRANSCOHOT": ["TRANSCORP HOTELS"],
}


def _build_url(scheme: str, host: str, path: str) -> str:
    return scheme + "://" + host + path


def fetch_official_ngx_closes(target_tickers: list[str]) -> tuple[dict[str, float], str]:
    """
    Fetches official daily NGX closing prices from Investing.com Nigeria (://investing.com)
    with NGX Group official price list fallback.
    """
    wanted = {t.strip().upper() for t in target_tickers if t.strip()}
    prices: dict[str, float] = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # Source 1: Investing.com Nigeria Equities Table
    inv_url = _build_url("https", "://investing.com", "/equities/nigeria")
    try:
        resp = requests.get(inv_url, headers=headers, timeout=20)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for row in soup.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) >= 3:
                    row_label = " ".join(cells[:2]).upper()
                    for sym in list(wanted - set(prices.keys())):
                        aliases = INVESTING_NAME_MAP.get(sym, [sym])
                        if any(alias in row_label for alias in aliases):
                            for cell_val in cells[1:5]:
                                cleaned = re.sub(r"[^\d.]", "", cell_val)
                                if cleaned and cleaned.count(".") <= 1:
                                    try:
                                        px = float(cleaned)
                                        if px > 0:
                                            prices[sym] = round(px, 2)
                                            break
                                    except ValueError:
                                        continue
    except Exception as exc:
        print(f"Investing.com NGX fetch notice: {exc}")

    # Source 2: NGX Group Official Daily Equities Price List Fallback
    missing = wanted - set(prices.keys())
    if missing:
        ngx_url = _build_url("https", "ngxgroup.com", "/exchange/data/equities-price-list/")
        try:
            resp = requests.get(ngx_url, headers=headers, timeout=20)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for row in soup.find_all("tr"):
                    cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
                    if len(cells) >= 5:
                        sym = cells.strip().upper()
                        if sym in missing:
                            for cell_val in cells[2:6]:
                                cleaned = re.sub(r"[^\d.]", "", cell_val)
                                if cleaned and cleaned.count(".") <= 1:
                                    try:
                                        px = float(cleaned)
                                        if px > 0:
                                            prices[sym] = round(px, 2)
                                            missing.discard(sym)
                                            break
                                    except ValueError:
                                        continue
        except Exception as exc:
            print(f"NGX Group fetch notice: {exc}")

    if prices:
        return prices, f"LIVE NGX MARKET FEED ({len(prices)}/{len(wanted)} official closing prices synced via Investing/NGX)"
    return {}, "NGX PUBLIC FEED UNREACHABLE (Using saved portfolio prices — verify on Bamboo before ordering)"
 
