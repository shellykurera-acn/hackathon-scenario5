"""
Triage Specialist tools — read-only. No side effects.

All functions return a success dict or:
  {"isError": True, "code": "...", "message": "...", "guidance": "..."}
"""

import json
from pathlib import Path

_DATA = Path(__file__).parent.parent / "data"

VALID_CATEGORIES = {"Network", "Security", "Hardware", "Software", "Access", "Password", "General"}


def classify_request(text: str) -> dict:
    """
    Classifies an IT support request into a category.

    Does: Returns a category from the fixed enum and a confidence score (0.0–1.0).
    Does NOT: Assign priority, create records, or take any action.

    Input: Free-text request string (the raw ticket / email / chat message).
    Example: classify_request("I can't log into my laptop — says my password is expired")
    Returns: {"category": "Password", "confidence": 0.95, "reasoning": "..."}
    """
    text_lower = text.lower()

    scores = {
        "Password": sum(w in text_lower for w in ["password", "reset", "locked", "expired", "login", "forgot", "unlock", "account"]),
        "Network":  sum(w in text_lower for w in ["vpn", "network", "internet", "wifi", "wi-fi", "connection", "dns", "ping"]),
        "Security": sum(w in text_lower for w in ["phishing", "malware", "virus", "breach", "suspicious", "ransomware", "hack", "mfa"]),
        "Hardware": sum(w in text_lower for w in ["laptop", "printer", "monitor", "keyboard", "mouse", "power", "screen", "battery", "hardware"]),
        "Software": sum(w in text_lower for w in ["software", "install", "crash", "error", "teams", "office", "update", "application", "app"]),
        "Access":   sum(w in text_lower for w in ["access", "permission", "share", "drive", "folder", "sharepoint", "denied", "role"]),
    }

    best = max(scores, key=scores.get)
    best_score = scores[best]

    if best_score == 0:
        return {"category": "General", "confidence": 0.50, "reasoning": "No strong keyword signal — defaulting to General."}

    total = sum(scores.values()) or 1
    confidence = round(min(0.95, 0.55 + (best_score / total) * 0.5), 2)

    return {
        "category": best,
        "confidence": confidence,
        "reasoning": f"Keyword matches: {best_score} signals for '{best}' out of {total} total.",
    }


def score_priority(category: str, user_message: str, vip_user: bool = False, outage_active: bool = False) -> dict:
    """
    Assigns a priority (P1–P4) to a classified request.

    Does: Returns priority and confidence given the category, message content, VIP flag, and outage state.
    Does NOT: Create or update any record.

    Input:
      category     — one of: Network, Security, Hardware, Software, Access, Password, General
      user_message — original request text
      vip_user     — True if the requester is flagged as VIP in the user profile
      outage_active — True if a known outage exists for this category

    Example: score_priority("Network", "VPN is down for the whole floor", vip_user=False, outage_active=True)
    Returns: {"priority": "P2", "confidence": 0.88, "reasoning": "..."}
    """
    if category not in VALID_CATEGORIES:
        return {
            "isError": True,
            "code": "INVALID_CATEGORY",
            "message": f"'{category}' is not a valid category.",
            "guidance": f"Valid values: {', '.join(sorted(VALID_CATEGORIES))}",
        }

    msg = user_message.lower()

    p1_signals = ["production down", "all users", "entire floor", "company-wide", "critical outage", "breach", "ransomware", "data loss"]
    p2_signals = ["team affected", "multiple users", "several people", "department", "outage", "degraded", "urgent"]
    p4_signals = ["when you get a chance", "not urgent", "low priority", "minor", "cosmetic", "toner", "mouse", "keyboard"]

    if category == "Security" or any(s in msg for s in p1_signals):
        base_priority = "P1"
    elif outage_active or any(s in msg for s in p2_signals) or vip_user:
        base_priority = "P2"
    elif any(s in msg for s in p4_signals):
        base_priority = "P4"
    elif category == "Password":
        base_priority = "P3"
    else:
        base_priority = "P3"

    confidence = 0.82
    if category == "Security":
        confidence = 0.90
    elif vip_user:
        confidence = 0.88

    return {
        "priority": base_priority,
        "confidence": round(confidence, 2),
        "reasoning": f"Category={category}, vip={vip_user}, outage={outage_active}. Signals matched for {base_priority}.",
    }


def lookup_user_profile(user_id: str) -> dict:
    """
    Returns a user's profile from the mock user store.

    Does: Returns name, role, VIP flag, and open ticket count.
    Does NOT: Query Active Directory or any live system. Data is static mock data.

    Input: user_id — string identifier (e.g. "U001"). Use "UNKNOWN" if user_id is not provided.
    Example: lookup_user_profile("U002")
    Returns: {"user_id": "U002", "name": "Bob Martinez", "role": "VP of Engineering", "vip": true, "open_tickets": 0}
    """
    users = json.loads((_DATA / "users.json").read_text())
    profile = users.get(user_id, users.get("UNKNOWN"))

    if profile is None:
        return {
            "isError": True,
            "code": "USER_NOT_FOUND",
            "message": f"No profile found for user_id '{user_id}'.",
            "guidance": "Use 'UNKNOWN' as user_id when the requester cannot be identified.",
        }

    return {"user_id": user_id, **profile}


def check_known_outage(category: str) -> dict:
    """
    Checks whether there is an active known outage for a given category.

    Does: Returns active outage flag, outage ID, severity, and summary if one exists.
    Does NOT: Check individual device status, resolve outages, or create alerts.

    Input: category — one of: Network, Security, Hardware, Software, Access, Password, General
    Example: check_known_outage("Network")
    Returns: {"outage_active": true, "outage_id": "OUT-001", "severity": "P2", "summary": "VPN gateway degraded..."}
    """
    if category not in VALID_CATEGORIES:
        return {
            "isError": True,
            "code": "INVALID_CATEGORY",
            "message": f"'{category}' is not a valid category.",
            "guidance": f"Valid values: {', '.join(sorted(VALID_CATEGORIES))}",
        }

    outages = json.loads((_DATA / "outages.json").read_text())
    active = [o for o in outages if o["active"] and o["category"] == category]

    if not active:
        return {"outage_active": False, "category": category}

    o = active[0]
    return {
        "outage_active": True,
        "outage_id": o["id"],
        "severity": o["severity"],
        "summary": o["summary"],
        "category": category,
    }


# Tool definitions in Claude API format — passed to the specialist agent
TRIAGE_TOOL_DEFINITIONS = [
    {
        "name": "classify_request",
        "description": (
            "Classifies an IT support request into a category (Network, Security, Hardware, "
            "Software, Access, Password, General) and returns a confidence score. "
            "Does NOT assign priority or create any records. "
            "Call this first, before score_priority."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The raw request text to classify."},
            },
            "required": ["text"],
        },
    },
    {
        "name": "score_priority",
        "description": (
            "Assigns a priority (P1–P4) to a classified request based on category, message "
            "content, VIP status, and whether a known outage is active. "
            "Does NOT create or update any records. "
            "Call after classify_request and lookup_user_profile."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category":      {"type": "string", "description": "Category from classify_request."},
                "user_message":  {"type": "string", "description": "Original request text."},
                "vip_user":      {"type": "boolean", "description": "True if the user is VIP."},
                "outage_active": {"type": "boolean", "description": "True if an outage is active for this category."},
            },
            "required": ["category", "user_message"],
        },
    },
    {
        "name": "lookup_user_profile",
        "description": (
            "Returns a user's name, role, VIP flag, and open ticket count from the mock store. "
            "Does NOT query Active Directory or any live system. "
            "Use 'UNKNOWN' if the user_id is not available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "User identifier, e.g. 'U001'. Use 'UNKNOWN' if not known."},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "check_known_outage",
        "description": (
            "Checks whether an active known outage exists for a given category. "
            "Returns outage flag, severity, and summary if found. "
            "Does NOT check individual device or host status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Category to check, e.g. 'Network'."},
            },
            "required": ["category"],
        },
    },
]

TRIAGE_TOOL_MAP = {
    "classify_request":   classify_request,
    "score_priority":     score_priority,
    "lookup_user_profile": lookup_user_profile,
    "check_known_outage": check_known_outage,
}
