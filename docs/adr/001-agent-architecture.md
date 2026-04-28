# ADR-001: IT Helpdesk Agent Architecture

**Status:** Accepted  
**Date:** 2026-04-28  
**Scenario:** Hackathon Scenario 5 — The Intake

---

## Context

Inbound IT support requests arrive through multiple channels (ticket portal, email, chat). A
human triages each one: reads it, assigns a priority (P1–P4), picks a queue
(Network / Security / Hardware / Software / Access / Password / General), and decides whether
to auto-resolve, create a ticket, or escalate to a specialist. At 200+ requests per day this
is a bottleneck. We want an agent that makes those decisions reliably, logs its reasoning, and
hands off to a human when confidence is low or the stakes are high.

The agent must:
- Classify every request into a category and priority
- Auto-resolve trivial requests (password resets, account unlocks)
- Create a tracked ticket for everything else
- Escalate to a human for high-risk or low-confidence cases
- Log the full reasoning chain so every decision is replayable from the log alone

---

## Decision

**Coordinator + two specialist subagents, connected via the Claude Agent SDK.**

```
                    ┌─────────────────────────────────────────────┐
                    │                COORDINATOR                  │
                    │                                             │
inbound request ───►│  1. parse & normalise request               │
                    │  2. call Triage Specialist (Task)           │
                    │  3. validate triage output  (Pydantic)  ◄───┼── retry up to 3x
                    │  4. call Action Specialist  (Task)          │
                    │  5. validate action output  (Pydantic)  ◄───┼── retry up to 3x
                    │  6. append to decisions.jsonl               │
                    │  7. return final decision to caller         │
                    └─────────────────────────────────────────────┘
                               │                    │
               ┌───────────────▼────────┐  ┌────────▼──────────────┐
               │   TRIAGE SPECIALIST    │  │   ACTION SPECIALIST   │
               │  (read-only tools)     │  │  (write tools)        │
               │                        │  │                       │
               │  classify_request      │  │  create_ticket        │
               │  score_priority        │  │  auto_resolve         │
               │  lookup_user_profile   │  │  search_knowledge_    │
               │  check_known_outage    │  │    base               │
               │                        │  │  escalate_to_human    │
               └────────────────────────┘  └───────────────────────┘
```

---

## Agent Loop and stop_reason Handling

The coordinator runs an agentic loop driven by the Claude Agent SDK. After each API call
the loop inspects `stop_reason` and decides what to do next:

| stop_reason     | What it means                              | Coordinator action                                        |
|-----------------|--------------------------------------------|-----------------------------------------------------------|
| `tool_use`      | Model wants to call one or more tools      | Execute every requested tool, feed results back, continue |
| `end_turn`      | Model is done; final answer is ready       | Extract structured output, validate against schema, break |
| `max_tokens`    | Response was cut off mid-generation        | Log a warning, feed "response truncated — please continue" back, retry once |
| `stop_sequence` | Hit a custom stop token                    | Treat the same as `end_turn`; extract what came before the token |

---

## Coordinator / Specialist Split

### Why two specialists?

Triage and action are distinct concerns with different tool sets and risk profiles.
Keeping them separate:
- Holds each specialist to 4 tools (reliability degrades noticeably past ~5)
- Isolates classification errors from action errors in the reasoning log
- Lets us swap or upgrade one specialist without touching the other

### Triage Specialist — read-only

Responsible for understanding the request. Cannot write anything.

| Tool                  | Does                                                    | Does NOT do                                |
|-----------------------|---------------------------------------------------------|--------------------------------------------|
| `classify_request`    | Returns category (enum) + confidence score              | Assign priority                            |
| `score_priority`      | Returns P1–P4 + confidence given category/impact/urgency| Create or update any record                |
| `lookup_user_profile` | Returns user role, VIP flag, open ticket count (mock)   | Query AD/LDAP live; resolve account state  |
| `check_known_outage`  | Returns active outage flag + summary for a category     | Check individual device or host status     |

### Action Specialist — write access

Responsible for acting on the triage result. All side-effects go through here.

| Tool                    | Does                                                  | Does NOT do                              |
|-------------------------|-------------------------------------------------------|------------------------------------------|
| `create_ticket`         | Creates ticket record, returns ticket_id              | Notify the user                          |
| `auto_resolve`          | Closes Password-category requests with canned response| Resolve any non-Password request         |
| `search_knowledge_base` | Returns top-3 KB articles by relevance                | Execute remediation steps                |
| `escalate_to_human`     | Flags ticket for human queue with reason + urgency    | Page on-call; sets a flag only           |

---

## Context Passing — Critical Design Note

**Task subagents do NOT inherit the coordinator's context.** Every Task call must be
self-contained. The coordinator passes context explicitly in each prompt.

### Triage Specialist Task prompt (template)

```
You are the Triage Specialist for an IT helpdesk agent.

REQUEST
  user_id:  {user_id}
  channel:  {channel}
  text:     {request_text}

Your job: classify the request and score its priority.
Return JSON matching this schema exactly:
{triage_schema}

Use your tools in this order:
  1. classify_request   — determine the category
  2. score_priority     — assign P1–P4
  3. lookup_user_profile — check if VIP or repeat caller
  4. check_known_outage  — check if a relevant outage is active (if category is Network/Security)
```

### Action Specialist Task prompt (template)

```
You are the Action Specialist for an IT helpdesk agent.

TRIAGE RESULT
  user_id:        {user_id}
  category:       {category}
  priority:       {priority}
  confidence:     {confidence}
  vip_user:       {vip_user}
  outage_active:  {outage_active}
  request_text:   {request_text}

Your job: take the correct action and return JSON matching this schema exactly:
{action_schema}

Decision rules:
  - auto_resolve   → only if category=Password AND confidence >= 0.85
  - escalate       → if priority=P1, OR confidence < 0.60, OR (vip_user=true AND priority <= P2)
  - create_ticket  → everything else
```

---

## Validation and Retry Loop

Both specialist outputs are validated against a Pydantic schema before the coordinator
proceeds. On validation failure:

1. The specific error (field name + reason) is appended to the next prompt
2. The specialist retries with the error as explicit context
3. After 3 consecutive failures the coordinator logs `status=failed` and routes to
   `escalate_to_human` automatically

Every `decisions.jsonl` entry records `retry_count` and `last_validation_error` so the
Scorecard can surface failure patterns.

---

## Structured Tool Errors

All tools return either a success dict or a structured error:

```json
{
  "isError": true,
  "code": "INVALID_CATEGORY",
  "message": "Category 'Networking' is not a valid option.",
  "guidance": "Valid values: Network, Security, Hardware, Software, Access, Password, General"
}
```

This lets the specialist recover and retry a corrected call rather than trying to parse a
plain error string — which is unreliable and untestable.

---

## Consequences

**Benefits:**
- Clean read/write separation: triage specialist cannot cause side-effects
- Small tool sets per specialist — measurable via the Scorecard
- Explicit context passing means the reasoning log is self-contained and replayable
- Structured errors make recovery deterministic, not prompt-dependent

**Accepted trade-offs:**
- Two API calls per request instead of one — acceptable for a non-interactive triage flow
- Mock data stores mean the agent cannot reflect live ticket state; a production version
  would need a real integration layer (ServiceNow, Jira Service Management, etc.)
