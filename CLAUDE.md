# CLAUDE.md — IT Helpdesk Agentic Solution

## Project Overview
Hackathon Scenario 5: An agentic IT helpdesk triage system built on the Claude Agent SDK.
The agent ingests inbound IT requests, classifies them, assigns priority (P1–P4), routes to
the correct queue, and auto-resolves trivials (password resets / account unlocks).

## Stack
- Python 3.11+
- Claude Agent SDK (`anthropic` package)
- Pydantic v2 for schema validation
- No external databases — mock data stores in `agent/data/`

## Project Structure
```
agent/
  coordinator.py          ← entry point; orchestrates specialist subagents
  specialists/
    triage_specialist.py  ← classifies, scores priority, enriches with context
    action_specialist.py  ← creates tickets, auto-resolves, escalates
  tools/
    triage_tools.py       ← 4 tools for the triage specialist
    action_tools.py       ← 4 tools for the action specialist
  data/
    users.json            ← mock user profiles
    knowledge_base.json   ← mock KB articles
    outages.json          ← mock active outages
docs/adr/
  001-agent-architecture.md
evals/
  adversarial_set.json    ← 13 adversarial test cases
  normal_traffic.json     ← 25 normal test cases (stratified)
  run_evals.py            ← eval harness; run with: python evals/run_evals.py
  results/                ← eval output lands here
logs/
  decisions.jsonl         ← append-only reasoning chain log
```

## Conventions

### Tool design
- Every tool returns either a success dict or `{"isError": True, "code": "...", "message": "...", "guidance": "..."}`
- Tool function names use `snake_case`
- Tool descriptions must state: what it does, what it does NOT do, input format, example query
- Max 4 tools per specialist — do not exceed

### Agent architecture
- Coordinator calls specialists via the Claude Agent SDK `Task` mechanism
- Specialists do NOT inherit coordinator context — all relevant context is passed explicitly in the Task prompt
- Validation-retry loop: up to 3 retries on Pydantic schema failure; log retry count + error type per request

### Eval format
- Every eval case: `{"id": "...", "input": "...", "expected_category": "...", "expected_priority": "...", "expected_action": "...", "should_escalate": bool}`
- Adversarial cases add: `"threat_type": "prompt_injection" | "fake_urgency" | "hidden_legal" | "ambiguous" | "auto_resolve_trap" | "pii_injection"`

### Commits
- Commit after each phase completes
- Message format: `<phase>: <what was done` (e.g., `bones: add ADR with coordinator/specialist split`)
- Co-author line required: `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`

### Environment
- API key in `.env` as `ANTHROPIC_API_KEY=...`
- `.env` is gitignored

## Running the agent
```bash
pip install -r requirements.txt
cp .env.example .env   # add your ANTHROPIC_API_KEY
python -m agent.coordinator --request "My laptop won't connect to VPN"
```

## Running evals
```bash
python evals/run_evals.py
# outputs evals/results/latest.json + summary table
```
