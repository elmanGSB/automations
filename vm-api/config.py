import os
from dotenv import load_dotenv

load_dotenv()

FIREFLIES_API_KEY = os.environ["FIREFLIES_API_KEY"]

LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000/v1")
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
    "class-fin-trading": "Fin Trading — Financial Trading Strategies",
    "class-conv-mgmt": "Conv in Mgmt — Conversations in Management",
    "class-policy": "Policy — Policy Proposals & Political Strategy",
    "class-humor": "Humor — Comedy Fundamentals",
}

INTERNAL_TEAM_NAMES = [
    "elman",
    "klara",
    "broccoli",
]

# Categories whose transcripts get archived as sources in a per-category
# NotebookLM notebook. Any category we've intentionally named is archived;
# ad-hoc/unknown categories skip NLM entirely to avoid orphan notebooks.
NLM_UPLOAD_CATEGORIES = set(KNOWN_CATEGORIES.keys())

# Categories where novel-insights analysis + email run on top of upload.
# Restricted to customer-discovery: other categories have no [INTERVIEWEE]
# speaker, so the NLM prompt returns noise.
NLM_ANALYSIS_CATEGORIES = {"customer-discovery"}

HINDSIGHT_API_KEY = os.environ.get("HINDSIGHT_API_KEY", "")
