import os
from llama_parse import LlamaParse
from langchain_google_genai import ChatGoogleGenerativeAI
from tenacity import retry, stop_after_attempt, wait_exponential
from graph.state import GraphState
from core.schemas import CandidateExtractedData
from config.settings import LLAMAPARSE_API_KEY, GEMINI_API_KEY, GEMINI_MODEL


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
def _parse_document(document_path: str) -> str:
    parser = LlamaParse(api_key=LLAMAPARSE_API_KEY, result_type="markdown")
    documents = parser.load_data(document_path)
    return "\n".join([doc.text for doc in documents])


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
def _extract_structured_data(prompt: str) -> CandidateExtractedData:
    llm = ChatGoogleGenerativeAI(model=GEMINI_MODEL, google_api_key=GEMINI_API_KEY, temperature=0)
    structured_llm = llm.with_structured_output(CandidateExtractedData)
    return structured_llm.invoke(prompt)


def reader_node(state: GraphState) -> GraphState:
    """
    Parses the PDF resume and extracts structured data using LlamaParse and Gemini.
    Only the FACTS (schema fields) come from the LLM here — no eligibility
    decision is made in this node.
    """
    document_path = state.get("document_path")
    applied_role = state.get("applied_role", "")

    if not document_path or not os.path.exists(document_path):
        return {"status": f"Reader Error: document not found at {document_path}"}

    try:
        raw_markdown = _parse_document(document_path)
    except Exception as e:
        return {"status": f"Reader Error: document parsing failed - {e}"}

    prompt = f"""
    You are an expert HR data extractor. Extract the candidate's qualifications from the following resume markdown.
    The candidate applied for the role: {applied_role}.

    Make sure to accurately determine:
    - B.Tech/M.Tech/Ph.D presence
    - First class degrees (usually >= 60% or First Division)
    - Total teaching/research experience years
    - Post-Ph.D experience years
    - Publication counts (total and while Associate Professor)
    - Number of Ph.D students guided
    - A short verbatim excerpt (<= 500 chars) of the key qualifications section for resume_markdown_excerpt

    Resume Markdown:
    {raw_markdown}
    """

    try:
        extracted_data = _extract_structured_data(prompt)
    except Exception as e:
        return {"status": f"Reader Error: structured extraction failed - {e}", "raw_markdown": raw_markdown}

    # Ensure applied_role is preserved if extraction misses it
    if applied_role and (not extracted_data.applied_role or extracted_data.applied_role.strip() == ""):
        extracted_data.applied_role = applied_role

    return {
        "raw_markdown": raw_markdown,
        "extracted_data": extracted_data
    }
