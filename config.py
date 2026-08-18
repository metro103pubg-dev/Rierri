import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    TG_BOT_TOKEN: str = os.getenv("TG_BOT_TOKEN", "")
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
    API_ID: int = int(os.getenv("API_ID", "0"))
    API_HASH: str = os.getenv("API_HASH", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv(
        "OPENAI_BASE_URL", 
        "https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    DB_NAME: str = "curator_bot.db"

config = Config()
