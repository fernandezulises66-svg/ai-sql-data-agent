"""Streamlit interface for the AI SQL Data Analyst Agent.

A thin presentation layer only: every question is answered by calling
the existing, already-tested backend
(``agent.data_analyst_agent.run_data_agent``), which itself uses
``tools.schema_tool`` and ``tools.sql_tool``. Nothing about agent
construction, SQL execution, schema introspection, or the OpenAI call is
reimplemented here.

Run with:

    streamlit run streamlit_app.py

The terminal CLI (``app.py``) keeps working independently — this file
does not replace or modify it. Each question submitted here is an
independent agent run (see ``run_data_agent``'s docstring); this module
only remembers past question/answer pairs in ``st.session_state`` for
convenient on-screen history, it does not add conversation memory to the
agent itself.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from agent.data_analyst_agent import (
    AgentAnswer,
    AgentConfigError,
    AgentError,
    AgentRuntimeError,
    SQLToolCallRecord,
    run_data_agent,
)
from tools.schema_tool import SchemaToolError

PAGE_TITLE = "Agente de Análisis de Datos con IA y SQL"

EXAMPLE_QUESTIONS_EN = [
    "What are the top 5 products by completed-order revenue?",
    "Which category generated the most revenue?",
    "Who are the top 5 customers by spending?",
    "What was the best sales month?",
    "What is the average completed order value?",
]

EXAMPLE_QUESTIONS_ES = [
    "¿Cuáles fueron los 5 productos con mayor facturación?",
    "¿Qué categoría generó más ingresos?",
    "¿Quiénes fueron los 5 clientes con mayor gasto?",
    "¿Cuál fue el mejor mes de ventas?",
]


# ---------------------------------------------------------------------------
# Pure helper functions (no Streamlit calls) — these do the actual work of
# turning backend results into display-ready data, so they can be unit
# tested directly without running the app or calling the OpenAI API.
# ---------------------------------------------------------------------------


def build_tool_call_view(record: SQLToolCallRecord) -> dict[str, Any]:
    """Plain-data view of one SQL tool call, ready for display.

    Only ever includes observable tool activity (query text + outcome
    metadata) — never chain-of-thought, secrets, or raw SDK internals.
    """
    return {
        "query": record.query,
        "success": record.success,
        "row_count": record.row_count,
        "truncated": record.truncated,
        "execution_time_ms": record.execution_time_ms,
        "error": record.error,
    }


def build_observability_view(answer: AgentAnswer) -> list[dict[str, Any]]:
    """Plain-data view of every SQL tool call made while producing answer."""
    return [build_tool_call_view(call) for call in answer.tool_calls]


def used_sql(answer: AgentAnswer) -> bool:
    """Whether the agent ran at least one SQL query for this answer."""
    return len(answer.tool_calls) > 0


def error_message_for(exc: Exception) -> str:
    """Map a known agent-layer exception to a clean, user-facing message.

    Mirrors app.py's CLI error handling so both front ends behave
    consistently; never returns a raw traceback.
    """
    if isinstance(exc, AgentConfigError):
        return f"Error de configuración: {exc}"
    if isinstance(exc, SchemaToolError):
        return f"Error de base de datos: {exc}"
    if isinstance(exc, AgentRuntimeError):
        return f"Error del agente: {exc}"
    if isinstance(exc, AgentError):
        return f"Error: {exc}"
    return f"Error inesperado: {exc}"


# ---------------------------------------------------------------------------
# Streamlit rendering — only reached via main(), so importing this module
# (e.g. from tests) never touches Streamlit's runtime or calls the agent.
# ---------------------------------------------------------------------------


def _use_example_question(question: str) -> None:
    st.session_state["question_input"] = question


def render_sidebar() -> None:
    with st.sidebar:
        st.header("Sobre este proyecto")
        st.write(
            "Un proyecto de portafolio: un agente de IA que responde preguntas "
            "de negocio en lenguaje natural consultando de forma segura una "
            "base de datos SQLite de e-commerce de solo lectura."
        )
        st.subheader("Tecnologías")
        st.markdown(
            "- Python\n"
            "- SQLite\n"
            "- SQL\n"
            "- OpenAI Agents SDK\n"
            "- Streamlit\n"
            "- pytest"
        )
        st.subheader("Características de la arquitectura")
        st.markdown(
            "- Introspección dinámica del esquema\n"
            "- Ejecución de SQL de solo lectura\n"
            "- Validación y seguridad de SQL\n"
            "- Uso de herramientas (tool calling)\n"
            "- Respuestas multilingües\n"
            "- Observabilidad\n"
            "- Evaluaciones del agente"
        )


def render_sql_details(answer: AgentAnswer, nested: bool = False) -> None:
    """Render the observable SQL tool activity behind one answer.

    nested=True skips wrapping in st.expander, since Streamlit does not
    allow nesting an expander inside another expander (used for history
    entries, which are already inside their own expander).
    """
    calls = build_observability_view(answer)

    def _body() -> None:
        if not calls:
            st.caption("No fue necesario consultar la base de datos para responder esta pregunta.")
            return
        for index, call in enumerate(calls, start=1):
            if len(calls) > 1:
                st.markdown(f"**Consulta {index} de {len(calls)}**")
            st.code(call["query"], language="sql")
            if call["success"]:
                st.write(f"Filas devueltas: {call['row_count']}")
                st.write(f"Resultado truncado: {'Sí' if call['truncated'] else 'No'}")
            else:
                st.error(f"La consulta falló: {call['error']}")
            st.caption(f"Tiempo de ejecución: {call['execution_time_ms']:.1f} ms")

    if nested:
        st.markdown("**Detalles SQL**")
        _body()
    else:
        with st.expander("Ver detalles SQL"):
            _body()


def render_answer(answer: AgentAnswer) -> None:
    st.subheader("Respuesta")
    st.write(answer.answer)
    render_sql_details(answer)


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, page_icon="📊", layout="centered")
    render_sidebar()

    st.title(PAGE_TITLE)
    st.write(
        "Hacé preguntas de negocio en lenguaje natural y obtené respuestas "
        "generadas a partir de una base de datos de e-commerce de solo lectura."
    )
    st.info(
        "- Las respuestas se generan a partir de consultas SQL reales "
        "ejecutadas sobre la base de datos.\n"
        "- El acceso a la base de datos es estrictamente de solo lectura.\n"
        "- La base de datos contiene datos de ejemplo ficticios."
    )
    st.caption("También podés escribir tu pregunta en inglés.")

    with st.expander("Preguntas de ejemplo"):
        col_en, col_es = st.columns(2)
        with col_en:
            st.markdown("**Inglés**")
            for question in EXAMPLE_QUESTIONS_EN:
                st.button(
                    question,
                    key=f"ex_en_{question}",
                    on_click=_use_example_question,
                    args=(question,),
                    use_container_width=True,
                )
        with col_es:
            st.markdown("**Español**")
            for question in EXAMPLE_QUESTIONS_ES:
                st.button(
                    question,
                    key=f"ex_es_{question}",
                    on_click=_use_example_question,
                    args=(question,),
                    use_container_width=True,
                )

    with st.form("question_form"):
        st.text_input(
            "Tu pregunta",
            key="question_input",
            placeholder="¿Qué productos generaron más ingresos?",
        )
        submitted = st.form_submit_button("Consultar")

    if submitted:
        question = st.session_state.get("question_input", "").strip()
        if not question:
            st.warning("Por favor, escribí una pregunta.")
        else:
            with st.spinner("Analizando tu pregunta... el agente está consultando la base de datos."):
                try:
                    result = run_data_agent(question)
                except Exception as exc:  # AgentConfigError, SchemaToolError, AgentRuntimeError, ...
                    st.error(error_message_for(exc))
                else:
                    st.session_state["last_result"] = result
                    st.session_state["last_question"] = question
                    history = st.session_state.setdefault("history", [])
                    history.insert(0, {"question": question, "result": result})

    last_result = st.session_state.get("last_result")
    if last_result is not None:
        render_answer(last_result)

    history = st.session_state.get("history", [])
    if len(history) > 1:
        st.subheader("Preguntas anteriores")
        for entry in history[1:]:
            with st.expander(entry["question"]):
                st.write(entry["result"].answer)
                render_sql_details(entry["result"], nested=True)


if __name__ == "__main__":
    main()
