import os
from dotenv import load_dotenv

load_dotenv()

FIREFLIES_API_KEY = os.environ["FIREFLIES_API_KEY"]
FIREFLIES_WEBHOOK_SECRET = os.environ.get("FIREFLIES_WEBHOOK_SECRET", "")

LITELLM_BASE_URL = "http://34.61.120.233:4000/v1"
LITELLM_API_KEY = "sk-litellm-8890d532d361215dcf8001d58e4c336a"
LITELLM_MODEL = "claude-sonnet"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

KNOWN_CATEGORIES = {
    "customer-discovery": "Customer Interviews & Sales",
    "investor-calls": "Investor Calls",
    "team-syncs": "Team Syncs",
    "competitors": "Competitor Research",
    "advisors": "Advisors",
}
