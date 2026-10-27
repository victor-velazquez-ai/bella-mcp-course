"""Bella's brain: turns a business question into ONE SQLite query.

Why put an AI behind an MCP tool when the client (Claude) is already an AI?
Because Bella owns the company's semantics — the glossary, the `sales` view, what
"revenue" means here. The client is generic; Bella is the domain expert.

Providers, auto-detected (same pattern as the rest of the course):
  ANTHROPIC_API_KEY -> Claude      OPENAI_API_KEY -> GPT      neither / MOCK=1 -> demo mode
Demo mode knows a handful of common questions. For anything else it says so, and
the client (Claude) simply sends SQL instead — which ask_bella also accepts.

Whatever the brain writes is UNTRUSTED: it goes through the same guard as any
other SQL (db.run_query). A model can be tricked; the guard can't be talked to.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

log = logging.getLogger("bella.brain")

SQL_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "One SQLite SELECT statement."},
            "explanation": {"type": "string", "description": "One sentence: what the query computes."},
        },
        "required": ["sql", "explanation"],
        "additionalProperties": False,
    },
}
# Claude models that support server-side refusal fallbacks.
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}

INSTRUCTIONS = """You are the SQL engine of Bella, Brightline Outdoor's data analyst.
Translate the user's question into exactly ONE read-only SQLite query.
Rules:
- SELECT (or WITH ... SELECT) only. Never modify data.
- Use the `sales` view for anything about revenue, margin, units, AOV or orders that count.
- Follow the business glossary definitions exactly.
- Round money to 2 decimals. Return at most 50 rows unless the question needs more (always add a LIMIT).
- Prefer readable column aliases (e.g. revenue, orders, margin_pct).
- If the question cannot be answered from this schema, return the query `SELECT 'not answerable' AS note`
  and explain why in `explanation`.

{schema}"""


@dataclass
class SqlDraft:
    sql: str
    explanation: str
    source: str  # anthropic | openai | demo


class BrainUnavailable(Exception):
    """The brain can't answer: the message tells the client what to do instead."""


class Brain:
    def __init__(self) -> None:
        if os.getenv("MOCK", "").strip() == "1":
            self.provider = "demo"
        elif os.getenv("ANTHROPIC_API_KEY"):
            self.provider = "anthropic"
        elif os.getenv("OPENAI_API_KEY"):
            self.provider = "openai"
        else:
            self.provider = "demo"
        default_model = {"anthropic": "claude-opus-5-5", "openai": "gpt-4.1-mini", "demo": "demo"}[self.provider]
        self.model = os.getenv("BELLA_MODEL", default_model) if self.provider != "demo" else "demo"

    def write_sql(self, question: str, schema: str) -> SqlDraft:
        if self.provider == "demo":
            return _demo_sql(question)
        system = INSTRUCTIONS.format(schema=schema)
        try:
            raw = self._anthropic(system, question) if self.provider == "anthropic" else self._openai(system, question)
            data = json.loads(raw)
            return SqlDraft(data["sql"], data.get("explanation", ""), self.provider)
        except BrainUnavailable:
            raise
        except Exception as exc:  # network, quota, bad JSON… the client can still send SQL
            log.warning("brain failed: %s", exc)
            raise BrainUnavailable(
                f"Bella's brain is unavailable right now ({type(exc).__name__}). "
                "Send a read-only SQL SELECT instead (schema: bella://schema)."
            ) from None

    def _anthropic(self, system: str, question: str) -> str:
        import anthropic

        client = anthropic.Anthropic()
        request = dict(
            model=self.model,
            max_tokens=16000,
            system=system,
            output_config={"effort": "medium", "format": SQL_FORMAT},
            messages=[{"role": "user", "content": question}],
        )
        if self.model in _FALLBACK_MODELS:
            # If the model declines, the API retries on a fallback model in the same call.
            response = client.beta.messages.create(**request, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        else:
            response = client.messages.create(**request)
        if response.stop_reason == "refusal":
            raise BrainUnavailable("Bella's brain declined this question. Rephrase it, or send SQL directly.")
        return next(block.text for block in response.content if block.type == "text")

    def _openai(self, system: str, question: str) -> str:
        from openai import OpenAI

        response = OpenAI().chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system + '\nReply as JSON: {"sql": "...", "explanation": "..."}'},
                {"role": "user", "content": question},
            ],
        )
        return response.choices[0].message.content or "{}"


# ------------------------------------------------------------------ demo mode
# Free, offline, deterministic: enough to demo the flow without an API key.
_DEMO: list[tuple[tuple[str, ...], str, str]] = [
    (("revenue", "month"),
     "SELECT month, ROUND(SUM(revenue), 2) AS revenue, COUNT(DISTINCT order_id) AS orders FROM sales GROUP BY month ORDER BY month",
     "Revenue and orders per month."),
    (("revenue", "category"),
     "SELECT category, ROUND(SUM(revenue), 2) AS revenue, ROUND(100 * SUM(margin) / SUM(revenue), 1) AS margin_pct "
     "FROM sales GROUP BY category ORDER BY revenue DESC",
     "Revenue and margin % per product category."),
    (("revenue", "region"),
     "SELECT region, ROUND(SUM(revenue), 2) AS revenue, COUNT(DISTINCT customer_id) AS customers FROM sales GROUP BY region ORDER BY revenue DESC",
     "Revenue and buying customers per region."),
    (("product",),
     "SELECT p.name, p.category, SUM(s.quantity) AS units, ROUND(SUM(s.revenue), 2) AS revenue FROM sales s "
     "JOIN products p ON p.product_id = s.product_id GROUP BY p.product_id ORDER BY revenue DESC LIMIT 10",
     "Top 10 products by revenue."),
    (("status",),
     "SELECT status, COUNT(*) AS orders FROM orders GROUP BY status ORDER BY orders DESC",
     "Number of orders per status (all orders, not only revenue)."),
    (("customers", "country"),
     "SELECT country, COUNT(*) AS customers FROM customers GROUP BY country ORDER BY customers DESC",
     "Customers per country."),
    (("customers",),
     "SELECT segment, COUNT(*) AS customers FROM customers GROUP BY segment ORDER BY customers DESC",
     "Customers per segment."),
    (("average order",),
     "SELECT substr(order_date, 1, 4) AS year, ROUND(SUM(revenue) / COUNT(DISTINCT order_id), 2) AS aov FROM sales GROUP BY year",
     "Average order value per year."),
]


def _demo_sql(question: str) -> SqlDraft:
    q = re.sub(r"\s+", " ", question.lower())
    q = q.replace("sales", "revenue").replace("aov", "average order")
    for keywords, sql, explanation in _DEMO:
        if all(k in q for k in keywords):
            return SqlDraft(sql, explanation, "demo")
    raise BrainUnavailable(
        "Bella is in demo mode (no API key), so she only understands a few questions: revenue by month / "
        "category / region, top products, orders by status, customers by country or segment, average order "
        "value. For anything else, send a read-only SQL SELECT as the question — schema in bella://schema."
    )
