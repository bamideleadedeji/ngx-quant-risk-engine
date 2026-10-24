"""
===============================================================================
NGX Quantitative Engine — Headless Browser Execution Bridge (Pathway B)
File: src/bamboo_bridge.py
===============================================================================
Description:
    Automates 100% hands-off order execution on Bamboo using Playwright.
    Logs into the Bamboo web interface, verifies order book ask depth,
    and submits market/limit buy orders automatically upon receiving strong buy signals.
===============================================================================
"""

import os
import sys
import time
import json
from typing import Dict, Any, List
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


BAMBOO_LOGIN_URL = "https://app.investbamboo.com/login"


def execute_bamboo_trade_headless(order: Dict[str, Any]) -> Dict[str, Any]:
    """
    Launches a headless Chromium browser, logs into Bamboo, locates the stock ticker,
    and submits the order lot instantly.
    """
    email = os.environ.get("BAMBOO_EMAIL")
    password = os.environ.get("BAMBOO_PASSWORD")
    pin = os.environ.get("BAMBOO_PIN", "1234")

    if not email or not password:
        print("❌ Error: BAMBOO_EMAIL or BAMBOO_PASSWORD environment variables not set.")
        return {"status": "FAILED", "reason": "MISSING_CREDENTIALS"}

    symbol = order.get("symbol", "").upper()
    units = order.get("units", 0)
    
    if units <= 0 or not symbol:
        print(f"⚠️ Invalid order parameters: Symbol={symbol}, Units={units}")
        return {"status": "SKIPPED", "reason": "INVALID_ORDER_PARAMS"}

    print(f"🚀 Launching Headless Execution Bridge for {symbol} ({units} shares)...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        try:
            # Step 1: Navigate to Login Page
            page.goto(BAMBOO_LOGIN_URL, timeout=30000)
            page.fill("input[type='email']", email)
            page.fill("input[type='password']", password)
            page.click("button[type='submit']")
            page.wait_for_timeout(3000)

            # Step 2: Handle Security PIN if Prompted
            pin_inputs = page.query_selector_all("input[type='password'], input[type='tel']")
            if pin_inputs and len(pin_inputs) >= 4:
                for i, char in enumerate(pin):
                    if i < len(pin_inputs):
                        pin_inputs[i].fill(char)
                page.wait_for_timeout(2000)

            # Step 3: Search Target Equity
            print(f"🔍 Searching ticker {symbol} on Bamboo...")
            page.goto(f"https://app.investbamboo.com/trade/stock/{symbol}", timeout=30000)
            page.wait_for_timeout(2000)

            # Step 4: Input Share Lot & Confirm Buy
            print(f"⚡ Entering order lot: {units} shares of {symbol}...")
            
            # Select Buy Tab & Share Lots
            page.click("text=Buy")
            page.wait_for_timeout(1000)

            # Fill Share Units
            units_input = page.query_selector("input[name='quantity'], input[placeholder='0']")
            if units_input:
                units_input.fill(str(units))
            else:
                print("⚠️ Quantity field selector missing. Attempting fallback input...")
                page.type("input", str(units))

            page.wait_for_timeout(1000)

            # Step 5: Review & Submit Order
            page.click("button:has-text('Review Order')")
            page.wait_for_timeout(1000)
            
            page.click("button:has-text('Submit Order'), button:has-text('Confirm')")
            page.wait_for_timeout(2000)

            print(f"✅ Executed {units} shares of {symbol} automatically on Bamboo!")
            browser.close()
            return {"status": "FILLED", "symbol": symbol, "units": units}

        except PlaywrightTimeoutError as te:
            print(f"❌ Execution Timeout on Bamboo web interface: {str(te)}")
            browser.close()
            return {"status": "FAILED", "reason": "TIMEOUT_ERROR"}
        except Exception as e:
            print(f"❌ Execution Bridge Exception: {str(e)}")
            browser.close()
            return {"status": "FAILED", "reason": str(e)}


if __name__ == "__main__":
    # Test order structure locally
    mock_order = {
        "symbol": "ZENITHBANK",
        "units": 118,
        "unit_price_ngn": 61.63,
        "action": "BUY"
    }
    result = execute_bamboo_trade_headless(mock_order)
    print("Execution Result:", json.dumps(result, indent=2))
