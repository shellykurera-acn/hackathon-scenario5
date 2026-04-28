"""
Action Specialist tools — write access.

All functions return a success dict or:
  {"isError": True, "code": "...", "message": "...", "guidance": "..."}
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

_DATA = Path(__file__).parent.parent / "data"
_LOGS = Path(__file__).parent.parent.parent / "logs"

VALID_CATEGORIES = {"Network", "Security", "Hardware", "Software", "Access", "Password", "General"}
VALID_PRIORITIES = {"P1", "P2", "P3", "P4"}


def create_ticket(
    user_id: str,
    category: str,
    priority: str,
    summary: str,
    request_text: str,
) -> dict:
    """
    Creates a ticket record and returns a ticket_id.

    Does: Appends a ticket entry to logs/tickets.jsonl and returns the ticket_id.
    Does NOT: Notify the user, send email, or integrate with a live ticketing system.

    Input:
      user_id      — requester identifier
      category     — one of: Network, Security, Hardware, Software, Access, Password, General
      priority     — P1, P2, P3, or P4
      summary      — one-sentence description of the issue
      request_text — original request text

    Example: create_ticket("U001", "Network", "P2", "VPN not connecting", "My VPN keeps dropping...")
    Returns: {"ticket_id": "TKT-...", "status": "created", "priority": "P2", "queue": "Network"}
    """
    if category not in VALID_CATEGORIES:
        return {
            "isError": True,
            "code": "INVALID_CATEGORY",
            "message": f"'{category}' is not a valid category.",
            "guidance": f"Valid values: {', '.join(sorted(VALID_CATEGORIES))}",
        }
    if priority not in VALID_PRIORITIES:
        return {
            "isError": True,
            "code": "INVALID_PRIORITY",
            "message": f"'{priority}' is not a valid priority.",
            "guidance": "Valid values: P1, P2, P3, P4",
        }

    ticket_id = f"TKT-{uuid.uuid4().hex[:8].upper()}"
    ticket = {
        "ticket_id": ticket_id,
        "user_id": user_id,
        "category": category,
        "priority": priority,
        "summary": summary,
        "request_text": request_text,
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    _LOGS.mkdir(exist_ok=True)
    with open(_LOGS / "tickets.jsonl", "a") as f:
        f.write(json.dumps(ticket) + "\n")

    return {
        "ticket_id": ticket_id,
        "status": "created",
        "priority": priority,
        "queue": category,
    }


def auto_resolve(user_id: str, category: str, request_text: str) -> dict:
    """
    Auto-resolves a Password-category request with a canned response.

    Does: Logs the resolution and returns confirmation with the resolution text.
    Does NOT: Actually reset the password or unlock the account — that requires a live AD integration.
              Will return an error if called for any category other than Password.

    Input:
      user_id      — requester identifier
      category     — MUST be "Password"; any other value returns an error
      request_text — original request text

    Example: auto_resolve("U003", "Password", "My password expired and I can't log in")
    Returns: {"resolved": true, "resolution_text": "...", "ticket_id": "TKT-..."}
    """
    if category != "Password":
        return {
            "isError": True,
            "code": "AUTO_RESOLVE_NOT_SUPPORTED",
            "message": f"auto_resolve only supports category=Password. Received: '{category}'.",
            "guidance": "Use create_ticket for all other categories, or escalate_to_human if warranted.",
        }

    ticket_id = f"TKT-{uuid.uuid4().hex[:8].upper()}"
    resolution_text = (
        "Your password reset request has been received. "
        "Please visit https://aka.ms/sspr to reset your password via self-service — available 24/7. "
        "If your account is locked and SSPR does not work, call the helpdesk at ext. 5000."
    )

    record = {
        "ticket_id": ticket_id,
        "user_id": user_id,
        "category": "Password",
        "priority": "P3",
        "summary": "Auto-resolved: password reset / account unlock",
        "request_text": request_text,
        "status": "auto-resolved",
        "resolution_text": resolution_text,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    _LOGS.mkdir(exist_ok=True)
    with open(_LOGS / "tickets.jsonl", "a") as f:
        f.write(json.dumps(record) + "\n")

    return {
        "resolved": True,
        "ticket_id": ticket_id,
        "resolution_text": resolution_text,
    }


def search_knowledge_base(query: str, category: str = "") -> dict:
    """
    Searches the knowledge base and returns the top-3 matching articles.

    Does: Matches query keywords against KB article titles and keyword lists.
    Does NOT: Execute any remediation steps or modify any system.

    Input:
      query    — search string (keywords from the request)
      category — optional category filter to narrow results

    Example: search_knowledge_base("VPN not connecting", "Network")
    Returns: {"articles": [{"id": "KB-002", "title": "...", "resolution": "..."}]}
    """
    articles = json.loads((_DATA / "knowledge_base.json").read_text())
    query_lower = query.lower()

    def score(article):
        hits = sum(kw in query_lower for kw in article["keywords"])
        if category and article["category"] == category:
            hits += 2
        return hits

    ranked = sorted(articles, key=score, reverse=True)
    top = [a for a in ranked if score(a) > 0][:3]

    if not top:
        return {
            "articles": [],
            "message": "No matching KB articles found for this query.",
        }

    return {
        "articles": [
            {"id": a["id"], "category": a["category"], "title": a["title"], "resolution": a["resolution"]}
            for a in top
        ]
    }


def escalate_to_human(
    user_id: str,
    category: str,
    priority: str,
    reason: str,
    request_text: str,
) -> dict:
    """
    Flags a request for human review by writing to the escalation queue.

    Does: Appends an escalation record to logs/escalations.jsonl and returns an escalation_id.
    Does NOT: Page on-call, send SMS/email, or trigger any live alerting system.

    Input:
      user_id      — requester identifier
      category     — ticket category
      priority     — P1, P2, P3, or P4
      reason       — why escalation is needed (e.g. "low confidence", "VIP user", "P1 severity")
      request_text — original request text

    Example: escalate_to_human("U002", "Security", "P1", "Suspected breach — VIP user", "...")
    Returns: {"escalation_id": "ESC-...", "status": "escalated", "reason": "..."}
    """
    if priority not in VALID_PRIORITIES:
        return {
            "isError": True,
            "code": "INVALID_PRIORITY",
            "message": f"'{priority}' is not a valid priority.",
            "guidance": "Valid values: P1, P2, P3, P4",
        }

    escalation_id = f"ESC-{uuid.uuid4().hex[:8].upper()}"
    record = {
        "escalation_id": escalation_id,
        "user_id": user_id,
        "category": category,
        "priority": priority,
        "reason": reason,
        "request_text": request_text,
        "status": "pending_human_review",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    _LOGS.mkdir(exist_ok=True)
    with open(_LOGS / "escalations.jsonl", "a") as f:
        f.write(json.dumps(record) + "\n")

    return {
        "escalation_id": escalation_id,
        "status": "escalated",
        "priority": priority,
        "reason": reason,
    }


# Tool definitions in Claude API format — passed to the action specialist agent
ACTION_TOOL_DEFINITIONS = [
    {
        "name": "create_ticket",
        "description": (
            "Creates a ticket record and returns a ticket_id. "
            "Does NOT notify the user or integrate with a live ticketing system. "
            "Use for all requests that are not auto-resolvable and do not require escalation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id":      {"type": "string"},
                "category":     {"type": "string", "description": "One of: Network, Security, Hardware, Software, Access, Password, General"},
                "priority":     {"type": "string", "description": "P1, P2, P3, or P4"},
                "summary":      {"type": "string", "description": "One-sentence issue description"},
                "request_text": {"type": "string", "description": "Original request text"},
            },
            "required": ["user_id", "category", "priority", "summary", "request_text"],
        },
    },
    {
        "name": "auto_resolve",
        "description": (
            "Auto-resolves a Password-category request with a canned self-service response. "
            "ONLY valid for category=Password with confidence >= 0.85. "
            "Returns an error for any other category — use create_ticket instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id":      {"type": "string"},
                "category":     {"type": "string", "description": "Must be 'Password'"},
                "request_text": {"type": "string"},
            },
            "required": ["user_id", "category", "request_text"],
        },
    },
    {
        "name": "search_knowledge_base",
        "description": (
            "Returns the top-3 KB articles matching a query. "
            "Does NOT execute any remediation — for context and resolution guidance only. "
            "Optional category filter narrows results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query":    {"type": "string", "description": "Keywords from the request"},
                "category": {"type": "string", "description": "Optional category filter"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Flags a request for human review. Use when: priority=P1, confidence < 0.60, "
            "VIP user with priority <= P2, or category=Security. "
            "Does NOT page on-call or send alerts — writes to the escalation queue only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id":      {"type": "string"},
                "category":     {"type": "string"},
                "priority":     {"type": "string"},
                "reason":       {"type": "string", "description": "Why escalation is needed"},
                "request_text": {"type": "string"},
            },
            "required": ["user_id", "category", "priority", "reason", "request_text"],
        },
    },
]

ACTION_TOOL_MAP = {
    "create_ticket":          create_ticket,
    "auto_resolve":           auto_resolve,
    "search_knowledge_base":  search_knowledge_base,
    "escalate_to_human":      escalate_to_human,
}
