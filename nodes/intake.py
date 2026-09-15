import imaplib
import email
import os
import re
from email.header import decode_header
from graph.state import GraphState
from config.settings import IMAP_EMAIL, IMAP_PASSWORD, IMAP_SERVER, IMAP_PORT

TEMP_DIR = os.path.join(os.path.dirname(__file__), "..", "temp")
os.makedirs(TEMP_DIR, exist_ok=True)


def connect() -> imaplib.IMAP4_SSL:
    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    mail.login(IMAP_EMAIL, IMAP_PASSWORD)
    mail.select("inbox")
    return mail


def list_unseen_ids(mail: imaplib.IMAP4_SSL) -> list[bytes]:
    """Returns every currently-unread message id (not just the first one)."""
    status, messages = mail.search(None, "(UNSEEN)")
    if status != "OK" or not messages or not messages[0]:
        return []
    return messages[0].split()


def mark_seen(mail: imaplib.IMAP4_SSL, msg_id: bytes):
    mail.store(msg_id, "+FLAGS", "\\Seen")


def _sanitize_filename(filename: str) -> str:
    """
    Attachment filenames come from untrusted email content. Strip any path
    components and anything that isn't a safe filename character before it's
    ever joined into a filesystem path, to prevent writing outside TEMP_DIR.
    """
    filename = os.path.basename(filename)
    filename = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    return filename or "attachment"


def parse_message(mail: imaplib.IMAP4_SSL, msg_id: bytes) -> dict:
    """
    Fetches and parses ONE message using BODY.PEEK[] so it is NOT marked as
    read as a side effect. The caller (main.py) only calls mark_seen() once
    the full downstream pipeline has actually succeeded for this message —
    so a crash mid-pipeline leaves the email available to retry, instead of
    silently disappearing.
    """
    status, msg_data = mail.fetch(msg_id, "(BODY.PEEK[])")

    document_path = None
    role = "Assistant Professor"  # Default assumption
    sender = "Unknown"
    message_id_header = msg_id.decode()

    for response_part in msg_data:
        if isinstance(response_part, tuple):
            msg = email.message_from_bytes(response_part[1])

            # Stable id (survives across IMAP sessions/UIDs) used for retry bookkeeping.
            message_id_header = msg.get("Message-ID", msg_id.decode())

            subject_header = msg["Subject"]
            if subject_header:
                subject, encoding = decode_header(subject_header)[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding if encoding else "utf-8")
            else:
                subject = ""

            sender = msg.get("From", "Unknown")

            if "Associate Professor" in subject:
                role = "Associate Professor"
            elif "Professor" in subject:
                role = "Professor"
            elif "Assistant Professor" in subject:
                role = "Assistant Professor"

            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    if part.get("Content-Disposition") is None:
                        continue

                    filename = part.get_filename()
                    if filename and filename.lower().endswith((".pdf", ".docx", ".doc")):
                        safe_filename = _sanitize_filename(filename)
                        document_path = os.path.join(TEMP_DIR, f"{msg_id.decode()}_{safe_filename}")
                        with open(document_path, "wb") as f:
                            f.write(part.get_payload(decode=True))
                        break

    result = {
        "email_id": msg_id.decode(),
        "message_id_header": message_id_header,
        "sender_email": sender,
        "applied_role": role,
    }
    if not document_path:
        result["status"] = "Failed - No Resume Attachment Found"
    else:
        result["document_path"] = document_path
        result["status"] = "Intake Complete"
    return result


def intake_node(state: GraphState) -> GraphState:
    """
    LangGraph entry node. In normal operation main.py has already connected
    to IMAP, listed every unread message, and pre-populated the initial state
    for ONE message via parse_message() above — so this node is a no-op
    passthrough. It only does the connect/list/parse itself as a convenience
    fallback so the graph is still runnable standalone (e.g. `python main.py`
    with no orchestration, or ad-hoc testing).
    """
    if state.get("email_id"):
        return {}

    if not IMAP_EMAIL or not IMAP_PASSWORD:
        return {"status": "Failed - IMAP credentials missing in environment variables."}

    try:
        mail = connect()
        try:
            ids = list_unseen_ids(mail)
            if not ids:
                return {"status": "No unread emails found"}
            result = parse_message(mail, ids[0])
            if result.get("status") == "Intake Complete":
                mark_seen(mail, ids[0])
            return result
        finally:
            mail.logout()
    except Exception as e:
        return {"status": f"IMAP Error: {e}"}
