"""
Action Specialist — takes a triage result and executes the correct action.

Runs as a subagent called by the coordinator. Does NOT inherit coordinator context;
all inputs arrive explicitly via the task prompt.
"""

import json
from agent.aws_credentials import get_bedrock_client
from agent.tools.action_tools import ACTION_TOOL_DEFINITIONS, ACTION_TOOL_MAP

MODEL_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"
MAX_TOKENS = 1024


def run_action(
    user_id: str,
    category: str,
    priority: str,
    confidence: float,
    vip_user: bool,
    outage_active: bool,
    request_text: str,
) -> dict:
    """
    Runs the action specialist agent and returns a structured action result.

    Returns:
      {
        "action": str,           — "auto_resolve" | "create_ticket" | "escalate_to_human"
        "ticket_id": str | None,
        "escalation_id": str | None,
        "resolution_text": str | None,
        "reasoning": str,
      }
    """
    client = get_bedrock_client()

    action_schema = json.dumps({
        "action":          "string — one of: auto_resolve, create_ticket, escalate_to_human",
        "ticket_id":       "string or null",
        "escalation_id":   "string or null",
        "resolution_text": "string or null",
        "reasoning":       "string — one or two sentences explaining the action taken",
    }, indent=2)

    system_prompt = (
        "You are the Action Specialist for an IT helpdesk agent. "
        "You receive a triage result and must take the correct action using your tools. "
        "You have write access. Return a single JSON object after calling the appropriate tool. "
        "Do not include any text outside the JSON."
    )

    task_prompt = f"""TRIAGE RESULT
  user_id:        {user_id}
  category:       {category}
  priority:       {priority}
  confidence:     {confidence}
  vip_user:       {vip_user}
  outage_active:  {outage_active}
  request_text:   {request_text}

Decision rules (apply in order):
  1. escalate_to_human  — if priority=P1, OR confidence < 0.60, OR (vip_user=true AND priority in [P1,P2]), OR category=Security
  2. auto_resolve       — ONLY if category=Password AND confidence >= 0.85
  3. create_ticket      — everything else

You may optionally call search_knowledge_base first to find relevant articles and include
them in the ticket summary.

Then return a single JSON object matching this schema exactly:
{action_schema}"""

    messages = [{"role": "user", "content": task_prompt}]

    for _ in range(6):
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            tools=ACTION_TOOL_DEFINITIONS,
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
                    fn = ACTION_TOOL_MAP.get(block.name)
                    result = fn(**block.input) if fn else {"isError": True, "code": "UNKNOWN_TOOL", "message": f"No tool named '{block.name}'."}
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })
            messages.append({"role": "user", "content": tool_results})

    raise ValueError("Action specialist exceeded iteration limit without producing a result.")
