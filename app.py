"""Terminal entry point for the AI SQL Data Analyst Agent.

A minimal interactive loop: ask a business question in natural language
and get a business-oriented answer generated from the live database via
agent/data_analyst_agent.py. The agent never touches SQLite directly —
all data access goes through the safe, read-only layer in
tools/sql_tool.py.

Run with `--debug` to additionally print the SQL the agent executed for
each answer (query text, rows returned, truncation, execution time).
This exposes observable tool activity only — never the model's internal
reasoning/chain-of-thought, which the OpenAI Agents SDK does not expose
to this application at all.

The Streamlit interface will be added in a later iteration.
"""

import argparse

from agent.data_analyst_agent import (
    AgentConfigError,
    AgentError,
    AgentRuntimeError,
    SQLToolCallRecord,
    run_data_agent,
)
from tools.schema_tool import SchemaToolError


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI SQL Data Analyst Agent (terminal demo).")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Also print SQL tool activity (query, rows, timing) for each answer.",
    )
    return parser.parse_args()


def _print_debug_info(tool_calls: list[SQLToolCallRecord]) -> None:
    """Print observable SQL tool activity only — no model reasoning."""
    if not tool_calls:
        print("(debug: no SQL was executed for this answer)\n")
        return

    for index, call in enumerate(tool_calls, start=1):
        if len(tool_calls) > 1:
            print(f"[SQL tool call {index} of {len(tool_calls)}]")
        print("SQL executed:")
        print(call.query)
        print()
        if call.success:
            print(f"Rows returned: {call.row_count}")
            print(f"Truncated: {call.truncated}")
        else:
            print(f"Failed: {call.error}")
        print(f"Execution time: {call.execution_time_ms:.1f} ms")
        print()


def main() -> None:
    args = _parse_args()

    print("AI SQL Data Analyst Agent")
    if args.debug:
        print("(debug mode: SQL tool activity will be shown after each answer)")
    print("Ask a business question about the ecommerce database.")
    print("Type 'exit' or 'quit' to leave.\n")

    while True:
        try:
            question = input("Ask a question:\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break

        try:
            result = run_data_agent(question)
        except AgentConfigError as exc:
            print(f"\nConfiguration error: {exc}\n")
            continue
        except SchemaToolError as exc:
            print(f"\nDatabase error: {exc}\n")
            continue
        except AgentRuntimeError as exc:
            print(f"\nAgent error: {exc}\n")
            continue
        except AgentError as exc:  # any other agent-layer error
            print(f"\nError: {exc}\n")
            continue
        except Exception as exc:  # last-resort guard: never show a raw traceback
            print(f"\nUnexpected error: {exc}\n")
            continue

        print(f"\n{result.answer}\n")
        if args.debug:
            _print_debug_info(result.tool_calls)


if __name__ == "__main__":
    main()
