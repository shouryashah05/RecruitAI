from langgraph.graph import StateGraph, END
from graph.state import GraphState

from nodes.intake import intake_node
from nodes.reader import reader_node
from nodes.evaluator import evaluate_candidate
from nodes.reporter import reporter_node
from nodes.pdf_report import pdf_report_node
from nodes.dispatch import dispatch_node

def evaluator_node(state: GraphState) -> GraphState:
    """Wrapper for the deterministic evaluator node."""
    extracted = state.get("extracted_data")
    if not extracted:
        return {"status": "Evaluator skipped - no extracted data"}
    
    eval_result = evaluate_candidate(extracted)
    return {"evaluation": eval_result}

def should_process(state: GraphState) -> str:
    """Conditional edge logic after intake."""
    if state.get("document_path"):
        return "reader"
    return "end"

def build_workflow(checkpointer=None):
    """Compiles and returns the LangGraph workflow.

    A checkpointer (e.g. a SqliteSaver) lets a crash mid-pipeline resume from
    the last completed node on the next `invoke` with the same thread_id,
    instead of silently losing the candidate.
    """
    builder = StateGraph(GraphState)

    # Add Nodes
    builder.add_node("intake", intake_node)
    builder.add_node("reader", reader_node)
    builder.add_node("evaluator", evaluator_node)
    builder.add_node("reporter", reporter_node)
    builder.add_node("pdf_report", pdf_report_node)
    builder.add_node("dispatch", dispatch_node)

    # Set Entry Point
    builder.set_entry_point("intake")

    # Add Edges with conditional routing
    builder.add_conditional_edges(
        "intake",
        should_process,
        {
            "reader": "reader",
            "end": END
        }
    )

    builder.add_edge("reader", "evaluator")
    builder.add_edge("evaluator", "reporter")
    builder.add_edge("reporter", "pdf_report")
    builder.add_edge("pdf_report", "dispatch")
    builder.add_edge("dispatch", END)

    return builder.compile(checkpointer=checkpointer)
