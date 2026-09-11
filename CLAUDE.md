# AI SQL Data Analyst Agent

## Project Overview

This is a portfolio project called **AI SQL Data Analyst Agent**.

The goal is to build an AI agent that allows users to ask business questions in natural language, translates those questions into safe SQL queries, executes them against a database, and returns clear business-oriented insights.

This project is being developed incrementally as part of a professional portfolio focused on AI Agents, Generative AI, Data Analysis, and Python.

## Main Goals

The application should eventually:

1. Accept business questions in natural language.
2. Understand the available database schema.
3. Generate appropriate SQL queries.
4. Validate SQL queries before execution.
5. Only allow safe read-only queries.
6. Execute queries against the database.
7. Interpret query results.
8. Return clear business-oriented answers.
9. Handle invalid or ambiguous questions gracefully.
10. Provide a simple user interface.

## Planned Tech Stack

- Python 3.11+
- SQLite for the initial database
- SQL
- OpenAI API
- OpenAI Agents SDK / tool calling
- Streamlit
- pytest
- Git / GitHub

Additional technologies should only be introduced when they solve a real project requirement.

Do not introduce unnecessary frameworks or abstractions.

## Development Philosophy

This project should remain:

- Simple
- Modular
- Easy to understand
- Easy to explain during a technical interview
- Well documented
- Secure by default
- Suitable for a junior AI / Data / Functional Analyst portfolio

Avoid overengineering.

Prefer straightforward Python implementations over complex architectural patterns unless complexity becomes necessary.

## Development Workflow

The project will be developed incrementally.

Do not implement future features unless explicitly requested.

Each iteration should focus on one clear piece of functionality.

Before making significant architectural changes:

1. Explain the proposed change.
2. Explain why it is necessary.
3. Prefer the simplest solution that satisfies the requirement.

Do not refactor unrelated code unless necessary.

## Code Quality

Follow these principles:

- Use clear and descriptive names.
- Keep functions small and focused.
- Add type hints when useful.
- Follow PEP 8 conventions.
- Avoid duplicated logic.
- Add comments only when they explain non-obvious decisions.
- Prefer readable code over clever code.

## Security

Security is especially important because this application will generate and execute SQL.

Never:

- Commit API keys.
- Hardcode secrets.
- Commit `.env` files.
- Allow destructive SQL operations.

The SQL execution layer should eventually restrict operations such as:

- INSERT
- UPDATE
- DELETE
- DROP
- ALTER
- CREATE
- TRUNCATE

The agent should only have read access to the analytical database.

## Environment Variables

Secrets must be stored in a local `.env` file.

The repository should only contain:

`.env.example`

Never put real credentials in `.env.example`.

## Testing

Important logic should be testable.

pytest will be used for testing.

Priority areas for tests will include:

- Database initialization
- SQL validation
- Query execution
- Agent tools
- Error handling

## Database

The initial version will use SQLite.

The database will represent a fictional e-commerce business so the agent can answer realistic analytical questions.

The initial domain will likely include:

- Customers
- Products
- Orders
- Order items

The schema should remain simple enough to understand but realistic enough to demonstrate joins, aggregations, filters, and business analysis.

## Git Workflow

Changes should be small and logically grouped.

Use descriptive commits such as:

- `chore: initialize project structure`
- `feat: add ecommerce database schema`
- `feat: generate sample sales data`
- `feat: add safe sql execution tool`
- `feat: integrate ai agent`
- `test: add sql validation tests`
- `docs: improve project readme`

Do not automatically commit or push changes unless explicitly requested.

## Documentation

The README should eventually explain:

- The business problem
- Architecture
- Features
- Tech stack
- Installation
- Environment setup
- Example questions
- Security considerations
- Screenshots
- Future improvements

The final repository should be understandable by both recruiters and technical reviewers.

## Important Instruction

Always respect the scope of the current task.

If asked to implement one feature, do not automatically implement later stages of the project.

At the end of each task, summarize:

1. What was changed.
2. Why it was changed.
3. Files created or modified.
4. How to test the changes.
5. Any relevant decisions or limitations.