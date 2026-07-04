#!/usr/bin/env python3
"""
run_mcp_agent.py — CLI entry for the Option A MCP host (Ollama + qwen3:8b).

    python run_mcp_agent.py --list-tools          # start servers, show tools
    python run_mcp_agent.py --once "your prompt"  # single agent turn
    python run_mcp_agent.py                       # interactive REPL
    python run_mcp_agent.py --model llama3.1:8b   # try another tool-caller
    python run_mcp_agent.py --verbose             # show tool calls as they run
"""

import argparse
import asyncio
import logging
import sys

from mcp_host import MCPAgent, MCPHost


def parse_args():
    p = argparse.ArgumentParser(description="Larry MCP agent (Ollama + real MCP servers)")
    p.add_argument("--model", default="qwen3:8b")
    p.add_argument("--config", default=None, help="path to servers.json")
    p.add_argument("--once", metavar="PROMPT", help="run one prompt and exit")
    p.add_argument("--list-tools", action="store_true", help="list aggregated MCP tools and exit")
    p.add_argument("--max-turns", type=int, default=10)
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def print_result(result, verbose: bool):
    if verbose and result.tool_calls_made:
        print(f"\n--- {len(result.tool_calls_made)} tool call(s), {result.turns} turn(s) ---")
        for call in result.tool_calls_made:
            print(f"  {call['tool']}({call['arguments']})")
            print(f"    -> {call['result_preview']!r}")
        print("---")
    print(f"\n{result.answer}\n")


async def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    async with MCPHost(config_path=args.config) as host:
        if host.failed_servers:
            for name, err in host.failed_servers.items():
                print(f"[warn] server '{name}' failed: {err}", file=sys.stderr)

        if args.list_tools:
            print(f"{len(host.tool_names())} tool(s) from {len(host.sessions)} server(s):\n")
            for spec in host.openai_tools():
                fn = spec["function"]
                desc = (fn["description"] or "").split("\n")[0][:90]
                print(f"  {fn['name']:<40} {desc}")
            return 0

        agent = MCPAgent(host, model=args.model, max_turns=args.max_turns)

        if args.once:
            result = await agent.run(args.once)
            print_result(result, args.verbose)
            return 0

        # Interactive REPL with rolling history
        print(f"Larry MCP agent — model={args.model}, "
              f"{len(host.tool_names())} tools. Ctrl+C or 'exit' to quit.")
        history = []
        while True:
            try:
                user = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not user:
                continue
            if user.lower() in ("exit", "quit"):
                break
            result = await agent.run(user, history=history)
            print_result(result, args.verbose)
            history.append({"role": "user", "content": user})
            history.append({"role": "assistant", "content": result.answer})
            history[:] = history[-20:]  # keep context bounded
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
