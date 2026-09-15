from typing import TypedDict, Optional
from core.schemas import CandidateExtractedData, EvaluationResult

class GraphState(TypedDict, total=False):
    # Intake Node Outputs
    email_id: str
    message_id_header: str
    sender_email: str
    applied_role: str
    document_path: str
    
    # Reader Node Outputs
    raw_markdown: str
    extracted_data: Optional[CandidateExtractedData]
    
    # Evaluator Node Outputs
    evaluation: Optional[EvaluationResult]
    
    # Reporter Node Outputs
    hr_report: str
    hr_report_pdf_path: str

    # Dispatch Node Outputs
    status: str
