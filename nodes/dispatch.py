import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

from tenacity import retry, stop_after_attempt, wait_exponential

from graph.state import GraphState
from config.settings import SMTP_EMAIL, SMTP_PASSWORD, SMTP_SERVER, SMTP_PORT, HR_EMAIL
from core.db import save_candidate_profile


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
def _send_email(msg: MIMEMultipart):
    server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) if SMTP_PORT == 465 else smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    try:
        if SMTP_PORT != 465:
            server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)
    finally:
        server.quit()


def dispatch_node(state: GraphState) -> GraphState:
    """
    Saves the profile to MongoDB and emails the HR report (with the PDF
    statistics report attached) via SMTP.
    """
    if not state.get("hr_report") or not state.get("extracted_data"):
        return {"status": "Dispatch Skipped - Missing HR Report or Extracted Data"}

    sender_email = state.get("sender_email", "Unknown")
    applied_role = state.get("applied_role", "Unknown")
    hr_report = state.get("hr_report", "")
    hr_report_pdf_path = state.get("hr_report_pdf_path")
    extracted_data = state.get("extracted_data")
    evaluation = state.get("evaluation")

    # 1. Save state to MongoDB (both latest snapshot and history)
    profile_data = {
        "sender_email": sender_email,
        "applied_role": applied_role,
        "extracted_data": extracted_data.model_dump() if extracted_data else None,
        "evaluation": evaluation.model_dump() if evaluation else None,
        "hr_report": hr_report,
    }

    try:
        save_candidate_profile(sender_email, profile_data)
    except Exception as e:
        print(f"Failed to save to MongoDB: {e}")

    # 2. Email HR Report
    if not SMTP_EMAIL or not SMTP_PASSWORD or not HR_EMAIL:
        return {"status": "Database saved, but Email Dispatch failed due to missing credentials."}

    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_EMAIL
        msg['To'] = HR_EMAIL

        subject = f"AICTE Evaluation Report: Candidate for {applied_role}"
        if evaluation is not None and evaluation.needs_review:
            subject = f"[NEEDS REVIEW] {subject}"
        msg['Subject'] = subject

        msg.attach(MIMEText(hr_report, 'plain', 'utf-8'))

        if hr_report_pdf_path and os.path.exists(hr_report_pdf_path):
            with open(hr_report_pdf_path, "rb") as f:
                attachment = MIMEApplication(f.read(), _subtype="pdf")
            attachment.add_header(
                "Content-Disposition", "attachment", filename=os.path.basename(hr_report_pdf_path)
            )
            msg.attach(attachment)

        _send_email(msg)

        # Cleanup temporary files
        for path in (state.get("document_path"), hr_report_pdf_path):
            if path and os.path.exists(path):
                os.remove(path)

        return {"status": "Dispatch Complete - Database Saved and Email Sent"}

    except Exception as e:
        return {"status": f"Dispatch Failed: SMTP Error {e}"}
