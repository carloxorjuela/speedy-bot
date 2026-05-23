import os
from dotenv import load_dotenv

load_dotenv()

WHATSAPP_TOKEN    = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "speedy_verify_2024")

GOOGLE_SHEETS_ID        = os.getenv("GOOGLE_SHEETS_ID", "1vTSCljUl3ycIE4B72o4-jeZn7iuJG9WxVX0jbTxJpPg")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

TWOCAPTCHA_KEY = os.getenv("TWOCAPTCHA_KEY", "")
PORT = int(os.getenv("PORT", "5001"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
