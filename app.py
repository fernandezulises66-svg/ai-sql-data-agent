"""Terminal entry point for the AI SQL Data Analyst Agent.

A minimal interactive loop: ask a business question in natural language
and get a business-oriented answer generated from the live database via
agent/data_analyst_agent.py. The agent never touches SQLite directly —
all data access goes through the safe, read-only layer in
tools/sql_tool.py.

The Streamlit interface will be added in a later iteration.
"""

from agent.data_analyst_agent import (
    AgentConfigError,
    AgentError,
    AgentRuntimeError,
    ask_data_agent,
)
from tools.schema_tool import SchemaToolError


def main() -> None:
    print("AI SQL Data Analyst Agent")
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
            answer = ask_data_agent(question)
        except AgentConfigError as exc:
            print(f"\nConfiguration error: {exc}\n")
        except SchemaToolError as exc:
            print(f"\nDatabase error: {exc}\n")
        except AgentRuntimeError as exc:
            print(f"\nAgent error: {exc}\n")
        except AgentError as exc:  # any other agent-layer error
            print(f"\nError: {exc}\n")
        except Exception as exc:  # last-resort guard: never show a raw traceback
            print(f"\nUnexpected error: {exc}\n")
        else:
            print(f"\n{answer}\n")


if __name__ == "__main__":
    main()
