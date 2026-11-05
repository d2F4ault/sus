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
API_ID = int(os.environ.get("TELEGRAM_API_ID"))
API_HASH = os.environ.get("TELEGRAM_API_HASH")
PHONE = os.environ.get("TELEGRAM_PHONE")
TARGET_URL = "https://flowfame.com/free-telegram-members"
MAX_CYCLES = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

def generate_random_username():
    return "ch_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))

async def process_flowfame_with_nodriver(link):
    """Opens the browser, solves CAPTCHA, submits link."""
    logging.info(f"Opening browser to claim for: {link}")
    browser = await uc.start(headless=True, browser_args=["--no-sandbox"])
    tab = await browser.get(TARGET_URL)
    
    await tab.sleep(5) # Wait for page load
    
    try:
        # Attempt to click the Turnstile iframe
        iframe = await tab.select("iframe[src*='challenges.cloudflare.com']", timeout=10)
        if iframe:
            logging.info("Clicking Turnstile checkbox...")
            await iframe.mouse_click()
            await tab.sleep(5)
    except Exception as e:
        logging.warning(f"Turnstile interaction note: {e}")

    # Fill form and submit
    link_input = await tab.select("input[placeholder*='t.me']", timeout=10)
    if link_input:
        await link_input.send_keys(link)
        await tab.sleep(1)
        
        submit_btn = await tab.select("button[type='submit']")
        if submit_btn:
            await submit_btn.click()
            logging.info("Submitted. Waiting for confirmation...")
            for _ in range(24): # Wait up to 2 mins
                await tab.sleep(5)
                page_text = await tab.evaluate("document.body.innerText")
                if "on the way" in page_text or "free claims remaining" in page_text:
                    logging.info("🎉 Members claimed successfully!")
                    break
    else:
        logging.error("Could not find input field. Page layout changed or blocked.")
    
    await browser.stop()

async def main():
    # 1. Read State
    try:
        with open("state.json", "r") as f:
            state = json.load(f)
    except FileNotFoundError:
        logging.error("state.json not found. Initializing default.")
        state = {"cycle": 0, "channel_id": None, "access_hash": None, "current_username": None}

    current_cycle = state["cycle"]
    
    if current_cycle >= MAX_CYCLES:
        logging.info(f"🏁 Reached {MAX_CYCLES} cycles. Automation complete. Exiting.")
        sys.exit(0)

    logging.info(f"--- 🔄 Starting Cycle {current_cycle + 1}/{MAX_CYCLES} ---")

    # 2. Initialize Telegram
    session = os.environ.get("TELEGRAM_SESSION")
    client = TelegramClient(session, API_ID, API_HASH)
    await client.start(phone=PHONE)

    # 3. Execute Cycle Logic
    if current_cycle == 0:
        # First run: Create the channel
        logging.info("Creating new channel...")
        result = await client(CreateChannelRequest(
            title="Auto Channel", about="Temporary channel", broadcast=True
        ))
        channel = result.chats[0]
        
        state["channel_id"] = channel.id
        state["access_hash"] = channel.access_hash
        
        current_username = generate_random_username()
        peer = InputPeerChannel(channel.id, channel.access_hash)
        
        if await client(CheckUsernameRequest(peer, current_username)):
            await client(UpdateUsernameRequest(peer, current_username))
            state["current_username"] = current_username
            logging.info(f"Channel created: https://t.me/{current_username}")
        else:
            logging.error("Initial username failed. Try again later.")
            await client.disconnect()
            sys.exit(1)
    else:
        # Subsequent runs: Change username
        logging.info("Changing channel username...")
        peer = InputPeerChannel(state["channel_id"], state["access_hash"])
        current_username = generate_random_username()
        
        if await client(CheckUsernameRequest(peer, current_username)):
            await client(UpdateUsernameRequest(peer, current_username))
            state["current_username"] = current_username
            logging.info(f"Username updated to: https://t.me/{current_username}")
        else:
            logging.error("Username update failed. Likely Telegram FloodWait.")
            await client.disconnect()
            sys.exit(1)

    await client.disconnect()

    # 4. Claim Members using the new link
    link = f"https://t.me/{state['current_username']}"
    await process_flowfame_with_nodriver(link)

    # 5. Update State and Save
    state["cycle"] += 1
    with open("state.json", "w") as f:
        json.dump(state, f, indent=2)
    
    logging.info(f"✅ Cycle {current_cycle + 1} complete. State saved. Exiting.")

if __name__ == "__main__":
    asyncio.run(main())
