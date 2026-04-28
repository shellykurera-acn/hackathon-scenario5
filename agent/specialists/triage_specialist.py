"""
Triage Specialist — classifies request, scores priority, enriches with user + outage context.

Runs as a subagent called by the coordinator. Does NOT inherit coordinator context;
all inputs arrive via the task_prompt argument.
"""

import json
from agent.aws_credentials import get_bedrock_client
from agent.tools.triage_tools import TRIAGE_TOOL_DEFINITIONS, TRIAGE_TOOL_MAP

MODEL_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"
MAX_TOKENS = 1024


def run_triage(user_id: str, channel: str, request_text: str) -> dict:
    """
    Runs the triage specialist agent and returns a structured triage result.

    Returns:
      {
        "category": str,
        "priority": str,
        "confidence": float,
        "vip_user": bool,
        "outage_active": bool,
        "reasoning": str,
      }
    or raises ValueError on repeated schema failures.
    """
    client = get_bedrock_client()

    triage_schema = json.dumps({
        "category":      "string — one of: Network, Security, Hardware, Software, Access, Password, General",
        "priority":      "string — one of: P1, P2, P3, P4",
        "confidence":    "float — 0.0 to 1.0",
        "vip_user":      "boolean",
        "outage_active": "boolean",
        "reasoning":     "string — one or two sentences explaining the decision",
    }, indent=2)

    system_prompt = (
        "You are the Triage Specialist for an IT helpdesk agent. "
        "Your only job is to classify the request, score its priority, and enrich it with context. "
        "You have no write access. Use your tools, then return a single JSON object. "
        "Do not include any text outside the JSON."
    )

    task_prompt = f"""REQUEST
  user_id:  {user_id}
  channel:  {channel}
  text:     {request_text}

Your job: classify the request and score its priority.

Use your tools in this order:
  1. classify_request   — determine the category
  2. lookup_user_profile — check VIP status and open ticket count
  3. check_known_outage  — check if an outage is active for the detected category
  4. score_priority      — assign P1–P4 using all gathered context

Then return a single JSON object matching this schema exactly:
{triage_schema}"""

    messages = [{"role": "user", "content": task_prompt}]

    for _ in range(6):  # agent loop iterations
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            tools=TRIAGE_TOOL_DEFINITIONS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    text = block.text.strip()
                    start = text.find("{")
                    end = text.rfind("}") + 1
                    if start != -1:
                        return json.loads(text[start:end])
            raise ValueError("end_turn reached but no JSON found in response")

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    fn = TRIAGE_TOOL_MAP.get(block.name)
                    result = fn(**block.input) if fn else {"isError": True, "code": "UNKNOWN_TOOL", "message": f"No tool named '{block.name}'."}
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })
            messages.append({"role": "user", "content": tool_results})

    raise ValueError("Triage specialist exceeded iteration limit without producing a result.")
