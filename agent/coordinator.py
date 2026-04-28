"""
Coordinator — entry point for the IT helpdesk agent.

Usage:
  python -m agent.coordinator --request "My laptop won't connect to VPN" --user-id U001
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from agent.specialists.triage_specialist import run_triage
from agent.specialists.action_specialist import run_action

_LOGS = Path(__file__).parent.parent / "logs"
_LOGS.mkdir(exist_ok=True)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class TriageResult(BaseModel):
    category: str
    priority: str
    confidence: float = Field(ge=0.0, le=1.0)
    vip_user: bool
    outage_active: bool
    reasoning: str

    def model_post_init(self, __context):
        valid_cats = {"Network", "Security", "Hardware", "Software", "Access", "Password", "General"}
        valid_pris = {"P1", "P2", "P3", "P4"}
        if self.category not in valid_cats:
            raise ValueError(f"category must be one of {valid_cats}, got '{self.category}'")
        if self.priority not in valid_pris:
            raise ValueError(f"priority must be one of {valid_pris}, got '{self.priority}'")


class ActionResult(BaseModel):
    action: str
    ticket_id: str | None = None
    escalation_id: str | None = None
    resolution_text: str | None = None
    reasoning: str

    def model_post_init(self, __context):
        valid_actions = {"auto_resolve", "create_ticket", "escalate_to_human"}
        if self.action not in valid_actions:
            raise ValueError(f"action must be one of {valid_actions}, got '{self.action}'")


# ── Validation-retry loop ─────────────────────────────────────────────────────

def _validate_with_retry(specialist_fn, schema_cls, max_retries=3, **kwargs):
    """
    Calls specialist_fn(**kwargs), validates output against schema_cls.
    On failure, feeds the validation error back and retries up to max_retries times.
    Returns (validated_result, retry_count, last_error).
    """
    last_error = None
    extra_context = ""

    for attempt in range(max_retries + 1):
        if extra_context:
            kwargs = {**kwargs, "_validation_feedback": extra_context}

        raw = specialist_fn(**{k: v for k, v in kwargs.items() if not k.startswith("_")})

        try:
            validated = schema_cls(**raw)
            return validated, attempt, None
        except (ValidationError, Exception) as e:
            last_error = str(e)
            extra_context = f"Previous output failed validation: {last_error}. Please correct and retry."

    return None, max_retries, last_error


# ── Decision log ──────────────────────────────────────────────────────────────

def _log_decision(entry: dict):
    with open(_LOGS / "decisions.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── Main coordinator ──────────────────────────────────────────────────────────

def process_request(request_text: str, user_id: str = "UNKNOWN", channel: str = "cli") -> dict:
    """
    Ingests a request, runs triage + action specialists, logs the decision.
    Returns the final decision dict.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    log_entry = {
        "started_at": started_at,
        "user_id": user_id,
        "channel": channel,
        "request_text": request_text,
    }

    # ── Step 1: Triage ────────────────────────────────────────────────────────
    triage, triage_retries, triage_error = _validate_with_retry(
        run_triage,
        TriageResult,
        user_id=user_id,
        channel=channel,
        request_text=request_text,
    )

    log_entry["triage_retries"] = triage_retries
    log_entry["triage_error"] = triage_error

    if triage is None:
        log_entry["status"] = "failed_triage"
        log_entry["action"] = "escalate_to_human"
        log_entry["completed_at"] = datetime.now(timezone.utc).isoformat()
        _log_decision(log_entry)
        return {
            "status": "error",
            "action": "escalate_to_human",
            "reason": f"Triage failed after {triage_retries} retries: {triage_error}",
        }

    log_entry["triage"] = triage.model_dump()

    # ── Step 2: Action ────────────────────────────────────────────────────────
    action, action_retries, action_error = _validate_with_retry(
        run_action,
        ActionResult,
        user_id=user_id,
        category=triage.category,
        priority=triage.priority,
        confidence=triage.confidence,
        vip_user=triage.vip_user,
        outage_active=triage.outage_active,
        request_text=request_text,
    )

    log_entry["action_retries"] = action_retries
    log_entry["action_error"] = action_error

    if action is None:
        log_entry["status"] = "failed_action"
        log_entry["completed_at"] = datetime.now(timezone.utc).isoformat()
        _log_decision(log_entry)
        return {
            "status": "error",
            "action": "escalate_to_human",
            "reason": f"Action failed after {action_retries} retries: {action_error}",
        }

    log_entry["action"] = action.model_dump()
    log_entry["status"] = "completed"
    log_entry["completed_at"] = datetime.now(timezone.utc).isoformat()
    _log_decision(log_entry)

    return {
        "status": "ok",
        "category": triage.category,
        "priority": triage.priority,
        "confidence": triage.confidence,
        "action": action.action,
        "ticket_id": action.ticket_id,
        "escalation_id": action.escalation_id,
        "resolution_text": action.resolution_text,
        "triage_reasoning": triage.reasoning,
        "action_reasoning": action.reasoning,
    }


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IT Helpdesk Agent")
    parser.add_argument("--request", required=True, help="The support request text")
    parser.add_argument("--user-id", default="UNKNOWN", help="User identifier (e.g. U001)")
    parser.add_argument("--channel", default="cli", help="Inbound channel (cli, email, chat, ticket)")
    args = parser.parse_args()

    result = process_request(args.request, user_id=args.user_id, channel=args.channel)

    print("\n--- Decision -------------------------------------------")
    print(json.dumps(result, indent=2))
