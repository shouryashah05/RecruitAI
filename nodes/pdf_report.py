"""
pdf_report.py — renders the candidate's evaluation as a statistics-driven PDF
(score breakdown chart, candidate-vs-requirement comparison, decision banner,
audit trail) for HR. This is presentation only: every number on the page
comes straight from the deterministic EvaluationResult, never re-derived here.
"""
import io
import os
import uuid

import matplotlib
matplotlib.use("Agg")  # headless — no display available on a server
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak,
)

from core.schemas import CandidateExtractedData, EvaluationResult
from graph.state import GraphState

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "temp", "reports")

DECISION_COLOR_HEX = {
    "Retain": "#1B8A5A",
    "Downgrade": "#C77800",
    "Reject": "#B00020",
}
DECISION_COLORS_RL = {name: colors.HexColor(hexval) for name, hexval in DECISION_COLOR_HEX.items()}

REQUIREMENT_METRICS = {
    "Assistant Professor": [],  # boolean/degree-driven, no numeric bars worth plotting
    "Associate Professor": [
        ("Total Experience (yrs)", "total_experience_years", 8),
        ("Post-Ph.D. Experience (yrs)", "post_phd_experience_years", 2),
        ("Publications", "publications_count", 6),
    ],
    "Professor": [
        ("Total Experience (yrs)", "total_experience_years", 10),
        ("Publications (Assoc. level)", "publications_at_associate_level", 6),
        ("Ph.D. Students Guided", "phd_students_guided", 2),
        ("Total Publications", "publications_count", 10),
    ],
}


def _fig_to_image(fig, width_cm=15.5) -> Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return Image(buf, width=width_cm * cm, height=width_cm * cm * 0.55)


def _score_breakdown_chart(evaluation: EvaluationResult) -> Image | None:
    if not evaluation.score_breakdown:
        return None
    labels = [k.replace("_", " ").title() for k in evaluation.score_breakdown]
    values = list(evaluation.score_breakdown.values())

    fig, ax = plt.subplots(figsize=(8, 4.4))
    bars = ax.barh(labels, values, color="#2E6F9E")
    ax.set_xlabel("Points contributed (of 100)")
    ax.set_title(f"Comparative Score Breakdown — Total: {evaluation.comparative_score}/100")
    ax.bar_label(bars, fmt="%.1f", padding=3)
    ax.set_xlim(0, max(values + [1]) * 1.25)
    fig.tight_layout()
    return _fig_to_image(fig)


def _requirements_chart(data: CandidateExtractedData, evaluation: EvaluationResult) -> Image | None:
    role = evaluation.qualified_role or evaluation.applied_role
    metrics = REQUIREMENT_METRICS.get(role, [])
    if not metrics:
        return None

    labels, candidate_vals, required_vals = [], [], []
    for label, attr, required in metrics:
        value = getattr(data, attr, 0)
        value = value() if callable(value) else value
        labels.append(label)
        candidate_vals.append(value)
        required_vals.append(required)

    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(8, 4.4))
    width = 0.35
    ax.bar([i - width / 2 for i in x], candidate_vals, width, label="Candidate", color="#2E6F9E")
    ax.bar([i + width / 2 for i in x], required_vals, width, label="Required", color="#B5B5B5")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_title(f"Candidate vs. Requirements — {role}")
    ax.legend()
    fig.tight_layout()
    return _fig_to_image(fig)


def _score_gauge(evaluation: EvaluationResult) -> Image:
    score = evaluation.comparative_score
    fig, ax = plt.subplots(figsize=(4, 4), subplot_kw={"projection": "polar"})
    ax.set_theta_offset(3.14159)
    ax.set_theta_direction(-1)
    ax.set_thetamin(0)
    ax.set_thetamax(180)

    ax.barh(0, 3.14159, color="#E6E6E6", height=1.0)
    ax.barh(0, 3.14159 * (score / 100), color=DECISION_COLOR_HEX.get(evaluation.decision, "#2E6F9E"), height=1.0)
    ax.set_yticklabels([])
    ax.set_xticklabels([])
    ax.spines.clear()
    ax.text(0, -0.35, f"{score:.1f}", ha="center", va="center", fontsize=22, fontweight="bold",
             transform=ax.transData)
    ax.set_title("Comparative Score", pad=20)
    fig.tight_layout()
    return _fig_to_image(fig, width_cm=8)


def generate_pdf_report(
    data: CandidateExtractedData,
    evaluation: EvaluationResult,
    hr_narrative: str,
    output_path: str,
) -> str:
    """Builds the PDF at output_path and returns that path."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleBig", parent=styles["Title"], fontSize=20)
    banner_style = ParagraphStyle(
        "Banner", parent=styles["Heading1"], fontSize=16, textColor=colors.white,
        alignment=1, spaceBefore=6, spaceAfter=6,
    )
    body = styles["BodyText"]

    story = []

    story.append(Paragraph("AICTE Faculty Evaluation Report", title_style))
    story.append(Spacer(1, 0.3 * cm))

    decision_color = DECISION_COLORS_RL.get(evaluation.decision, colors.grey)
    decision_text = f"DECISION: {evaluation.decision.upper()}"
    if evaluation.decision == "Downgrade":
        decision_text += f" → Qualifies for {evaluation.qualified_role}"
    banner = Table([[Paragraph(decision_text, banner_style)]], colWidths=[17 * cm])
    banner.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), decision_color), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(banner)
    story.append(Spacer(1, 0.4 * cm))

    if evaluation.needs_review:
        review_text = (
            "NEEDS HUMAN REVIEW — the resume extraction looked incomplete or suspicious: "
            + "; ".join(evaluation.review_reasons)
        )
        review_banner = Table([[Paragraph(review_text, ParagraphStyle("Review", parent=body, textColor=colors.white))]], colWidths=[17 * cm])
        review_banner.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#8A6D00")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0,0), (-1,-1), 8), ("BOTTOMPADDING", (0,0), (-1,-1), 8)]))
        story.append(review_banner)
        story.append(Spacer(1, 0.4 * cm))

    info_rows = [
        ["Candidate", data.candidate_name],
        ["Email", data.email or "—"],
        ["Phone", data.phone or "—"],
        ["Applied Role", evaluation.applied_role],
        ["Satisfied Path", evaluation.satisfied_path or "—"],
    ]
    info_table = Table(info_rows, colWidths=[4.5 * cm, 12.5 * cm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.5 * cm))

    story.append(Paragraph("Statistics", styles["Heading2"]))
    gauge = _score_gauge(evaluation)
    story.append(gauge)

    breakdown_chart = _score_breakdown_chart(evaluation)
    if breakdown_chart:
        story.append(breakdown_chart)
        story.append(Spacer(1, 0.3 * cm))

    requirements_chart = _requirements_chart(data, evaluation)
    if requirements_chart:
        story.append(requirements_chart)
        story.append(Spacer(1, 0.3 * cm))

    if evaluation.failing_criteria:
        story.append(Paragraph("Failing Criteria", styles["Heading2"]))
        for item in evaluation.failing_criteria:
            story.append(Paragraph(f"• {item}", body))
        story.append(Spacer(1, 0.3 * cm))

    story.append(PageBreak())
    story.append(Paragraph("HR Summary", styles["Heading2"]))
    for paragraph in (hr_narrative or "No narrative summary generated.").split("\n\n"):
        if paragraph.strip():
            story.append(Paragraph(paragraph.strip().replace("\n", "<br/>"), body))
            story.append(Spacer(1, 0.2 * cm))

    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph("Extracted Resume Data (audit trail)", styles["Heading2"]))
    extracted_rows = [[k.replace("_", " ").title(), str(v)] for k, v in data.model_dump().items() if k != "resume_markdown_excerpt"]
    extracted_table = Table(extracted_rows, colWidths=[7 * cm, 10 * cm])
    extracted_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#EEEEEE")),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#F7F7F7")]),
    ]))
    story.append(extracted_table)

    doc.build(story)
    return output_path


def pdf_report_node(state: GraphState) -> GraphState:
    """LangGraph node: renders the PDF from state and stores its path."""
    extracted_data = state.get("extracted_data")
    evaluation = state.get("evaluation")

    if not extracted_data or not evaluation:
        return {"status": "PDF report skipped - missing extracted data or evaluation"}

    os.makedirs(REPORTS_DIR, exist_ok=True)
    filename = f"{state.get('email_id', uuid.uuid4().hex)}_report.pdf"
    output_path = os.path.join(REPORTS_DIR, filename)

    try:
        generate_pdf_report(
            extracted_data, evaluation, state.get("hr_report", ""), output_path
        )
    except Exception as e:
        return {"status": f"PDF Report Error: {e}"}

    return {"hr_report_pdf_path": output_path}
