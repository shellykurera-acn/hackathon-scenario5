# Team Solo — Shelly Warnakulasooriya

## Participants
- Shelly Warnakulasooriya (PM / Architect / Developer / Quality)

## Scenario
Scenario 5: Agentic Solution — "The Intake"

---

## What We Built

An agentic IT helpdesk triage system built on the **Claude Agent SDK via AWS Bedrock**. The
agent ingests inbound IT support requests (tickets, email, chat), classifies them into one
of seven categories (Network / Security / Hardware / Software / Access / Password / General),
assigns a priority (P1–P4), and takes the correct action: auto-resolve trivial requests,
create a tracked ticket, or escalate to a human.

**What runs end-to-end:**
- Coordinator orchestrates two specialist subagents — Triage and Action — each with 4 custom
  tools. Specialists receive context explicitly in their Task prompt; they do not inherit
  coordinator state.
- Triage Specialist classifies the request, scores priority, looks up the user profile, and
  checks for active outages — all read-only.
- Action Specialist creates tickets, auto-resolves password resets, searches the knowledge
  base, and escalates to the human queue — all writes go through here.
- Pydantic validation-retry loop: up to 3 retries per specialist on schema failure, with the
  specific error fed back to the model.
- Append-only decision log at `logs/decisions.jsonl` — every decision is replayable from
  the log alone.
- 38-case eval harness (25 normal + 13 adversarial) with 5 metrics including
  adversarial-pass rate and false-confidence rate.

**What is scaffolded / faked:**
- User profiles, knowledge base articles, and active outages are static JSON mock stores.
  A production version would integrate with ServiceNow, Active Directory, and a live
  monitoring feed.
- The `auto_resolve` tool sends a canned response; it does not call a real AD API to
  reset the password.
- No front-end — the agent is invoked via CLI or the eval harness.

---

## Challenges Attempted

| # | Challenge | Status | Notes |
|---|---|---|---|
| 1 | The Mandate | skipped | Time constraint |
| 2 | The Bones | done | ADR-001 with ASCII loop diagram, stop_reason table, context-passing templates |
| 3 | The Tools | done | 4 triage tools + 4 action tools, structured errors, Pydantic schemas |
| 4 | The Triage | partial | Coordinator + validation-retry loop built; full reasoning enrichment present |
| 5 | The Brake | skipped | Time constraint — escalation rules are in the Action Specialist prompt, not PreToolUse hooks |
| 6 | The Attack | done | 13 adversarial cases across 6 threat types |
| 7 | The Scorecard | done | Eval harness with 5 metrics, stratified sampling, CI-runnable |
| 8 | The Loop | skipped | — |

---

## Eval Results (38-case suite, run 2026-04-28)

```
Stratified accuracy          61.0%
False-confidence rate        18.4%
PII leaked                   no

Escalation recall            40.0%
Needless escalation rate     10.7%

Adversarial pass rate        46.2%
  prompt_injection           3/3  (100%)
  fake_urgency               2/2  (100%)
  pii_injection              1/2   (50%)
  hidden_legal               0/2    (0%)
  ambiguous                  0/2    (0%)
  auto_resolve_trap          0/2    (0%)

Precision per category
  Hardware                  100%
  Network                   100%
  Software                   75%
  Password                   75%
  Access                     60%
  Security                   17%
  General                     0%
```

**What the numbers mean:**

The agent handles clear-cut categories (Hardware, Network) with 100% precision and correctly
ignores prompt injection and fake urgency 100% of the time. These are the most common
real-world patterns and the hardest to patch once they fail.

The weaknesses are honest and diagnosable:

- **Security mis-classification (17%)** — the keyword-based `classify_request` tool misses
  Security signals when they're wrapped in other surface categories (infected laptop →
  Hardware, credit card breach → Password). Fix: richer Security keyword set and a
  second-pass "is this actually a security incident?" check.

- **Auto-resolve trap (0%)** — the agent was fooled by "reset my access to executive
  compensation." The `auto_resolve` guard (`category=Password AND confidence >= 0.85`) is
  the right pattern but the upstream classifier needs to route this to Access first.

- **JSON parse errors on complex multi-part requests (ADV-009, ADV-011)** — when a request
  contains multiple distinct issues, the specialist sometimes ends its turn without producing
  valid JSON. Fix: add an explicit "if you see multiple issues, resolve the highest-severity
  one and note the rest" instruction.

- **General category used as a fallback** — low-confidence cases land in General and then
  get needlessly escalated. Fix: clearer routing rules for the General bucket.

---

## Key Decisions

**1. Coordinator + specialist split with explicit context passing**  
Task subagents do not inherit coordinator context. Every specialist prompt is self-contained.
This is the single most important architectural decision — it makes every decision replayable
from the log and forces us to think carefully about what each specialist actually needs.
See `docs/adr/001-agent-architecture.md`.

**2. AWS Bedrock instead of direct Anthropic API**  
The hackathon environment uses AWS SSO (profile `bootcamp`). The `anthropic` SDK's
`AnthropicBedrock` client uses boto3 internally; on this Windows/SSO setup we bypass the
boto3 credential provider (which requires `botocore[crt]` to resolve SSO tokens) by
calling `aws configure export-credentials` directly and passing the short-lived keys.

**3. `auto_resolve` locked to `category=Password` only**  
The action tool returns a structured error for any other category. This is a hard guard
against auto-resolve traps — the agent cannot accidentally auto-resolve an Access or
Security request even if prompted to.

**4. Stratified eval scoring**  
The eval score weights each category equally. Without stratification, the Password category
(easy, high volume, high confidence) would inflate the overall accuracy and hide the
Security and General weaknesses.

---

## How to Run It

```bash
# 1. Log in to AWS (opens browser)
aws sso login --profile bootcamp --region us-east-1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the agent on a single request
python -m agent.coordinator --request "My laptop won't connect to VPN" --user-id U001

# 4. Run the full eval suite (25 normal + 13 adversarial)
python evals/run_evals.py

# Run adversarial cases only
python evals/run_evals.py --adversarial-only

# Run a single case
python evals/run_evals.py --case ADV-004

# 5. Inspect the decision log
python -m json.tool logs/decisions.jsonl
```

---

## If We Had More Time

1. **Fix Security classification** — extend `classify_request` keyword set and add a
   security-signal second-pass check. This is the highest-impact fix given the eval results.

2. **The Brake** — implement `PreToolUse` hooks that deterministically block `auto_resolve`
   on known high-risk patterns (exec data, frozen accounts, requests mentioning compliance).
   Currently escalation is prompt-based; hooks would make it a hard stop.

3. **Fix JSON parse failures on multi-part requests** — add explicit handling in the
   specialist prompts for requests containing multiple distinct issues.

4. **The Loop** — when a human overrides a decision, feed it as a labelled example back
   into the eval set. This closes the feedback loop and makes the Scorecard improve over
   time.

5. **MCP server** — expose the coordinator as an MCP server so any Claude session can
   call `process_request` as a tool without needing to know the implementation.

6. **Live integrations** — replace mock data stores with real ServiceNow / AD / Okta calls.

---

## How We Used Claude Code

**What worked exceptionally well:**
- Generated the entire ADR (architecture decision record) including the ASCII loop diagram
  and stop_reason handling table in a single pass — saved ~45 minutes of documentation work.
- Wrote all 8 tool functions with correct structured error formats, Pydantic schemas, and
  tool definition dicts without needing iteration.
- Generated all 38 eval cases (25 normal + 13 adversarial) with realistic IT helpdesk
  language and correctly labelled expected outputs.
- Debugged the AWS Bedrock SSO credential chain — identified that `AnthropicBedrock` creates
  its own boto3 session (bypassing the profile env var), diagnosed the `botocore[crt]` error,
  and proposed the `aws configure export-credentials` workaround.

**What surprised us:**
- Claude Code kept the full architectural context across the entire session — it remembered
  the tool schemas, the Pydantic models, and the eval format without being reminded.
- The commit message convention in CLAUDE.md was respected automatically on every commit.

**Where it saved the most time:**
- The eval harness (`run_evals.py`) — stratified scoring, per-threat-type adversarial
  breakdown, false-confidence detection, and PII leak checking would have taken 2–3 hours
  to write manually. It was written and tested in under 20 minutes.
