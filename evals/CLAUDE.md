# Evals Module — Directory Conventions

Inherits from project-level CLAUDE.md. Rules here are specific to `evals/`.

## Case schema
Every eval case must include these fields — no exceptions:
```json
{
  "id":                "NRM-001 or ADV-001 (prefix indicates dataset)",
  "user_id":           "U001–U008 or UNKNOWN",
  "input":             "raw request text, realistic IT helpdesk language",
  "expected_category": "one of the 7 valid categories",
  "expected_priority": "P1–P4",
  "expected_action":   "auto_resolve | create_ticket | escalate_to_human",
  "should_escalate":   "boolean — must match expected_action == escalate_to_human",
  "notes":             "why this case is interesting / what it tests"
}
```

Adversarial cases add:
```json
{
  "threat_type": "prompt_injection | fake_urgency | hidden_legal | ambiguous | auto_resolve_trap | pii_injection",
  "pii_must_not_appear_in_output": ["list of strings that must not appear in agent output"]
}
```

## Dataset balance
- `normal_traffic.json`: 3–5 cases per category (7 categories = 21–35 cases total)
- `adversarial_set.json`: 2–3 cases per threat type (6 types = 12–18 cases total)
- Never let a single category exceed 30% of the normal traffic set
- At least one VIP user case (U002, U004, U007) per dataset

## Adding new cases
- Add to the correct dataset file — do not mix normal and adversarial
- IDs are sequential within each dataset; do not reuse or skip numbers
- Run `python evals/run_evals.py` after adding cases to confirm the harness loads them

## Metrics — definitions
- **Stratified accuracy**: mean of per-category accuracy (not overall %). Prevents Password from dominating.
- **False-confidence rate**: cases where `confidence >= 0.8` AND `correct_overall == False`. Measures dangerous overconfidence.
- **Escalation recall**: `correct escalations / total cases that should_escalate`. Missing a real escalation is the critical failure mode.
- **Adversarial-pass rate**: broken down by `threat_type` — aggregate rate is a vanity metric.

## Results
- `evals/results/` is gitignored — results are not committed
- Re-run the full suite after any change to tools, prompts, or mock data
- The README documents the last full run result with the commit SHA
