import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ── LLM / Parsing ──────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
LLAMAPARSE_API_KEY = os.getenv("LLAMAPARSE_API_KEY")

# ── MongoDB ──────────────────────────────────────────────────────────────
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "recruitai")
MONGODB_COLLECTION = os.getenv("MONGODB_COLLECTION", "candidates")

# ── IMAP — inbox monitored by Intake node ────────────────────────────────
IMAP_EMAIL = os.getenv("IMAP_EMAIL")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD")
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))

# ── SMTP — outgoing HR report dispatch ────────────────────────────────────
SMTP_EMAIL = os.getenv("SMTP_EMAIL", IMAP_EMAIL)
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", IMAP_PASSWORD)
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))

# ── HR recipient ───────────────────────────────────────────────────────
HR_EMAIL = os.getenv("HR_EMAIL")

# ── Run mode ─────────────────────────────────────────────────────────────
# "once"  -> process whatever is currently unread, then exit (default, CI/cron-friendly)
# "loop"  -> keep polling the inbox every POLL_INTERVAL_SECONDS forever
RUN_MODE = os.getenv("RUN_MODE", "once")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
MAX_INTAKE_RETRIES = int(os.getenv("MAX_INTAKE_RETRIES", "3"))

# ── Checkpointing ──────────────────────────────────────────────────────
# SQLite file used by LangGraph to persist workflow progress so a crash
# mid-pipeline can resume instead of silently losing the candidate.
CHECKPOINT_DB_PATH = os.getenv("CHECKPOINT_DB_PATH", "checkpoints.sqlite")
