import json
from typing import Any

from mcp import ClientSession

from shared.client import get_client
from week_04.mcp_client import connect, tool_text
from week_04.orchestrator import MultiServerOrchestrator
from week_04.targets import Target, profile_targets

_SYSTEM_SINGLE = (
    "You are an assistant with access to MCP tools. "
    "When a tool can help, call it, then answer the user using the tool result. "
    "For any places search/report request, always call save_to_file after build_report. "
    "If no filename is provided, choose a sensible lowercase filename using the city "
    "and query, like places_report_lisbon_coffee.md. "
    "Do not skip saving unless the request is impossible to complete. "
    "Use min_price/max_price only when the user asks for cheap, budget, moderate, "
    "expensive, premium, or upscale places. Price filters are search filters only; "
    "do not claim exact price tiers in the final report because Foursquare price values "
    "are Premium fields. "
    "Be concise."
)

_SYSTEM_TECH_RADAR = (
    "You orchestrate tools across multiple MCP servers for a Tech Radar workflow. "
    "Server prefixes are mandatory and must not be mixed: github__, pypi__, radar__, reports__. "
    "You MUST call radar__extract_requirements as your very first tool call before any other tool. "
    "Do not call any other tool until you have received its result. "
    "Then follow this flow: search repos, normalize candidates, collect github and pypi evidence, "
    "build comparison, write markdown yourself, save report, list reports. "
    "Use enriched candidates with strict fields and null for missing values. "
    "If evidence is partial, continue and explain gaps. "
    "After radar__build_comparison, you MUST author the final markdown report yourself and pass it "
    "as reports__save_report(content=..., slug=...). "
    "Your markdown must include: title; requirements; ranked recommendations; "
    "and for each candidate: repo full_name, github stars, github updated_at, "
    "github open issues (if available), pypi package "
    "name, latest pypi version, requires_python, latest release version+date, deterministic score "
    "breakdown (fit/maintenance/freshness/community), confidence penalty, package confidence note "
    "(guess/match), and a 1-2 sentence recommendation explaining the rank. "
    "If data is missing or errored, state it explicitly. "
    "End with verdict and a note that scores are deterministic heuristics. "
    "Use concise output."
)

_MAX_STEPS_SINGLE = 5
_MAX_STEPS_ORCHESTRATION = 16
_LOG_TRUNCATE = 200


def _truncate(text: str) -> str:
    return text if len(text) <= _LOG_TRUNCATE else f"{text[:_LOG_TRUNCATE]}..."


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
                {"role": "system", "content": _SYSTEM_SINGLE},
                {"role": "user", "content": question},
            ]
            print(f"User: {question}\n")

            for _ in range(_MAX_STEPS_SINGLE):
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
                    print(f"  <- {_truncate(text)}")
                    messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": text}
                    )
                print()

            print("Agent: (stopped: max tool steps reached)")


async def run_orchestrated_agent(profile: str, provider: str, question: str) -> None:
    client, model = get_client(provider)
    targets = profile_targets(profile)
    print(f"Target: Day 20 orchestration profile '{profile}'")
    print(f"Servers: {', '.join(sorted(targets))}")
    print(f"Provider: {provider} ({model})")

    async with MultiServerOrchestrator(targets) as orchestrator:
        print(f"tools available to LLM: {orchestrator.tool_names}\n")
        print(f"User: {question}\n")

        messages: list[Any] = [
            {"role": "system", "content": _SYSTEM_TECH_RADAR},
            {"role": "user", "content": question},
        ]

        for _ in range(_MAX_STEPS_ORCHESTRATION):
            resp = client.chat.completions.create(
                model=model, messages=messages, tools=orchestrator.openai_tools
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                print(f"Agent: {msg.content}")
                return

            messages.append(msg.model_dump(exclude_none=True))
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                print(f"  -> call {tc.function.name}({_truncate(str(args))})")
                try:
                    text = await orchestrator.call_tool(tc.function.name, arguments=args)
                except Exception as exc:
                    text = json.dumps({"error": str(exc)}, ensure_ascii=False)
                print(f"  <- {_truncate(text)}")
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})
            print()

        print("Agent: (stopped: max tool steps reached)")

