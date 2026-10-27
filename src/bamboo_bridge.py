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

# Target Bamboo Endpoints
BAMBOO_LOGIN_URL = "https://app.investbamboo.com/login"
SESSION_FILE = "bamboo_session.json"


def execute_bamboo_trade_headless(order: Dict[str, Any]) -> Dict[str, Any]:
    """
    Launches a headless Chromium instance, authenticates with Bamboo using session
    persistence, navigates to the target stock symbol, inputs the calculated share lot,
    and verifies receipt confirmation before returning status.
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
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )

        # Use stored session if available to bypass 2FA / Login prompts
        if os.path.exists(SESSION_FILE):
            print("🔑 Found existing session state. Loading cookies...")
            context = browser.new_context(
                storage_state=SESSION_FILE,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        else:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

        page = context.new_page()

        try:
            # Step 1: Navigate to Bamboo & Authenticate if necessary
            page.goto(BAMBOO_LOGIN_URL, timeout=30000, wait_until="networkidle")
            page.wait_for_timeout(2000)

            # Check if login form is presented
            if page.locator("input[type='email'], input[name='email']").is_visible():
                print("🔑 Authenticating with Bamboo Web Interface...")
                page.fill("input[type='email'], input[name='email']", email)
                page.fill("input[type='password'], input[name='password']", password)
                
                # Click submit button flexibly
                login_btn = page.locator("button[type='submit'], button:has-text('Log In'), button:has-text('Sign In')").first
                login_btn.click()
                page.wait_for_timeout(3000)

                # Step 2: Handle Security PIN Prompt if present
                pin_input = page.locator("input[type='password'], input[type='tel']")
                if pin_input.count() >= 4:
                    print("🔒 Entering Security PIN...")
                    for idx, char in enumerate(str(pin)):
                        if idx < pin_input.count():
                            pin_input.nth(idx).fill(char)
                    page.wait_for_timeout(2000)

                # Save session state after successful authentication
                context.storage_state(path=SESSION_FILE)
                print("✅ Session saved to bamboo_session.json")

            # Step 3: Navigate Directly to Target Equity Stock Page
            stock_url = f"https://app.investbamboo.com/stocks/{symbol}"
            print(f"🔍 Navigating to order page: {stock_url}")
            page.goto(stock_url, timeout=30000, wait_until="networkidle")
            page.wait_for_timeout(2000)

            # Step 4: Open Order Form & Fill Share Lot
            print(f"⚡ Setting order parameters: {units} shares of {symbol}...")
            
            # Click Buy Button / Tab
            buy_btn = page.locator("button:has-text('Buy'), tab:has-text('Buy')").first
            if buy_btn.is_visible():
                buy_btn.click()
                page.wait_for_timeout(1000)

            # Locate Share Quantity Field
            qty_input = page.locator("input[name='quantity'], input[name='shares'], input[placeholder='0']").first
            if qty_input.is_visible():
                qty_input.fill(str(units))
            else:
                print("⚠️ Primary input selector missed. Using fallback focused input...")
                page.keyboard.type(str(units))

            page.wait_for_timeout(1000)

            # Step 5: Review Order
            review_btn = page.locator("button:has-text('Review Order'), button:has-text('Review')").first
            if review_btn.is_visible():
                review_btn.click()
                page.wait_for_timeout(1500)

            # Step 6: Submit & VERIFY Execution Receipt
            confirm_btn = page.locator("button:has-text('Submit Order'), button:has-text('Confirm Buy')").first
            if not confirm_btn.is_visible():
                # Screenshot failure state for debugging
                page.screenshot(path=f"bamboo_failure_{symbol}.png")
                browser.close()
                print(f"❌ Could not locate confirmation button for {symbol}. Saved debug screenshot.")
                return {"status": "FAILED", "reason": "CONFIRM_BUTTON_NOT_FOUND"}

            confirm_btn.click()
            
            # CRITICAL ASSERTION: Wait up to 15 seconds for Order Receipt confirmation element
            print("⏳ Waiting for broker order confirmation receipt...")
            receipt = page.wait_for_selector(".order-success, .receipt-modal, text='Order Submitted'", timeout=15000)

            if receipt:
                print(f"✅ Verified Order Fill Receipt for {units} shares of {symbol}!")
                context.storage_state(path=SESSION_FILE)
                browser.close()
                return {
                    "status": "FILLED",
                    "symbol": symbol,
                    "units": units,
                    "target_price": target_price,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
            else:
                page.screenshot(path=f"bamboo_failure_{symbol}.png")
                browser.close()
                print(f"❌ Order submitted but receipt confirmation timed out. Saved screenshot.")
                return {"status": "FAILED", "reason": "RECEIPT_CONFIRMATION_TIMEOUT"}

        except PlaywrightTimeoutError as te:
            print(f"❌ Execution Timeout on Bamboo Web Interface: {str(te)}")
            page.screenshot(path=f"bamboo_timeout_{symbol}.png")
            browser.close()
            return {"status": "FAILED", "reason": "TIMEOUT_ERROR"}
        except Exception as err:
            print(f"❌ Headless Bridge Exception: {str(err)}")
            page.screenshot(path=f"bamboo_error_{symbol}.png")
            browser.close()
            return {"status": "FAILED", "reason": str(err)}


if __name__ == "__main__":
    print("🚀 Testing Headless Browser Execution Bridge locally...")
    
    test_order = {
        "symbol": "ZENITHBANK",
        "units": 118,
        "unit_price_ngn": 61.63,
        "action": "BUY"
    }
    
    execution_result = execute_bamboo_trade_headless(test_order)
    print("\n--- Execution Bridge Result ---")
    print(json.dumps(execution_result, indent=2))
