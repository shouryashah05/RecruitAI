from langchain_core.messages import SystemMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from tenacity import retry, stop_after_attempt, wait_exponential
from graph.state import GraphState
from config.settings import GEMINI_API_KEY, GEMINI_MODEL


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
def _invoke_llm(llm, messages):
    return llm.invoke(messages)


def reporter_node(state: GraphState) -> GraphState:
    """
    Generates a professional 3-paragraph Markdown HR narrative summarizing the
    candidate. This text is prose only — it never decides eligibility; that
    was already settled deterministically by the Evaluator node.
    """
    extracted_data = state.get("extracted_data")
    evaluation = state.get("evaluation")

    if not extracted_data or not evaluation:
        return {"status": "Reporter skipped - missing extracted data or evaluation"}

    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=GEMINI_API_KEY,
        temperature=0.7
    )

    sys_msg = SystemMessage(
        content="You are an expert AI HR assistant for a technical university. "
                "Write a concise, professional 3-paragraph Markdown HR report for a candidate. "
                "The eligibility decision and all numbers are already final and provided to you — "
                "report them faithfully, do not second-guess or recompute them."
    )

    user_msg = HumanMessage(
        content=f"""
        Please write a 3-paragraph HR report based on the following extracted data and evaluation result.

        Extracted Data:
        {extracted_data.model_dump_json(indent=2)}

        Evaluation Result:
        {evaluation.model_dump_json(indent=2)}

        Format requirements:
        - Paragraph 1: Candidate summary and applied role.
        - Paragraph 2: Core qualifications, experience, and research highlighting.
        - Paragraph 3: AICTE eligibility decision (Retain/Downgrade/Reject), comparative score, and reasoning.
        """
    )

    try:
        response = _invoke_llm(llm, [sys_msg, user_msg])
    except Exception as e:
        return {"status": f"Reporter Error: LLM narrative generation failed - {e}"}

    return {
        "hr_report": response.content
    }
