import asyncio
import logging
import os
import random
import string
import time

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
CYCLES = 30
SLEEP_SECONDS = 3600  # 1 Hour

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

def generate_random_username():
    """Generates a random, unique Telegram username."""
    return "ch_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))

async def change_channel_username(client, channel_entity, new_username):
    """Updates the public username of a Telegram channel."""
    try:
        # Check if the new username is available
        check = await client(CheckUsernameRequest(channel_entity, new_username))
        if check:
            await client(UpdateUsernameRequest(channel_entity, new_username))
            logging.info(f"✅ Username updated to: {new_username}")
            return f"https://t.me/{new_username}"
        else:
            logging.warning(f"⚠️ Username {new_username} taken. Retrying...")
            return await change_channel_username(client, channel_entity, generate_random_username())
    except Exception as e:
        logging.error(f"Failed to change username: {e}")
        raise

async def process_flowfame_with_nodriver(link):
    """Opens the browser, clicks the Turnstile checkbox, and submits the link."""
    browser = await uc.start(headless=True) # Headless mode for GitHub Actions
    tab = await browser.get(TARGET_URL)
    
    # 1. Wait for the page to load
    await tab.sleep(5)
    
    # 2. Locate the Turnstile checkbox (inside an iframe) and click it
    # NOTE: The exact selector may change. We search for the iframe and simulate a human click.
    logging.info("Searching for Cloudflare Turnstile iframe...")
    try:
        # Wait for the iframe to appear
        iframe = await tab.select("iframe[src*='challenges.cloudflare.com']", timeout=10)
        if iframe:
            logging.info("Turnstile iframe found. Attempting to click...")
            # Move mouse to the iframe and click (simulating human interaction)
            await iframe.mouse_click()
            await tab.sleep(5) # Wait for verification
        else:
            logging.warning("Turnstile iframe not found immediately. Waiting...")
            await tab.sleep(10)
    except Exception as e:
        logging.error(f"Error interacting with Turnstile: {e}")

    # 3. Fill the form with the Telegram link
    logging.info("Filling the form...")
    link_input = await tab.select("input[placeholder*='t.me']", timeout=10)
    if link_input:
        await link_input.send_keys(link)
        await tab.sleep(1)
        
        # 4. Click submit
        submit_btn = await tab.select("button[type='submit']")
        if submit_btn:
            await submit_btn.click()
            logging.info("Form submitted. Waiting for progress...")
            # Wait for the success page (max 3 minutes)
            for _ in range(36):
                await tab.sleep(5)
                page_text = await tab.evaluate("document.body.innerText")
                if "on the way" in page_text or "free claims remaining" in page_text:
                    logging.info("🎉 Members claimed successfully!")
                    break
            else:
                logging.warning("Timeout waiting for confirmation page.")
    else:
        logging.error("Could not find the input field. The page layout may have changed.")
    
    await browser.stop()

async def main():
    # Initialize Telegram Client (using the session string to avoid re-login)
    session = os.environ.get("TELEGRAM_SESSION")
    client = TelegramClient(session, API_ID, API_HASH)
    await client.start(phone=PHONE)
    
    logging.info("🚀 Starting Automation Loop (30 Cycles)...")

    # 1. Create the initial channel
    logging.info("Creating initial channel...")
    result = await client(CreateChannelRequest(
        title="Auto Channel", about="Temporary channel", broadcast=True
    ))
    channel = result.chats[0]
    
    # Make it public with a random username
    current_username = generate_random_username()
    # Check and set username
    peer = InputPeerChannel(channel.id, channel.access_hash)
    check = await client(CheckUsernameRequest(peer, current_username))
    if check:
        await client(UpdateUsernameRequest(peer, current_username))
        current_link = f"https://t.me/{current_username}"
        logging.info(f"Channel created and public: {current_link}")
    else:
        logging.error("Initial username generation failed. Exiting.")
        await client.disconnect()
        return

    # 2. The 30-Cycle Loop
    for cycle in range(1, CYCLES + 1):
        logging.info(f"\n--- 🔄 CYCLE {cycle}/{CYCLES} ---")
        
        # Step A: Use the current link to claim members
        await process_flowfame_with_nodriver(current_link)
        
        # Step B: Sleep for 1 hour (unless it's the last cycle)
        if cycle < CYCLES:
            logging.info(f"💤 Sleeping for {SLEEP_SECONDS} seconds (1 Hour)...")
            await asyncio.sleep(SLEEP_SECONDS)
            
            # Step C: Change the username to get a new link for the next cycle
            logging.info("🔄 Rotating channel username for the next cycle...")
            current_username = generate_random_username()
            current_link = await change_channel_username(client, peer, current_username)
            logging.info(f"New link ready for Cycle {cycle + 1}: {current_link}")

    logging.info("🏁 All 30 cycles completed. Shutting down.")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
