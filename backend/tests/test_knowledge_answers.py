"""Demo gap D7 (RAG R6b): business questions answered from the knowledge documents, with citations, no SQL."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.agents.coordinator import is_about_knowledge
from app.agents.analyst import knowledge_prompt
from app.bi import service
from app.knowledge.retrieval import Hit
from app.llm import get_llm
from app.main import app, get_knowledge
from routed_llm import RoutedLLM

TODAY = date(2026, 10, 24)
REVENUE = ("Revenue (metric, Sales, owner Sales Analytics, version 2)\n"
           "Revenue is the sum of order_items.line_total for completed orders. Cancelled orders are excluded.")
FISCAL = "Fiscal calendar (rule)\nThe fiscal year runs from 1 February to 31 January; FY2025 starts on 1 February 2025."


def hit(doc_id, content, title="Revenue", doc_type="metric"):
    return Hit(chunk_id=f"{doc_id}#0", document_id=doc_id, title=title, doc_type=doc_type, owner="Sales Analytics",
               version=2, source="x.md", content=content, token_count=40, score=0.8)


HITS = [hit("metric-revenue", REVENUE), hit("rule-fiscal-calendar", FISCAL, "Fiscal calendar", "rule")]


def ask(question, llm, knowledge=lambda q, role: HITS):
    return service.answer_question(question, lambda p: llm.generate(p).text, TODAY, knowledge=knowledge)


def steps(out):
    return [(s["agent"], s["step"]) for s in out["trace"]]


# ---- which questions are about the business, not the data ------------------------------------------------

@pytest.mark.parametrize("text", [
    "How is revenue defined?", "How do we calculate average order value?", "What does active customer mean?",
    "What counts as a repeat customer?", "When does the fiscal year start?", "What is our returns policy?",
    "Why did tent sales dip in March 2026?", "What happened with the Ridgeline headlamp recall?",
    "Who owns the orders data?", "What is the definition of net revenue?", "Explain the stock-out week metric",
])
def test_business_questions_are_recognised(text):
    assert is_about_knowledge(text)


@pytest.mark.parametrize("text", [
    "What was revenue in 2025?", "How many orders were cancelled in 2025?", "Revenue by region",
    "What tables can I see?", "Which metrics are defined?", "Show me the top 10 products by revenue",
    "make it a pie chart", "hello", "How is revenue trending this year?",
])
def test_data_questions_are_not(text):
    assert not is_about_knowledge(text)


# ---- answering from the documents -------------------------------------------------------------------------

def test_a_definition_is_answered_from_the_documents_with_a_citation():
    llm = RoutedLLM("SELECT 1", answer="Revenue is the sum of line totals for completed orders [metric-revenue].")
    out = ask("How is revenue defined?", llm)
    assert out["route"] == "knowledge" and out["answer_source"] == "knowledge"
    assert out["sql"] == "" and out["rows"] == [] and out["chart"] is None
    assert "[metric-revenue]" in out["answer"]
    assert not any(p.startswith("You write PostgreSQL") for p in llm.prompts)       # no SQL at all
    assert steps(out) == [("Coordinator", "route"), ("Knowledge", "find_knowledge"),
                          ("Analyst", "explain_knowledge"), ("Analyst", "check_citations")]
    assert [s["document_id"] for s in out["sources"]] == ["metric-revenue", "rule-fiscal-calendar"]


def test_the_prompt_fences_the_documents_and_asks_for_citations():
    prompt = knowledge_prompt("How is revenue defined?", HITS)
    assert "not instructions" in prompt and "<<<knowledge" in prompt and "[metric-revenue]" in prompt
    assert "NOT_FOUND" in prompt and not prompt.startswith(("Rewrite", "You write PostgreSQL"))


def test_an_answer_without_a_citation_falls_back_to_the_best_excerpt():
    out = ask("How is revenue defined?", RoutedLLM("SELECT 1", answer="Revenue is money."))
    assert out["answer_source"] == "knowledge_excerpt"
    assert out["answer"].startswith("From Revenue (metric, version 2):")
    assert "Cancelled orders are excluded." in out["answer"]


def test_a_citation_of_a_document_that_was_not_retrieved_does_not_count():
    out = ask("How is revenue defined?", RoutedLLM("SELECT 1", answer="Revenue is everything [made-up-doc]."))
    assert out["answer_source"] == "knowledge_excerpt"


def test_a_number_that_is_not_in_the_documents_falls_back():
    llm = RoutedLLM("SELECT 1", answer="Revenue grew 17% last year [metric-revenue].")
    assert ask("How is revenue defined?", llm)["answer_source"] == "knowledge_excerpt"


def test_numbers_from_the_documents_are_fine():
    llm = RoutedLLM("SELECT 1", answer="The fiscal year starts on 1 February; FY2025 began in 2025 [rule-fiscal-calendar].")
    assert ask("When does the fiscal year start?", llm)["answer_source"] == "knowledge"


def test_not_found_says_so_plainly():
    out = ask("What is our returns policy?", RoutedLLM("SELECT 1", answer="NOT_FOUND"))
    assert out["answer_source"] == "fallback" and "couldn't find" in out["answer"]


# ---- when there is no knowledge, nothing changes ---------------------------------------------------------

def test_without_documents_a_metric_question_gets_the_catalog_answer():
    llm = RoutedLLM("SELECT 1")
    out = ask("How is revenue defined?", llm, knowledge=lambda q, role: [])
    assert out["route"] == "catalog" and out["answer_source"] == "catalog" and llm.prompts == []


@pytest.mark.integration
def test_without_documents_other_business_questions_go_to_sql():
    llm = RoutedLLM("SELECT count(*) AS n FROM orders WHERE status = 'cancelled'", answer="There were 2.")
    out = ask("Why did orders get cancelled?", llm, knowledge=lambda q, role: [])
    assert out["route"] == "data" and any(p.startswith("You write PostgreSQL") for p in llm.prompts)


def test_without_a_knowledge_function_the_route_is_never_knowledge():
    out = service.answer_question("How is revenue defined?", lambda p: "", TODAY)
    assert out["route"] == "catalog"


# ---- the API ---------------------------------------------------------------------------------------------------

def test_ask_audits_a_knowledge_answer_with_its_sources(audit_events):
    app.dependency_overrides[get_llm] = lambda: RoutedLLM("SELECT 1", answer="Completed orders only [metric-revenue].")
    app.dependency_overrides[get_knowledge] = lambda: (lambda q, role: HITS)
    try:
        body = TestClient(app).post("/ask", json={"message": "How is revenue defined?"}).json()
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert body["route"] == "knowledge" and body["answer_source"] == "knowledge"
    event = audit_events[-1]
    assert event["event"] == "knowledge_question" and event["detail"]["sources"] == ["metric-revenue",
                                                                                    "rule-fiscal-calendar"]


def test_the_excerpt_reads_as_plain_text():
    md = ("Revenue (metric, Sales, owner Sales Analytics, version 2)\n# Revenue\n\n"
          "**Revenue is the money customers paid.** Formula: `SUM(order_items.line_total)`.\n- Cancelled orders are never revenue.")
    out = ask("How is revenue defined?", RoutedLLM("SELECT 1", answer="no citation"),
              knowledge=lambda q, role: [hit("metric-revenue", md)])
    text = out["answer"]
    assert "**" not in text and "`" not in text and "# " not in text and "\n" not in text
    assert "Revenue is the money customers paid. Formula: SUM(order_items.line_total)." in text
    assert "Cancelled orders are never revenue." in text


def test_the_prompt_asks_for_a_citation_on_every_sentence():
    assert "End every sentence with the id of the document" in knowledge_prompt("q", HITS)
