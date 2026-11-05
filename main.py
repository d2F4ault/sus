import asyncio
import json
import logging
import os
import random
import string
import sys
import traceback

import nodriver as uc
from telethon import TelegramClient
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
api_id_str = os.environ.get("TELEGRAM_API_ID", "")
api_hash = os.environ.get("TELEGRAM_API_HASH", "")
phone = os.environ.get("TELEGRAM_PHONE", "")
session_string = os.environ.get("TELEGRAM_SESSION", "")

if not all([api_id_str, api_hash, phone, session_string]):
    logger.critical("❌ CRITICAL: One or more GitHub Secrets are missing or empty!")
    logger.critical("Please go to your GitHub Repo -> Settings -> Secrets and variables -> Actions.")
    logger.critical("Ensure you have added: TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE, TELEGRAM_SESSION")
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

# ... (Rest of the script remains exactly the same from here) ...
def generate_random_username():
    return "ch_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))

async def process_flowfame_with_nodriver(link):
    # ... (keep the rest of the file as it was) ...
