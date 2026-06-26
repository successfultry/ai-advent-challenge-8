import json
from typing import Any

from mcp import ClientSession

from shared.client import get_client
from week_04.mcp_client import connect, tool_text
from week_04.targets import Target

_SYSTEM = (
    "You are an assistant with access to MCP tools. "
    "When a tool can help, call it, then answer the user using the tool result. "
    "For search/report requests, save the final report with save_to_file unless the "
    "user explicitly asks not to save or asks only to show results. "
    "If no filename is provided, choose a sensible one like places_report_<city>.md. "
    "Be concise."
)
_MAX_STEPS = 5


def _to_openai_tools(tools: list[Any]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": (t.description or "").strip(),
                "parameters": t.inputSchema
                if isinstance(t.inputSchema, dict)
                else {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]


async def run_agent(target: Target, provider: str, question: str) -> None:
    client, model = get_client(provider)
    print(f"Target: {target.label}")
    print(f"Provider: {provider} ({model})")
    async with connect(target) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            oai_tools = _to_openai_tools(tools)
            print(f"tools available to LLM: {[t.name for t in tools]}\n")

            messages: list[Any] = [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": question},
            ]
            print(f"User: {question}\n")

            for _ in range(_MAX_STEPS):
                resp = client.chat.completions.create(
                    model=model, messages=messages, tools=oai_tools
                )
                msg = resp.choices[0].message
                if not msg.tool_calls:
                    print(f"Agent: {msg.content}")
                    return

                messages.append(msg.model_dump(exclude_none=True))
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments or "{}")
                    print(f"  -> call {tc.function.name}({args})")
                    result = await session.call_tool(tc.function.name, arguments=args)
                    text = tool_text(result)
                    short = text if len(text) <= 200 else f"{text[:200]}..."
                    print(f"  <- {short}")
                    messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": text}
                    )
                print()

            print("Agent: (stopped: max tool steps reached)")
