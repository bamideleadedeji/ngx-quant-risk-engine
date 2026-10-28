"""
===============================================================================
NGX Quantitative Engine — Headless Browser Execution Bridge (Pathway B)
File: src/bamboo_bridge.py
===============================================================================
Description:
    Automates 100% hands-off order execution on Bamboo using Playwright.
    Logs into Bamboo web interface, navigates to target NGX equities,
    inputs share lots, and asserts order completion receipts.
===============================================================================
"""

from datetime import datetime
import json
import os
import sys
import time
from typing import Any, Dict, Optional
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

# Target Bamboo Endpoints
BAMBOO_LOGIN_URL = "https://app.investbamboo.com/login"
SESSION_FILE = "bamboo_session.json"


def execute_bamboo_trade_headless(order: Dict[str, Any]) -> Dict[str, Any]:
  """Launches a headless Chromium instance, authenticates with Bamboo, uses in-app

  search to navigate to target NGX equity, and verifies order completion.
  """
  email = os.environ.get("BAMBOO_EMAIL")
  password = os.environ.get("BAMBOO_PASSWORD")
  pin = os.environ.get("BAMBOO_PIN", "1234")

  if not email or not password:
    try:
      import streamlit as st

      email = email or st.secrets.get("BAMBOO_EMAIL")
      password = password or st.secrets.get("BAMBOO_PASSWORD")
      pin = st.secrets.get("BAMBOO_PIN", pin)
    except Exception:
      pass

  if not email or not password:
    print(
        "❌ Execution Bridge Error: BAMBOO_EMAIL or BAMBOO_PASSWORD credentials"
        " not found."
    )
    return {"status": "FAILED", "reason": "MISSING_CREDENTIALS"}

  symbol = (
      order.get("symbol", "").replace(".LG", "").replace(".NS", "").upper()
  )
  units = int(order.get("units", 0))
  target_price = float(order.get("unit_price_ngn", 0.0))

  if units <= 0 or not symbol:
    print(f"⚠️ Invalid Order Payload: Symbol='{symbol}', Units={units}")
    return {"status": "SKIPPED", "reason": "INVALID_ORDER_PARAMS"}

  print(
      f"🚀 Initializing Headless Execution Bridge for {symbol} ({units} shares"
      f" @ ₦{target_price:,.2f})..."
  )

  with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
        ],
    )

    if os.path.exists(SESSION_FILE):
      print("🔑 Found existing session state. Loading cookies...")
      context = browser.new_context(
          storage_state=SESSION_FILE,
          user_agent=(
              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
              " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
          ),
      )
    else:
      context = browser.new_context(
          user_agent=(
              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
              " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
          )
      )

    page = context.new_page()

    try:
      # Step 1: Authenticate
      page.goto(BAMBOO_LOGIN_URL, timeout=45000, wait_until="networkidle")
      page.wait_for_timeout(3000)

      email_input = page.locator(
          "input[type='email'], input[name='email']"
      ).first
      if email_input.is_visible():
        print("🔑 Authenticating with Bamboo Web Interface...")
        email_input.fill(email)
        page.fill("input[type='password'], input[name='password']", password)

        login_btn = page.locator(
            "button[type='submit'], button:has-text('Log In'),"
            " button:has-text('Sign In')"
        ).first
        login_btn.click()
        page.wait_for_timeout(4000)

        # Step 2: Security PIN Check
        pin_inputs = page.locator("input[type='password'], input[type='tel']")
        if pin_inputs.count() >= 4:
          print("🔒 Entering Security PIN...")
          for idx, char in enumerate(str(pin)):
            if idx < pin_inputs.count():
              pin_inputs.nth(idx).fill(char)
          page.wait_for_timeout(3000)

        context.storage_state(path=SESSION_FILE)

      # Step 3: In-App Search with Explicit Wait
      print(f"🔍 Searching for NGX Equity: {symbol}...")

      page.goto(
          f"https://app.investbamboo.com/app/trade?search={symbol}",
          timeout=45000,
          wait_until="networkidle",
      )
      page.wait_for_timeout(3000)

      buy_btn = page.locator(
          "button:has-text('Buy'), tab:has-text('Buy')"
      ).first
      if not buy_btn.is_visible():
        stock_item = page.locator(f"text='{symbol}'").first
        if stock_item.is_visible():
          stock_item.click()
          page.wait_for_timeout(2000)

      # Step 4: Fill Share Quantity & Submit
      print(f"⚡ Setting order quantity: {units} shares of {symbol}...")

      buy_btn = page.locator("button:has-text('Buy')").first
      if buy_btn.is_visible():
        buy_btn.click()
        page.wait_for_timeout(1500)

      qty_input = page.locator(
          "input[name='quantity'], input[name='shares'],"
          " input[placeholder='0']"
      ).first
      if qty_input.is_visible():
        qty_input.fill(str(units))
      else:
        page.keyboard.type(str(units))

      page.wait_for_timeout(1500)

      review_btn = page.locator(
          "button:has-text('Review Order'), button:has-text('Review')"
      ).first
      if review_btn.is_visible():
        review_btn.click()
        page.wait_for_timeout(2000)

      # EXPANDED CONFIRM BUTTON SELECTORS FOR BAMBOO
      confirm_btn = page.locator(
          "button:has-text('Place Order'), button:has-text('Submit Order'),"
          " button:has-text('Confirm Buy'), button:has-text('Confirm'),"
          " button:has-text('Buy Now'), button[type='submit']"
      ).first

      if not confirm_btn.is_visible():
        page.screenshot(path=f"bamboo_timeout_{symbol}.png")
        browser.close()
        return {"status": "FAILED", "reason": "CONFIRM_BUTTON_NOT_FOUND"}

      confirm_btn.click()

      receipt = page.wait_for_selector(
          ".order-success, .receipt-modal, text='Order Submitted',"
          " text='Success'",
          timeout=15000,
      )
      if receipt:
        context.storage_state(path=SESSION_FILE)
        browser.close()
        return {
            "status": "FILLED",
            "symbol": symbol,
            "units": units,
            "target_price": target_price,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
      else:
        page.screenshot(path=f"bamboo_timeout_{symbol}.png")
        browser.close()
        return {"status": "FAILED", "reason": "RECEIPT_CONFIRMATION_TIMEOUT"}

    except PlaywrightTimeoutError as te:
      page.screenshot(path=f"bamboo_timeout_{symbol}.png")
      browser.close()
      return {"status": "FAILED", "reason": f"TIMEOUT_ERROR: {str(te)}"}
    except Exception as err:
      page.screenshot(path=f"bamboo_error_{symbol}.png")
      browser.close()
      return {"status": "FAILED", "reason": str(err)}
