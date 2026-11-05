import asyncio
import json
import logging
import os
import random
import string
import sys

import nodriver as uc
from telethon import TelegramClient
from telethon.tl.functions.channels import (
    CheckUsernameRequest,
    CreateChannelRequest,
    UpdateUsernameRequest,
)
from telethon.tl.types import InputPeerChannel

# --- CONFIGURATION ---
# These are now fetched securely from GitHub Secrets
API_ID = int(os.environ.get("TELEGRAM_API_ID"))
API_HASH = os.environ.get("TELEGRAM_API_HASH")
PHONE = os.environ.get("TELEGRAM_PHONE")
# The session string is a one-time login token. You do not need to change this.
SESSION_STRING = os.environ.get("TELEGRAM_SESSION")

TARGET_URL = "https://flowfame.com/free-telegram-members"
MAX_CYCLES = 30

# Configure logging to be more detailed
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def generate_random_username():
    """Generates a random string suitable for a Telegram username."""
    return "ch_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))

async def process_flowfame_with_nodriver(link):
    """Opens the browser, solves the CAPTCHA, and submits the link."""
    logging.info(f"Opening browser to claim for: {link}")
    browser = None
    try:
        # Improved browser startup with arguments for stability in CI environments
        browser = await uc.start(
            headless=True,
            browser_args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        tab = await browser.get(TARGET_URL)
        
        await tab.sleep(5) # Wait for the page and any potential challenges

        # --- CAPTCHA SOLVING LOGIC ---
        # The most common technique is to find the Turnstile iframe and click it.
        try:
            logging.info("Searching for Cloudflare Turnstile iframe...")
            iframe = await tab.select("iframe[src*='challenges.cloudflare.com']", timeout=15)
            if iframe:
                logging.info("Turnstile iframe found. Attempting to click...")
                # Nodriver's mouse_click is more human-like than .click()
                await iframe.mouse_click()
                await tab.sleep(7) # Wait for the challenge to complete
            else:
                logging.warning("Turnstile iframe not found. It might be invisible or page has changed.")
        except Exception as e:
            logging.warning(f"Error during CAPTCHA interaction: {e}")

        # --- FORM SUBMISSION ---
        logging.info("Filling the form...")
        link_input = await tab.select("input[placeholder*='t.me']", timeout=10)
        if not link_input:
            logging.error("Fatal: Could not find the Telegram link input field.")
            return # Exit this function

        await link_input.send_keys(link)
        await tab.sleep(1) # Small delay to mimic typing

        submit_btn = await tab.select("button[type='submit']", timeout=10)
        if not submit_btn:
            logging.error("Fatal: Could not find the submit button.")
            return

        await submit_btn.click()
        logging.info("Form submitted. Waiting for confirmation...")

        # --- WAIT FOR SUCCESS CONFIRMATION ---
        # Poll for the success message instead of using a fixed sleep
        for i in range(24): # Wait for up to 2 minutes (24 * 5s)
            await tab.sleep(5)
            page_text = await tab.evaluate("document.body.innerText")
            if "on the way" in page_text or "free claims remaining" in page_text:
                logging.info("🎉 Members claimed successfully!")
                return
        logging.warning("Timeout waiting for confirmation message.")

    except Exception as e:
        logging.error(f"An unexpected error occurred in process_flowfame: {e}")
    finally:
        if browser:
            await browser.stop()

async def main():
    # 1. READ STATE
    # If the file doesn't exist, this will raise an error. The workflow handles this.
    try:
        with open("state.json", "r") as f:
            state = json.load(f)
    except FileNotFoundError:
        logging.error("state.json not found! This should not happen in the automated flow.")
        sys.exit(1)

    current_cycle = state["cycle"]
    
    if current_cycle >= MAX_CYCLES:
        logging.info(f"🏁 Reached {MAX_CYCLES} cycles. Automation complete. Exiting.")
        sys.exit(0)

    logging.info(f"--- 🔄 Starting Cycle {current_cycle + 1}/{MAX_CYCLES} ---")

    # 2. INITIALIZE TELEGRAM CLIENT
    client = TelegramClient(SESSION_STRING, API_ID, API_HASH)
    await client.start()
    logging.info("Telegram client connected.")

    # 3. EXECUTE CYCLE LOGIC
    try:
        if current_cycle == 0:
            # FIRST RUN: Create a new channel
            logging.info("Creating new channel...")
            result = await client(CreateChannelRequest(
                title="Auto Claim Channel", about="Temporary channel for claims", broadcast=True
            ))
            channel = result.chats[0]
            state["channel_id"] = channel.id
            state["access_hash"] = channel.access_hash
            
            current_username = generate_random_username()
            peer = InputPeerChannel(channel.id, channel.access_hash)
            if await client(CheckUsernameRequest(peer, current_username)):
                await client(UpdateUsernameRequest(peer, current_username))
                state["current_username"] = current_username
                logging.info(f"Channel created and made public: https://t.me/{current_username}")
            else:
                logging.error("Failed to set initial username. Aborting cycle.")
                await client.disconnect()
                sys.exit(1) # Exit on failure to retry next hour
        else:
            # SUBSEQUENT RUNS: Change the username of the existing channel
            logging.info("Rotating channel username...")
            peer = InputPeerChannel(state["channel_id"], state["access_hash"])
            new_username = generate_random_username()
            if await client(CheckUsernameRequest(peer, new_username)):
                await client(UpdateUsernameRequest(peer, new_username))
                state["current_username"] = new_username
                logging.info(f"Username updated successfully: https://t.me/{new_username}")
            else:
                logging.error("Failed to update username (likely FloodWait). Aborting cycle.")
                await client.disconnect()
                sys.exit(1) # Exit on failure
    except Exception as e:
        logging.error(f"FATAL Telegram error: {e}")
        await client.disconnect()
        sys.exit(1) # Exit on any Telegram error to be safe
    finally:
        # Ensure the client is always disconnected
        if client.is_connected():
            await client.disconnect()

    # 4. CLAIM MEMBERS using the new link
    link_to_claim = f"https://t.me/{state['current_username']}"
    await process_flowfame_with_nodriver(link_to_claim)

    # 5. UPDATE STATE
    state["cycle"] += 1
    with open("state.json", "w") as f:
        json.dump(state, f, indent=2)
    
    logging.info(f"✅ Cycle {current_cycle + 1} complete. State saved. Exiting.")

if __name__ == "__main__":
    asyncio.run(main())
