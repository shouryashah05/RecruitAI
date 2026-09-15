import time

from graph.workflow import build_workflow
from config.settings import (
    IMAP_EMAIL, RUN_MODE, POLL_INTERVAL_SECONDS, MAX_INTAKE_RETRIES, CHECKPOINT_DB_PATH,
)
from nodes.intake import connect, list_unseen_ids, parse_message, mark_seen
from core.db import save_processing_failure, flag_for_manual_review

SUCCESS_MARKERS = ("Dispatch Complete",)
# Statuses that mean "nothing to retry" (e.g. no attachment) — still mark seen,
# no point re-processing the same malformed email forever.
TERMINAL_NO_RETRY_MARKERS = ("Failed - No Resume Attachment Found",)


def process_one_message(graph, mail, msg_id) -> str:
    """Parses, runs the full pipeline for, and resolves (seen/retry/dead-letter) one email."""
    parsed = parse_message(mail, msg_id)
    message_id_header = parsed.get("message_id_header", msg_id.decode())
    sender_email = parsed.get("sender_email", "Unknown")

    if parsed.get("status") in TERMINAL_NO_RETRY_MARKERS:
        mark_seen(mail, msg_id)
        return parsed["status"]

    try:
        final_state = graph.invoke(parsed, config={"configurable": {"thread_id": message_id_header}})
        status = final_state.get("status", "Unknown Status")
    except Exception as e:
        status = f"Pipeline crashed: {e}"

    if any(marker in status for marker in SUCCESS_MARKERS):
        mark_seen(mail, msg_id)
        return status

    retry_count = save_processing_failure(message_id_header, sender_email, status)
    if retry_count >= MAX_INTAKE_RETRIES:
        flag_for_manual_review(message_id_header, sender_email, status)
        mark_seen(mail, msg_id)  # stop retrying forever; a human takes it from here
        return f"{status} (gave up after {retry_count} attempts, flagged for manual review)"

    # Left unseen on purpose: will be retried on the next inbox scan.
    return f"{status} (attempt {retry_count}/{MAX_INTAKE_RETRIES}, will retry)"


def run_once(graph) -> int:
    """Processes every currently-unread application email. Returns how many were handled."""
    mail = connect()
    try:
        ids = list_unseen_ids(mail)
        if not ids:
            print("No unread emails found.")
            return 0

        print(f"Found {len(ids)} unread email(s).")
        for msg_id in ids:
            status = process_one_message(graph, mail, msg_id)
            print(f"  [{msg_id.decode()}] {status}")
        return len(ids)
    finally:
        mail.logout()


def main():
    print("=" * 50)
    print("Starting RecruitAI Headless Talent Engine...")
    print(f"Monitoring inbox: {IMAP_EMAIL}")
    print(f"Run mode: {RUN_MODE}")
    print("=" * 50)

    from langgraph.checkpoint.sqlite import SqliteSaver

    with SqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as checkpointer:
        graph = build_workflow(checkpointer=checkpointer)

        if RUN_MODE == "loop":
            while True:
                try:
                    run_once(graph)
                except Exception as e:
                    print(f"Inbox scan failed: {e}")
                print(f"Sleeping {POLL_INTERVAL_SECONDS}s before next scan...")
                time.sleep(POLL_INTERVAL_SECONDS)
        else:
            run_once(graph)


if __name__ == "__main__":
    main()
