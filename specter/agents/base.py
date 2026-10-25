"""A small, guarded tool-calling loop shared by the model-driven agents.

Guards: only whitelisted tools run (anything else gets an error result and is logged as blocked),
every tool call counts against the run budget, and the loop stops after MAX_AGENT_ITERATIONS
model turns. On the last turn the model is forced to call the final tool.
"""

import json

import config
from specter.llm import RunCtx, call_model


def tool_schema(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "function", "name": name, "description": description, "strict": True,
            "parameters": {"type": "object", "properties": properties, "additionalProperties": False,
                           "required": required if required is not None else list(properties)}}


def run_tool_loop(ctx: RunCtx, agent: str, instructions: str, user_input: str, tools: dict, final_tool: str,
                  purpose: str = "") -> dict | None:
    """tools: name -> (schema, function or None for the final tool). Returns the final tool's arguments."""
    schemas = [schema for schema, _ in tools.values()]
    items: list = [{"role": "user", "content": user_input}]
    for turn in range(1, config.MAX_AGENT_ITERATIONS + 1):
        last = turn == config.MAX_AGENT_ITERATIONS
        choice = {"type": "function", "name": final_tool} if last else "required"
        result = call_model(ctx, agent, instructions, items, tools=schemas, tool_choice=choice, cacheable=True,
                            purpose=f"{purpose} (turn {turn})")
        if not result.tool_calls:
            return None
        for call in result.tool_calls:
            name, args = call["name"], call["arguments"]
            if name == final_tool:
                return args
            items.append({"type": "function_call", "call_id": call["call_id"], "name": name,
                          "arguments": json.dumps(args)})
            if name not in tools:
                ctx.emit(agent, name, f"Blocked a call to {name}(): not on the {agent}'s tool whitelist.")
                output = {"error": f"{name} is not an allowed tool."}
            else:
                ctx.budget.add_tool_call()
                try:
                    output = tools[name][1](**args)
                except TypeError as exc:
                    output = {"error": f"bad arguments: {exc}"}
            items.append({"type": "function_call_output", "call_id": call["call_id"],
                          "output": json.dumps(output, default=str)})
    return None
