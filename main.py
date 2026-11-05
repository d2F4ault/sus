import asyncio
import json
import logging
import os
import random
import string
import sys
import traceback # Import traceback for detailed error logging

import nodriver as uc
from telethon import TelegramClient
from telethon.tl.functions.channels import (
    CheckUsernameRequest,
    CreateChannelRequest,
    UpdateUsernameRequest,
)
from telethon.tl.types import InputPeerChannel

# --- CONFIGURATION ---
logging.basicConfig(
    level=logging.DEBUG, # Set to DEBUG for maximum verbosity
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)] # Ensure logs go to console
)
logger = logging.getLogger(__name__)

# --- GLOBAL VARIABLES ---
API_ID = int(os.environ.get("TELEGRAM_API_ID", 0))
API_HASH = os.environ.get("TELEGRAM_API_HASH")
PHONE = os.environ.get("TELEGRAM_PHONE")
SESSION_STRING = os.environ.get("TELEGRAM_SESSION")
CHROME_PATH = os.environ.get("CHROME_PATH") # Get path from workflow

TARGET_URL = "https://flowfame.com/free-telegram-members"
MAX_CYCLES = 30

def generate_random_username():
    return "ch_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))

async def process_flowfame_with_nodriver(link):
    logger.info(f"=== STARTING BROWSER PROCESS FOR: {link} ===")
    browser = None
    try:
        # --- Browser Configuration with Debugging ---
        browser_args = ["--no-sandbox", "--disable-dev-shm-usage", "--headless=new"]
        logger.info(f"Starting nodriver with arguments: {browser_args}")
        if CHROME_PATH:
            logger.info(f"Using Chrome executable from: {CHROME_PATH}")
            browser = await uc.start(
                headless=True,
                browser_args=browser_args,
                browser_executable_path=CHROME_PATH
            )
        else:
            logger.warning("CHROME_PATH not set. Relying on nodriver auto-detection.")
            browser = await uc.start(
                headless=True,
                browser_args=browser_args
            )
        logger.info("Browser started successfully.")

        # --- Navigate to URL with detailed logging ---
        logger.info(f"Navigating to {TARGET_URL}...")
        tab = await browser.get(TARGET_URL)
        logger.info("Page loaded. Waiting 5 seconds for dynamic content...")
        await tab.sleep(5)

        # --- CAPTCHA SOLVING LOGIC with enhanced logging ---
        logger.info("Searching for Cloudflare Turnstile iframe...")
        try:
            iframe = await tab.select("iframe[src*='challenges.cloudflare.com']", timeout=15)
            if iframe:
                logger.info("Turnstile iframe found. Attempting to click...")
                await iframe.mouse_click()
                logger.info("Click executed. Waiting 7 seconds for verification...")
                await tab.sleep(7)
            else:
                logger.warning("Turnstile iframe not found. It might be invisible or the page has changed.")
        except Exception as e:
            logger.error(f"Error during CAPTCHA interaction: {e}")
            logger.error(traceback.format_exc())

        # --- FORM SUBMISSION with detailed logging ---
        logger.info("Searching for the Telegram link input field...")
        link_input = await tab.select("input[placeholder*='t.me']", timeout=10)
        if not link_input:
            logger.critical("Fatal: Could not find the Telegram link input field. Aborting.")
            return
        logger.info("Input field found. Typing the link...")
        await link_input.send_keys(link)
        await tab.sleep(1)

        logger.info("Searching for the submit button...")
        submit_btn = await tab.select("button[type='submit']", timeout=10)
        if not submit_btn:
            logger.critical("Fatal: Could not find the submit button. Aborting.")
            return
        logger.info("Submit button found. Clicking...")
        await submit_btn.click()
        logger.info("Form submitted. Waiting for confirmation...")

        # --- WAIT FOR SUCCESS CONFIRMATION with detailed logging ---
        for i in range(24):
            await tab.sleep(5)
            page_text = await tab.evaluate("document.body.innerText")
            logger.debug(f"Polling for success ({i+1}/24)...")
            if "on the way" in page_text or "free claims remaining" in page_text:
                logger.info("🎉 Members claimed successfully! Confirmation message found.")
                return
        logger.warning("Timeout reached. Confirmation message not found.")

    except Exception as e:
        logger.critical(f"An unexpected error occurred in process_flowfame: {e}")
        logger.critical(traceback.format_exc()) # Print the full stack trace
    finally:
        if browser:
            logger.info("Closing browser.")
            await browser.stop()

async def main():
    logger.info("========== SCRIPT STARTED ==========")
    
    # --- Verify all required secrets are present ---
    if not all([API_ID, API_HASH, PHONE, SESSION_STRING]):
        logger.critical("One or more Telegram secrets are missing. Please check repository secrets.")
        sys.exit(1)

    # --- READ STATE with error handling ---
    try:
        with open("state.json", "r") as f:
            state = json.load(f)
        logger.info(f"State loaded: {state}")
    except FileNotFoundError:
        logger.error("state.json not found. This might be the first run or a setup issue.")
        sys.exit(1)

    current_cycle = state["cycle"]
    if current_cycle >= MAX_CYCLES:
        logger.info(f"🏁 Reached {MAX_CYCLES} cycles. Automation complete. Exiting.")
        sys.exit(0)

    logger.info(f"--- 🔄 Starting Cycle {current_cycle + 1}/{MAX_CYCLES} ---")

    # --- INITIALIZE TELEGRAM CLIENT ---
    logger.info("Initializing Telegram client...")
    client = TelegramClient(SESSION_STRING, API_ID, API_HASH)
    try:
        await client.start()
        logger.info("Telegram client connected successfully.")
    except Exception as e:
        logger.critical(f"Failed to connect to Telegram: {e}")
        logger.critical(traceback.format_exc())
        sys.exit(1)

    # --- EXECUTE CYCLE LOGIC with detailed logging ---
    try:
        if current_cycle == 0:
            logger.info("Creating new Telegram channel...")
            result = await client(CreateChannelRequest(
                title="Auto Claim Channel", about="Temporary channel for claims", broadcast=True
            ))
            channel = result.chats[0]
            state["channel_id"] = channel.id
            state["access_hash"] = channel.access_hash
            logger.info(f"Channel created with ID: {channel.id}")

            current_username = generate_random_username()
            logger.info(f"Generated username: {current_username}")
            peer = InputPeerChannel(channel.id, channel.access_hash)
            if await client(CheckUsernameRequest(peer, current_username)):
                await client(UpdateUsernameRequest(peer, current_username))
                state["current_username"] = current_username
                logger.info(f"Channel made public: https://t.me/{current_username}")
            else:
                logger.error("Failed to set initial username. Aborting cycle.")
                await client.disconnect()
                sys.exit(1)
        else:
            logger.info("Rotating channel username...")
            peer = InputPeerChannel(state["channel_id"], state["access_hash"])
            new_username = generate_random_username()
            logger.info(f"New username: {new_username}")
            if await client(CheckUsernameRequest(peer, new_username)):
                await client(UpdateUsernameRequest(peer, new_username))
                state["current_username"] = new_username
                logger.info(f"Username updated successfully: https://t.me/{new_username}")
            else:
                logger.error("Failed to update username (likely FloodWait). Aborting cycle.")
                await client.disconnect()
                sys.exit(1)
    except Exception as e:
        logger.critical(f"FATAL Telegram error: {e}")
        logger.critical(traceback.format_exc())
        await client.disconnect()
        sys.exit(1)
    finally:
        if client.is_connected():
            logger.info("Disconnecting Telegram client.")
            await client.disconnect()

    # --- CLAIM MEMBERS ---
    link_to_claim = f"https://t.me/{state['current_username']}"
    logger.info(f"Proceeding to claim members for: {link_to_claim}")
    await process_flowfame_with_nodriver(link_to_claim)

    # --- UPDATE STATE ---
    state["cycle"] += 1
    with open("state.json", "w") as f:
        json.dump(state, f, indent=2)
    logger.info(f"✅ Cycle {current_cycle + 1} complete. State saved. Exiting.")

if __name__ == "__main__":
    asyncio.run(main())
