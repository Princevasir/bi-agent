"""The five specialist agents (demo gap D2). Each owns one job and the graph steps listed here.

The coordinator decides which agents handle a message; the graph in app/bi/service.py wires their
steps together and records each step in the answer's trace. Only the coordinator, SQL and analyst
agents call the model, and only the SQL agent touches the business database.
"""
from dataclasses import dataclass

from app.agents import analyst, chart, coordinator, knowledge, sql


@dataclass(frozen=True)
class Agent:
    name: str
    job: str
    steps: tuple


AGENTS = [
    Agent("Coordinator", coordinator.JOB, ("route", "rewrite")),
    Agent("Knowledge", knowledge.JOB, ("find_knowledge", "catalog_answer")),
    Agent("SQL", sql.JOB, ("write_sql", "second_opinion", "check_sql", "execute", "declined")),
    Agent("Analyst", analyst.JOB, ("explain", "ground", "no_rows", "explain_knowledge", "check_citations")),
    Agent("Chart", chart.JOB, ("draw", "redraw")),
]

OWNER = {step: a.name for a in AGENTS for step in a.steps}
