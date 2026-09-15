from datetime import datetime, timezone

from pymongo import MongoClient
from config.settings import MONGODB_URI, MONGODB_DB_NAME, MONGODB_COLLECTION

# Initialize a global client to reuse connections
_client = None

def get_database():
    """Returns a connection to the MongoDB database."""
    global _client
    if _client is None:
        _client = MongoClient(MONGODB_URI)
    return _client[MONGODB_DB_NAME]

def save_candidate_profile(email: str, profile_data: dict):
    """
    Records an evaluation for a candidate. Writes to two places:
      - `<MONGODB_COLLECTION>` — upserted "latest known state" per email, for
        quick lookups.
      - `<MONGODB_COLLECTION>_history` — an append-only record of every
        evaluation, so a re-application doesn't silently erase the audit
        trail of a candidate's earlier attempt/role.
    """
    db = get_database()
    profile_data = {**profile_data, "updated_at": datetime.now(timezone.utc)}

    latest = db[MONGODB_COLLECTION]
    result = latest.update_one(
        {"email": email},
        {"$set": profile_data},
        upsert=True
    )

    history = db[f"{MONGODB_COLLECTION}_history"]
    history.insert_one({**profile_data, "email": email})

    return result.upserted_id or email


def save_processing_failure(message_id: str, sender_email: str, reason: str) -> int:
    """
    Records an intake/pipeline failure keyed by the email's stable Message-ID
    so retries can be counted across runs. Returns the failure count so far.
    """
    db = get_database()
    failures = db["processing_failures"]
    doc = failures.find_one_and_update(
        {"message_id": message_id},
        {
            "$set": {"sender_email": sender_email, "last_reason": reason, "last_seen_at": datetime.now(timezone.utc)},
            "$inc": {"retry_count": 1},
        },
        upsert=True,
        return_document=True,
    )
    return doc.get("retry_count", 1)


def flag_for_manual_review(message_id: str, sender_email: str, reason: str):
    """Gives up retrying a message and records it for a human to look at directly."""
    db = get_database()
    db["needs_manual_review"].insert_one({
        "message_id": message_id,
        "sender_email": sender_email,
        "reason": reason,
        "flagged_at": datetime.now(timezone.utc),
    })
