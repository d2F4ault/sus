import asyncio
import json
import logging
import os
import random
import shutil
import string
import sys
import traceback

import nodriver as uc
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import (
    CheckUsernameRequest,
    CreateChannelRequest,
    UpdateUsernameRequest,
)
from telethon.tl.types import InputPeerChannel

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# --- SAFE CONFIGURATION LOADING ---
api_id_str = os.environ.get("TELEGRAM_API_ID", "").strip()
api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
phone = os.environ.get("TELEGRAM_PHONE", "").strip()
session_string = os.environ.get("TELEGRAM_SESSION", "").strip()

if not all([api_id_str, api_hash, phone, session_string]):
    logger.critical("❌ CRITICAL: Missing GitHub Secrets.")
    sys.exit(1)

API_ID = int(api_id_str)
API_HASH = api_hash
PHONE = phone
SESSION_STRING = session_string
MAX_CYCLES = 30
TARGET_URL = "https://flowfame.com/free-telegram-members"

def generate_random_username():
    return "ch_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))

async def process_flowfame_with_nodriver(link):
    logger.info(f"=== STARTING BROWSER PROCESS FOR: {link} ===")
    browser = None
    try:
        # Find the actual Google Chrome binary installed by apt
        chrome_path = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
        if not chrome_path:
            logger.error("Could not find Google Chrome binary!")
            return False
            
        logger.info(f"Using Chrome binary at: {chrome_path}")

        # Add sandbox=False, specific executable path, and headless args
        browser = await uc.start(
            headless=True,
            sandbox=False, # CRITICAL for running as root
            browser_executable_path=chrome_path,
            browser_args=["--disable-dev-shm-usage", "--headless=new"]
        )
        
        tab = await browser.get(TARGET_URL)
        logger.info("Page loaded. Waiting 5 seconds...")
        await tab.sleep(5)

        # Attempt CAPTCHA click
        try:
            logger.info("Searching for Cloudflare Turnstile iframe...")
            iframe = await tab.select("iframe[src*='challenges.cloudflare.com']", timeout=10)
            if iframe:
                logger.info("Turnstile iframe found. Attempting to click...")
                # nodriver's mouse_click simulates a real cursor
                await iframe.mouse_click()
                logger.info("Clicked. Waiting 10 seconds for verification...")
                await tab.sleep(10)
            else:
                logger.info("No iframe found. It might be invisible or passed automatically.")
        except Exception as e:
            logger.warning(f"CAPTCHA interaction note: {e}")

        # Find input
        logger.info("Searching for Telegram link input...")
        link_input = await tab.select("input[placeholder*='t.me']", timeout=10)
        if not link_input:
            logger.error("Could not find the Telegram link input field.")
            await tab.save_screenshot("error_input.png")
            logger.error("Saved screenshot to error_input.png")
            return False

        await link_input.send_keys(link)
        await tab.sleep(1)

        logger.info("Searching for submit button...")
        submit_btn = await tab.select("button[type='submit']", timeout=10)
        if not submit_btn:
            logger.error("Could not find submit button.")
            await tab.save_screenshot("error_submit.png")
            return False

        await submit_btn.click()
        logger.info("Form submitted. Waiting for confirmation...")

        for i in range(24):
            await tab.sleep(5)
            page_text = await tab.evaluate("document.body.innerText")
            if "on the way" in page_text or "free claims remaining" in page_text:
                logger.info("🎉 Members claimed successfully!")
                return True
        
        logger.warning("Timeout waiting for confirmation.")
        await tab.save_screenshot("error_timeout.png")
        return False

    except Exception as e:
        logger.critical(f"Browser error: {e}")
        logger.critical(traceback.format_exc())
        return False
    finally:
        if browser:
            await browser.stop()

async def main():
    logger.info("========== SCRIPT STARTED ==========")
    
    if not os.path.exists("state.json"):
        logger.warning("state.json missing! Creating a new one...")
        with open("state.json", "w") as f:
            json.dump({"cycle": 0, "channel_id": None, "access_hash": None, "current_username": None}, f)

    with open("state.json", "r") as f:
        state = json.load(f)

    current_cycle = state["cycle"]
    if current_cycle >= MAX_CYCLES:
        logger.info(f"🏁 Reached {MAX_CYCLES} cycles. Exiting.")
        sys.exit(0)

    logger.info(f"--- 🔄 Starting Cycle {current_cycle + 1}/{MAX_CYCLES} ---")

    try:
        session = StringSession(SESSION_STRING)
        client = TelegramClient(session, API_ID, API_HASH)
    except Exception as e:
        logger.critical(f"❌ CRITICAL: Failed to parse TELEGRAM_SESSION. Error: {e}")
        sys.exit(1)

    try:
        await client.start()
        logger.info("Telegram client connected.")
    except Exception as e:
        logger.critical(f"Failed to connect to Telegram: {e}")
        sys.exit(1)

    try:
        if current_cycle == 0:
            logger.info("Creating new channel...")
            result = await client(CreateChannelRequest(
                title="Auto Claim Channel", about="Temporary channel", broadcast=True
            ))
            channel = result.chats[0]
            state["channel_id"] = channel.id
            state["access_hash"] = channel.access_hash
            
            current_username = generate_random_username()
            peer = InputPeerChannel(channel.id, channel.access_hash)
            if await client(CheckUsernameRequest(peer, current_username)):
                await client(UpdateUsernameRequest(peer, current_username))
                state["current_username"] = current_username
                logger.info(f"Channel made public: https://t.me/{current_username}")
            else:
                logger.error("Failed to set initial username.")
                sys.exit(1)
        else:
            logger.info("Rotating channel username...")
            peer = InputPeerChannel(state["channel_id"], state["access_hash"])
            new_username = generate_random_username()
            if await client(CheckUsernameRequest(peer, new_username)):
                await client(UpdateUsernameRequest(peer, new_username))
                state["current_username"] = new_username
                logger.info(f"Username updated: https://t.me/{new_username}")
            else:
                logger.error("Failed to update username (FloodWait?).")
                sys.exit(1)
    except Exception as e:
        logger.critical(f"Telegram Error: {e}")
        sys.exit(1)
    finally:
        if client.is_connected():
            await client.disconnect()

    link_to_claim = f"https://t.me/{state['current_username']}"
    success = await process_flowfame_with_nodriver(link_to_claim)

    if success:
        state["cycle"] += 1
        with open("state.json", "w") as f:
            json.dump(state, f, indent=2)
        logger.info(f"✅ Cycle {current_cycle + 1} complete. State saved.")
    else:
        logger.error("❌ Cycle failed. State NOT updated. Will retry next hour.")

if __name__ == "__main__":
    asyncio.run(main())
