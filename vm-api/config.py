import os
from dotenv import load_dotenv

load_dotenv()

FIREFLIES_API_KEY = os.environ["FIREFLIES_API_KEY"]
# Optional: if empty, webhook signature verification is skipped (useful for local dev)
FIREFLIES_WEBHOOK_SECRET = os.environ.get("FIREFLIES_WEBHOOK_SECRET", "")

LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://34.61.120.233:4000/v1")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
LITELLM_MODEL = os.environ.get("LITELLM_MODEL", "claude-sonnet")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

KNOWN_CATEGORIES = {
    "customer-discovery": "Customer Interviews & Sales",
    "investor-calls": "Investor Calls",
    "team-syncs": "Team Syncs",
    "competitors": "Competitor Research",
    "advisors": "Advisors",
    # Stanford GSB classes (Q3 2026)
    "class-mge": "MGE — Managing Growing Enterprises",
    "class-sales": "Sales — Building Sales Organizations",
    "class-leadership": "Leadership — Art of Leading in Challenging Times",
    "class-taxes": "Taxes — Taxes and Business Strategy",
    "class-fsa": "FSA — Financial Statement Analysis",
}

INTERNAL_TEAM_NAMES = [
    "elman",
    "klara",
    "broccoli",
]

NLM_ENABLED_CATEGORIES = {"customer-discovery"}

HINDSIGHT_API_KEY = os.environ.get("HINDSIGHT_API_KEY", "")
