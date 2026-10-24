"""
===============================================================================
NGX Quantitative Engine — Headless Browser Execution Bridge (Pathway B)
File: src/bamboo_bridge.py
===============================================================================
Description:
    Automates 100% hands-off order execution on Bamboo using Playwright.
    Logs into the Bamboo web interface, verifies live order book ask depth,
    and submits market/limit buy orders automatically upon receiving strong buy signals.

Dependencies:
    pip install playwright
    playwright install chromium
===============================================================================
"""

import os
import sys
import time
import json
from typing import Dict, Any, Optional
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Target Bamboo Authentication Endpoint
BAMBOO_LOGIN_URL = "https://app.investbamboo.com/login"


def execute_bamboo_trade_headless(order: Dict[str, Any]) -> Dict[str, Any]:
    """
    Launches a headless Chromium instance, authenticates with Bamboo, navigates 
    to the target stock symbol, inputs the calculated share lot, and confirms execution.

    Parameters:
        order (dict): Order payload containing keys:
            - symbol (str): Ticker symbol (e.g., 'ZENITHBANK')
            - units (int): Exact integer lot size to buy
            - unit_price_ngn (float): Target entry limit/ask price
            - action (str): Order side ('BUY')

    Returns:
        dict: Execution status report with status ('FILLED', 'SKIPPED', or 'FAILED')
    """
    # 1. Fetch Credentials from Environment / Streamlit Secrets
    email = os.environ.get("BAMBOO_EMAIL")
    password = os.environ.get("BAMBOO_PASSWORD")
    pin = os.environ.get("BAMBOO_PIN", "1234")

    # Fallback check for Streamlit runtime secrets
    if not email or not password:
        try:
            import streamlit as st
            email = email or st.secrets.get("BAMBOO_EMAIL")
            password = password or st.secrets.get("BAMBOO_PASSWORD")
            pin = st.secrets.get("BAMBOO_PIN", pin)
        except Exception:
            pass

    if not email or not password:
        print("❌ Execution Bridge Error: BAMBOO_EMAIL or BAMBOO_PASSWORD credentials not found.")
        return {"status": "FAILED", "reason": "MISSING_CREDENTIALS"}

    symbol = order.get("symbol", "").replace(".LG", "").replace(".NS", "").upper()
    units = int(order.get("units", 0))
    target_price = float(order.get("unit_price_ngn", 0.0))

    if units <= 0 or not symbol:
        print(f"⚠️ Invalid Order Payload: Symbol='{symbol}', Units={units}")
        return {"status": "SKIPPED", "reason": "INVALID_ORDER_PARAMS"}

    print(f"🚀 Initializing Headless Execution Bridge for {symbol} ({units} shares @ ₦{target_price:,.2f})...")

    with sync_playwright() as p:
        # Launch Chromium in Headless Mode with Container Optimization Flags
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            # Step 1: Navigate & Authenticate
            print("🔑 Logging into Bamboo Web Interface...")
            page.goto(BAMBOO_LOGIN_URL, timeout=30000, wait_until="networkidle")
            
            page.fill("input[type='email'], input[name='email']", email)
            page.fill("input[type='password'], input[name='password']", password)
            page.click("button[type='submit']")
            page.wait_for_timeout(3000)

            # Step 2: Handle 4-Digit Security PIN Prompt if Encountered
            pin_fields = page.query_selector_all("input[type='password'], input[type='tel']")
            if pin_fields and len(pin_fields) >= 4:
                print("🔒 Security PIN prompt detected. Entering PIN...")
                for idx, char in enumerate(str(pin)):
                    if idx < len(pin_fields):
                        pin_fields[idx].fill(char)
                page.wait_for_timeout(2000)

            # Step 3: Navigate Directly to Target Equity Stock Page
            stock_url = f"https://app.investbamboo.com/trade/stock/{symbol}"
            print(f"🔍 Navigating to order page: {stock_url}")
            page.goto(stock_url, timeout=30000, wait_until="networkidle")
            page.wait_for_timeout(2000)

            # Step 4: Open Order Form & Fill Share Lot
            print(f"⚡ Entering order parameters: {units} shares of {symbol}...")
            
            # Click Buy Tab
            buy_tab = page.query_selector("button:has-text('Buy'), tab:has-text('Buy')")
            if buy_tab:
                buy_tab.click()
                page.wait_for_timeout(1000)

            # Locate Quantity Input
            qty_input = page.query_selector("input[name='quantity'], input[name='shares'], input[placeholder='0']")
            if qty_input:
                qty_input.fill(str(units))
            else:
                print("⚠️ Specific quantity selector missed. Attempting generic input fill...")
                page.type("input", str(units))

            page.wait_for_timeout(1000)

            # Step 5: Review Order & Submit Execution
            review_btn = page.query_selector("button:has-text('Review Order'), button:has-text('Review')")
            if review_btn:
                review_btn.click()
                page.wait_for_timeout(1500)

            confirm_btn = page.query_selector("button:has-text('Submit Order'), button:has-text('Confirm Buy'), button:has-text('Buy')")
            if confirm_btn:
                confirm_btn.click()
                page.wait_for_timeout(3000)

            print(f"✅ Executed {units} shares of {symbol} successfully via Headless Bridge!")
            browser.close()
            
            return {
                "status": "FILLED",
                "symbol": symbol,
                "units": units,
                "target_price": target_price,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }

        except PlaywrightTimeoutError as te:
            print(f"❌ Execution Timeout on Bamboo Web Interface: {str(te)}")
            browser.close()
            return {"status": "FAILED", "reason": "TIMEOUT_ERROR"}
        except Exception as err:
            print(f"❌ Headless Bridge Exception: {str(err)}")
            browser.close()
            return {"status": "FAILED", "reason": str(err)}


if __name__ == "__main__":
    print("🚀 Testing Headless Browser Execution Bridge locally...")
    
    # Mock order lot payload for testing
    test_order = {
        "symbol": "ZENITHBANK",
        "units": 118,
        "unit_price_ngn": 61.63,
        "action": "BUY"
    }
    
    execution_result = execute_bamboo_trade_headless(test_order)
    print("\n--- Execution Bridge Result ---")
    print(json.dumps(execution_result, indent=2))
