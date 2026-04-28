# Agent Module — Directory Conventions

Inherits from project-level CLAUDE.md. Rules here are specific to `agent/`.

## Specialist pattern
- Every specialist exposes a single public function: `run_<name>(...)  -> dict`
- Specialists are stateless — no module-level state, no caching
- All context arrives via function arguments; specialists never read from disk except via tools
- `get_bedrock_client()` is the only authorised way to create an API client

## Tool design rules
- Max 4 tools per specialist — do not add a fifth without removing one
- Every tool must have a docstring with: Does / Does NOT / Input / Example
- Every tool returns either a success dict or the standard error shape:
  `{"isError": True, "code": "SCREAMING_SNAKE", "message": "...", "guidance": "..."}`
- Tool names: `snake_case` verbs — `classify_request`, not `classifier` or `RequestClassifier`
- Tool definitions live at the bottom of the tools file as `<NAME>_TOOL_DEFINITIONS` and `<NAME>_TOOL_MAP`

## Agent loop
- Max 6 iterations per specialist call — prevents runaway loops
- On `end_turn`: extract JSON from response text (find `{` ... `}`) and return
- On `tool_use`: execute every tool in the block, collect all results, continue
- On `max_tokens`: log warning, append "response truncated — please continue", retry once

## Mock data
- All mock data lives in `agent/data/*.json` — never inline test data in code
- Schema changes to mock data require updating the corresponding tool docstring

## Pydantic schemas
- Defined in `coordinator.py` — do not duplicate in specialist files
- `model_post_init` for cross-field validation (e.g. category enum check)
- Validation errors must include field name + received value in the message
