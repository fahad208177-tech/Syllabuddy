"""Syllabuddy MCP server: the official exam syllabus, as tools an assistant can call.

    python -m mcp_server            # Streamable HTTP on http://127.0.0.1:8765/mcp

Every tool answers from the parsed syllabus (data/syllabus.json) and a
per-student SQLite history. None of them call a language model, which keeps
answers fast enough for voice and impossible to hallucinate: when a tool says
"excluded", that is a quote from the official document.

Who is asking: the caller identifies the student with an ``X-Syllabuddy-Student``
header (the simulated Alexa+ app sends a per-browser id). A real Alexa+
deployment would use the subject of the OAuth access token from account
linking instead; ``student_id`` below already prefers a bearer token when one
is present.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations

from syllabus_core.progress import ProgressStore
from syllabus_core.service import ROOT, SyllabusService

INSTRUCTIONS = """\
Syllabuddy answers questions about official exam syllabuses: the US College Board
AP courses (Calculus AB/BC, Precalculus, Statistics, Physics 1/2/C, Chemistry,
Biology, Environmental Science, Computer Science A and Principles, Psychology,
Macro/Microeconomics, US and Comparative Government, US/World/European History,
Human Geography, African American Studies, Music Theory), the Canadian
Alberta Diploma courses (Physics 30, Chemistry 30) and the Singapore-Cambridge
GCE A-Level (H1/H2). Use it whenever a student asks whether
something is in their syllabus or on their exam, which objective a question
belongs to, what a topic requires, to be quizzed, or what to revise. Always quote
the objective id (Singapore "9758.3.3", AP "CALCBC-10.8" = topic 10.8) so the
student can check it. Never guess about what is examinable: if a tool says
'unclear' or 'not_in_syllabus', say so."""

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
RECORDS = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

mcp = MCPServer(name="Syllabuddy", title="Syllabuddy: exam syllabus assistant",
                instructions=INSTRUCTIONS, version="1.0.0")

_service: SyllabusService | None = None
_progress: ProgressStore | None = None
_lock = threading.Lock()


def service() -> SyllabusService:
    global _service
    with _lock:
        if _service is None:
            _service = SyllabusService()
        return _service


def progress() -> ProgressStore:
    global _progress
    with _lock:
        if _progress is None:
            _progress = ProgressStore(os.environ.get("SYLLABUDDY_DB", ROOT / "data" / "progress.db"))
        return _progress


def student_id(ctx: Context | None) -> str:
    headers = {k.lower(): v for k, v in ((ctx.headers or {}) if ctx is not None else {}).items()}
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        # Never store the token itself; a stable hash is enough to key history.
        return "tok-" + hashlib.sha256(auth[7:].encode()).hexdigest()[:16]
    sid = headers.get("x-syllabuddy-student", "").strip()
    return sid[:64] if sid else "anonymous"


def _error(error: Exception) -> dict[str, Any]:
    return {"error": str(error)}


# ---- syllabus lookups -----------------------------------------------------------

@mcp.tool(annotations=READ_ONLY)
def check_examinable(topic: str, subject: str | None = None, ctx: Context | None = None) -> dict[str, Any]:
    """Check whether a topic is examinable in the student's syllabus (AP or Singapore A-Level).

    Use for "is X in the syllabus?", "is X on my exam?", "do I need to know X?".
    Returns a verdict: 'excluded' (explicitly listed as not examinable, with the
    exact syllabus wording), 'examinable' (with the objective that covers it),
    'unclear' (only an approximate match, often assumed prior knowledge) or
    'not_in_syllabus'.

    Pass the topic exactly as specifically as the student said it: "skew lines"
    are examinable, but "the shortest distance between skew lines" is excluded.

    Args:
        topic: The topic in the student's words, e.g. "shortest distance between skew lines".
        subject: Optional subject, as the student says it: "AP Calc AB", "APUSH", "AP Chem", "H2 Maths", "H1 Physics" or a code like "9758" or "CALCAB".
    """
    try:
        result = service().check_examinable(topic, subject)
    except ValueError as error:
        return _error(error)
    objective = result.get("objective")
    if objective:
        progress().record_question(student_id(ctx), objective["objective_id"], topic)
    return result


@mcp.tool(annotations=READ_ONLY)
def find_objective(question: str, subject: str | None = None, ctx: Context | None = None) -> dict[str, Any]:
    """Find which official syllabus learning objective(s) a question belongs to.

    Use before explaining a concept, so the explanation sticks to what the
    syllabus requires. Returns the best objectives with id, title, what the
    syllabus requires, what it excludes, the source page, and a confidence
    ('matched', 'approximate' or 'weak').

    Args:
        question: The student's question or topic.
        subject: Optional subject, e.g. "AP Physics 1", "AP Statistics" or "H2 Chemistry".
    """
    try:
        result = service().find_objective(question, subject)
    except ValueError as error:
        return _error(error)
    if result["objectives"] and result["match"] != "weak":
        progress().record_question(student_id(ctx), result["objectives"][0]["objective_id"], question)
    return result


@mcp.tool(annotations=READ_ONLY)
def get_objective(objective_id: str) -> dict[str, Any]:
    """Get the full details of one syllabus objective by its id, e.g. "9758.3.3" or "CALCBC-10.8"."""
    try:
        return service().get_objective(objective_id)
    except ValueError as error:
        return _error(error)


@mcp.tool(annotations=READ_ONLY)
def list_subjects() -> dict[str, Any]:
    """List the exams, subjects and syllabus codes Syllabuddy has loaded."""
    return {"exams": ["College Board AP", "Alberta Diploma", "Singapore-Cambridge GCE A-Level"],
            "subjects": service().list_subjects()}


@mcp.tool(annotations=READ_ONLY)
def list_topics(subject: str) -> dict[str, Any]:
    """List the topics in a subject's syllabus, e.g. subject="H2 Physics"."""
    try:
        return service().list_topics(subject)
    except ValueError as error:
        return _error(error)


# ---- studying -------------------------------------------------------------------

@mcp.tool(annotations=RECORDS)
def start_quiz(subject: str | None = None, objective_id: str | None = None,
               ctx: Context | None = None) -> dict[str, Any]:
    """Pick a syllabus objective to quiz the student on.

    Prefers the student's weakest objective, otherwise one they haven't been
    quizzed on. Ask ONE short question that tests the returned objective and
    can be answered out loud in a sentence or two (never ask for code, a
    diagram or a long calculation), wait for their answer, judge it against
    'syllabus_requires', then call record_quiz_result.

    Args:
        subject: Optional subject, e.g. "AP Calc BC" or "H2 Maths".
        objective_id: Optional specific objective to quiz on.
    """
    sid = student_id(ctx)
    svc = service()
    try:
        if objective_id:
            card = svc.get_objective(objective_id)
        else:
            weak = [row["lo_id"] for row in progress().weakest(sid, limit=10)]
            lo = svc.pick_quiz_objective(subject, avoid=progress().quizzed_ids(sid), prefer=weak)
            card = svc.objective_card(lo)
    except ValueError as error:
        return _error(error)
    return {"quiz_objective": card,
            "next_step": ("Ask ONE question the student can answer in a sentence or two out loud "
                         "(no code, no diagrams, no calculations needing paper), then call record_quiz_result.")}


@mcp.tool(annotations=RECORDS)
def record_quiz_result(objective_id: str, correct: bool, note: str = "", ctx: Context | None = None) -> dict[str, Any]:
    """Record whether the student answered a quiz question correctly.

    Args:
        objective_id: The objective the question tested.
        correct: True if the answer met what the syllabus requires.
        note: Optional short note on what was missing.
    """
    sid = student_id(ctx)
    try:
        service().get_objective(objective_id)
    except ValueError as error:
        return _error(error)
    progress().record_quiz(sid, objective_id, correct, note)
    return {"recorded": True, "stats": progress().stats(sid)}


@mcp.tool(annotations=READ_ONLY)
def my_revision_list(ctx: Context | None = None) -> dict[str, Any]:
    """What the student should revise first, from their own history.

    Ranked by wrong quiz answers, then by objectives they keep asking about.
    Use for "what should I revise?", "what am I weak at?", "how am I doing?".
    """
    sid = student_id(ctx)
    svc = service()
    items = []
    for row in progress().weakest(sid):
        lo = svc.by_id.get(row["lo_id"])
        if lo is None:
            continue
        items.append(svc.objective_card(lo, full=False) | {
            "wrong_answers": int(row["wrong"] or 0), "times_asked": int(row["asked"] or 0)})
    stats = progress().stats(sid)
    return {"revise_first": items, "stats": stats,
            "note": None if items else "No history yet. Ask some questions or try a quiz first."}


# Deletion is confirmed by the server, not by trusting the model: the first call
# only arms a request, and only a later call (after the student has had time to
# say yes) deletes. A model that calls twice in one breath gets refused.
CONFIRM_MIN_SECONDS = 3.0
CONFIRM_MAX_SECONDS = 120.0
_pending_deletes: dict[str, float] = {}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False))
def clear_my_history(confirm: bool = False, ctx: Context | None = None) -> dict[str, Any]:
    """Delete everything Syllabuddy has stored about this student (questions, quiz results).

    Two steps, enforced by the server. First call: nothing is deleted; ask the
    student to confirm, using the counts returned. After the student says yes
    in a later turn, call again with confirm=true. If they say no, call with
    confirm=false to cancel.
    """
    sid = student_id(ctx)
    now = time.monotonic()
    requested = _pending_deletes.get(sid)
    stats = progress().stats(sid)

    if requested is None or now - requested > CONFIRM_MAX_SECONDS:
        _pending_deletes[sid] = now
        return {"deleted": False, "needs_confirmation": True, "stats": stats,
                "say": f"Ask the student to confirm deleting {stats['asked']} questions and "
                       f"{stats['quizzed']} quiz results. This cannot be undone."}
    if not confirm:
        _pending_deletes.pop(sid, None)
        return {"deleted": False, "cancelled": True}
    if now - requested < CONFIRM_MIN_SECONDS:
        return {"deleted": False, "needs_confirmation": True,
                "say": "Wait for the student to answer before deleting."}
    _pending_deletes.pop(sid, None)
    progress().clear(sid)
    return {"deleted": True, "stats": progress().stats(sid)}


def main() -> None:
    host = os.environ.get("SYLLABUDDY_HOST", "127.0.0.1")
    port = int(os.environ.get("SYLLABUDDY_PORT", "8765"))
    print("Loading syllabus and embedding model...", flush=True)
    service()
    print(f"Syllabuddy MCP server: http://{host}:{port}/mcp  (Streamable HTTP)", flush=True)
    mcp.run("streamable-http", host=host, port=port, streamable_http_path="/mcp")


if __name__ == "__main__":
    main()
