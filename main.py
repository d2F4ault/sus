import asyncio
import json
import logging
import os
import random
import string
import sys
import traceback

import zendriver as zd
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.functions.channels import (
    CheckUsernameRequest,
    CreateChannelRequest,
    UpdateUsernameRequest,
)
from telethon.tl.types import InputPeerChannel

# --- LOGGING SETUP ---
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
    logger.critical("❌ CRITICAL: One or more GitHub Secrets are missing or empty!")
    sys.exit(1)

try:
    API_ID = int(api_id_str)
except ValueError:
    logger.critical(f"❌ CRITICAL: TELEGRAM_API_ID must be a number. Got: '{api_id_str}'")
    sys.exit(1)

API_HASH = api_hash
PHONE = phone
SESSION_STRING = session_string
MAX_CYCLES = 30
TARGET_URL = "https://flowfame.com/free-telegram-members"

# --- HELPER FUNCTIONS ---
def generate_random_username():
    return "ch_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))

def load_state():
    if not os.path.exists("state.json"):
        logger.warning("state.json missing. Creating a new one.")
        return {"cycle": 0, "channel_id": None, "access_hash": None, "current_username": None}
    try:
        with open("state.json", "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.error("state.json is corrupted! Resetting state.")
        return {"cycle": 0, "channel_id": None, "access_hash": None, "current_username": None}

def save_state(state):
    with open("state.json", "w") as f:
        json.dump(state, f, indent=2)

# --- BROWSER AUTOMATION ---
async def process_flowfame_with_zendriver(link):
    logger.info(f"=== STARTING BROWSER PROCESS FOR: {link} ===")
    browser = None
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Browser launch attempt {attempt + 1}/{max_retries}...")
            # Hardcode the correct Chrome path for GitHub Actions
            chrome_path = "/usr/bin/google-chrome"
            
            # Start zendriver with explicit path and sandbox disabled
            browser = await zd.start(
                browser_executable_path=chrome_path,
                headless=True,
                sandbox=False,
                browser_args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
            )
            logger.info("Browser connected successfully.")
            break
        except Exception as e:
            logger.warning(f"Browser launch attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                logger.critical("All browser launch attempts failed. Giving up on this cycle.")
                return False
            await asyncio.sleep(5)

    if not browser:
        return False

    try:
        tab = await browser.get(TARGET_URL)
        logger.info("Page loaded. Waiting 5 seconds for Cloudflare to initialize...")
        await tab.sleep(5)

        # --- CAPTCHA CLICK ---
        try:
            logger.info("Searching for Cloudflare Turnstile iframe...")
            iframe = await tab.select("iframe[src*='challenges.cloudflare.com']", timeout=15)
            if iframe:
                logger.info("Turnstile iframe found. Clicking...")
                await iframe.mouse_click()
                logger.info("Clicked. Waiting 10 seconds for verification...")
                await tab.sleep(10)
            else:
                logger.info("No iframe found. It might be invisible or passed automatically.")
        except Exception as e:
            logger.warning(f"CAPTCHA interaction note: {e}")

        # --- FILL FORM ---
        logger.info("Searching for Telegram link input...")
        link_input = await tab.select("input[placeholder*='t.me']", timeout=15)
        if not link_input:
            logger.error("Could not find the Telegram link input field. Saving screenshot...")
            await tab.save_screenshot("error_input.png")
            return False

        await link_input.send_keys(link)
        await tab.sleep(1)

        logger.info("Searching for submit button...")
        submit_btn = await tab.select("button[type='submit']", timeout=10)
        if not submit_btn:
            logger.error("Could not find submit button. Saving screenshot...")
            await tab.save_screenshot("error_submit.png")
            return False

        await submit_btn.click()
        logger.info("Form submitted. Waiting for confirmation...")

        # --- WAIT FOR SUCCESS ---
        for i in range(24):
            await tab.sleep(5)
            page_text = await tab.evaluate("document.body.innerText")
            if "on the way" in page_text or "free claims remaining" in page_text:
                logger.info("🎉 Members claimed successfully!")
                return True
        
        logger.warning("Timeout waiting for confirmation message. Saving screenshot...")
        await tab.save_screenshot("error_timeout.png")
        return False

    except Exception as e:
        logger.critical(f"Browser execution error: {e}")
        logger.critical(traceback.format_exc())
        return False
    finally:
        if browser:
            await browser.stop()
            logger.info("Browser closed.")

# --- MAIN EXECUTION ---
async def main():
    logger.info("========== SCRIPT STARTED ==========")
    
    state = load_state()
    current_cycle = state["cycle"]

    if current_cycle >= MAX_CYCLES:
        logger.info(f"🏁 Reached {MAX_CYCLES} cycles. Automation complete. Exiting.")
        sys.exit(0)

    logger.info(f"--- 🔄 Starting Cycle {current_cycle + 1}/{MAX_CYCLES} ---")

    # Initialize Telegram
    try:
        session = StringSession(SESSION_STRING)
        client = TelegramClient(session, API_ID, API_HASH)
        await client.start()
        logger.info("Telegram client connected.")
    except Exception as e:
        logger.critical(f"Failed to connect to Telegram: {e}")
        sys.exit(1)

    # Create or Update Channel
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
                logger.error("Failed to set initial username (taken). Exiting.")
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
                logger.error("Failed to update username (taken). Exiting.")
                sys.exit(1)
                
    except FloodWaitError as e:
        logger.error(f"⚠️ Telegram FloodWait: You must wait {e.seconds} seconds before doing this again.")
        logger.error("Skipping this cycle. The next scheduled run will try again.")
        await client.disconnect()
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Telegram Error: {e}")
        await client.disconnect()
        sys.exit(1)
    finally:
        if client.is_connected():
            await client.disconnect()

    # Claim Members
    link_to_claim = f"https://t.me/{state['current_username']}"
    success = await process_flowfame_with_zendriver(link_to_claim)

    # Save State ONLY if successful
    if success:
        state["cycle"] += 1
        save_state(state)
        logger.info(f"✅ Cycle {current_cycle + 1} complete. State saved. Next cycle ready.")
    else:
        logger.error("❌ Cycle failed. State NOT updated. Will retry next hour.")

if __name__ == "__main__":
    asyncio.run(main())
