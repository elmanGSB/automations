import os
from dotenv import load_dotenv

load_dotenv()

FIREFLIES_API_KEY = os.environ.get("FIREFLIES_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
AGENTMAIL_API_KEY = os.environ.get("AGENTMAIL_API_KEY", "")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
HINDSIGHT_API_KEY = os.environ.get("HINDSIGHT_API_KEY", "")
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

INTERNAL_TEAM_NAMES = ["elman", "klara", "broccoli"]

KNOWN_CATEGORIES = {
    "customer-discovery": "Customer Interviews & Sales",
    "investor-calls": "Investor Calls",
    "team-syncs": "Team Syncs",
    "competitors": "Competitor Research",
    "advisors": "Advisors",
    "class-mge": "MGE — Managing Growing Enterprises",
    "class-sales": "Sales — Building Sales Organizations",
    "class-leadership": "Leadership — Art of Leading in Challenging Times",
    "class-taxes": "Taxes — Taxes and Business Strategy",
    "class-fsa": "FSA — Financial Statement Analysis",
}
