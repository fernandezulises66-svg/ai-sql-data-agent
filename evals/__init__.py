"""Lightweight end-to-end evaluation suite for the AI Data Analyst Agent.

Unlike tests/ (which validates deterministic application logic — SQL
validation, schema introspection, seeding, agent wiring — with mocks and
never touches the OpenAI API), this package runs representative business
questions through the *real* agent and grades its behavior. Running it
for real (`python -m evals.run_evals`) calls the OpenAI API and consumes
API usage; pytest never does this automatically.
"""
