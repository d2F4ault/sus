import asyncio
import json
import logging
import os
import random
import string
import sys
import traceback

from seleniumbase import Driver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

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

# --- BROWSER AUTOMATION WITH SELENIUMBASE ---
def process_flowfame_with_seleniumbase(link):
    logger.info(f"=== STARTING BROWSER PROCESS FOR: {link} ===")
    
    # Initialize SeleniumBase Driver with Undetected Chrome (uc) mode
    driver = None
    try:
        logger.info("Launching SeleniumBase Driver...")
        driver = Driver(uc=True, headless=True)
        logger.info("Browser connected successfully.")
        
        driver.get(TARGET_URL)
        logger.info("Page loaded. Waiting for initial elements...")
        
        # --- CAPTCHA SOLVING ---
        # SeleniumBase's solve_captcha() uses CDP to handle Turnstile
        logger.info("Attempting to solve Cloudflare Turnstile with SeleniumBase...")
        try:
            driver.solve_captcha()  # Built-in method to handle CAPTCHAs
            logger.info("CAPTCHA solving attempted.")
        except Exception as e:
            logger.warning(f"CAPTCHA solver note: {e}. Proceeding anyway...")

        # --- WAIT FOR PAGE TO BE FULLY INTERACTABLE ---
        # Use explicit wait for the input field, indicating the page is ready
        logger.info("Waiting for Telegram link input to be interactable...")
        wait = WebDriverWait(driver, 20)
        link_input = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "input[placeholder*='t.me']"))
        )
        logger.info("Input field is ready.")

        # Fill the form
        link_input.clear()
        link_input.send_keys(link)
        logger.info("Link entered.")

        # --- SUBMIT FORM ---
        logger.info("Searching for submit button...")
        submit_btn = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))
        )
        submit_btn.click()
        logger.info("Form submitted. Waiting for confirmation...")

        # --- WAIT FOR SUCCESS CONFIRMATION ---
        success = False
        for _ in range(24):  # Wait up to 2 minutes
            driver.sleep(5)
            page_text = driver.find_element(By.TAG_NAME, "body").text
            if "on the way" in page_text or "free claims remaining" in page_text:
                logger.info("🎉 Members claimed successfully!")
                success = True
                break
        
        if not success:
            logger.warning("Timeout waiting for confirmation message.")
            driver.save_screenshot("error_timeout.png")
            logger.error("Saved screenshot to error_timeout.png")
        
        return success

    except Exception as e:
        logger.critical(f"Browser execution error: {e}")
        logger.critical(traceback.format_exc())
        if driver:
            driver.save_screenshot("error_exception.png")
        return False
    finally:
        if driver:
            driver.quit()
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
    success = process_flowfame_with_seleniumbase(link_to_claim)

    # Save State ONLY if successful
    if success:
        state["cycle"] += 1
        save_state(state)
        logger.info(f"✅ Cycle {current_cycle + 1} complete. State saved. Next cycle ready.")
    else:
        logger.error("❌ Cycle failed. State NOT updated. Will retry next hour.")

if __name__ == "__main__":
    asyncio.run(main())
