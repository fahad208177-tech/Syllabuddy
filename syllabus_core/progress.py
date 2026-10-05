"""Per-student study history in SQLite.

Alexa+ remembers a student's shoe size; it does not know which syllabus
objectives they keep getting stuck on. This does. Every event is stored
against a student id and a syllabus ``lo_id``, so "what should I revise?"
is a query, not a guess.

The student id comes from whoever is calling the MCP server. In the simulated
Alexa+ app it is a per-browser id; on real Alexa+ it would be the subject of
the OAuth token that account linking issues.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  TEXT NOT NULL,
    at          TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('asked', 'quiz')),
    lo_id       TEXT NOT NULL,
    correct     INTEGER,          -- quiz only: 1 right, 0 wrong
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_student ON events(student_id, lo_id);
CREATE TABLE IF NOT EXISTS courses (
    student_id  TEXT PRIMARY KEY,
    subject_ids TEXT NOT NULL,    -- JSON list, e.g. ["CALCBC", "SATM"]
    exam_date   TEXT,             -- ISO date of the next exam, if the student said it
    updated     TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProgressStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One connection shared across the server's worker threads, guarded by a lock.
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()

    def _write(self, sql: str, args: tuple) -> None:
        with self._lock:
            self._db.execute(sql, args)
            self._db.commit()

    def _read(self, sql: str, args: tuple) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def record_question(self, student_id: str, lo_id: str, question: str) -> None:
        self._write("INSERT INTO events (student_id, at, kind, lo_id, detail) VALUES (?, ?, 'asked', ?, ?)",
                    (student_id, _now(), lo_id, question[:500]))

    def record_quiz(self, student_id: str, lo_id: str, correct: bool, note: str = "") -> None:
        self._write("INSERT INTO events (student_id, at, kind, lo_id, correct, detail) VALUES (?, ?, 'quiz', ?, ?, ?)",
                    (student_id, _now(), lo_id, int(bool(correct)), note[:500]))

    def weakest(self, student_id: str, limit: int = 5) -> list[dict]:
        """Objectives to revise first.

        Wrong quiz answers count most. Asking about an objective repeatedly is a
        weaker signal (you're unsure about it), so it ranks objectives that have
        not been quizzed yet. Objectives answered right every time drop out.
        """
        rows = self._read(
            """
            SELECT lo_id,
                   SUM(kind = 'quiz')                    AS quizzed,
                   SUM(kind = 'quiz' AND correct = 0)    AS wrong,
                   SUM(kind = 'asked')                   AS asked,
                   MAX(at)                               AS last_seen
            FROM events WHERE student_id = ?
            GROUP BY lo_id
            HAVING wrong > 0 OR quizzed = 0
            ORDER BY (wrong * 3 + asked) DESC, last_seen DESC
            LIMIT ?
            """,
            (student_id, limit),
        )
        return [dict(row) for row in rows]

    def history(self, student_id: str, limit: int = 20) -> list[dict]:
        rows = self._read("SELECT at, kind, lo_id, correct, detail FROM events WHERE student_id = ? "
                          "ORDER BY id DESC LIMIT ?", (student_id, limit))
        return [dict(row) for row in rows]

    def quizzed_ids(self, student_id: str) -> list[str]:
        return [r["lo_id"] for r in self._read(
            "SELECT DISTINCT lo_id FROM events WHERE student_id = ? AND kind = 'quiz'", (student_id,))]

    def touched_ids(self, student_id: str) -> list[str]:
        return [r["lo_id"] for r in self._read(
            "SELECT DISTINCT lo_id FROM events WHERE student_id = ?", (student_id,))]

    def stats(self, student_id: str) -> dict:
        row = self._read(
            "SELECT SUM(kind='asked') AS asked, SUM(kind='quiz') AS quizzed, SUM(kind='quiz' AND correct=1) AS right "
            "FROM events WHERE student_id = ?", (student_id,))[0]
        return {k: int(row[k] or 0) for k in ("asked", "quizzed", "right")}

    def set_courses(self, student_id: str, subject_ids: list[str], exam_date: str | None = None) -> None:
        self._write("INSERT INTO courses (student_id, subject_ids, exam_date, updated) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(student_id) DO UPDATE SET subject_ids = excluded.subject_ids, "
                    "exam_date = excluded.exam_date, updated = excluded.updated",
                    (student_id, json.dumps(subject_ids), exam_date, _now()))

    def courses(self, student_id: str) -> dict:
        """The student's courses: {"subject_ids": [...], "exam_date": "2027-05-11" or None}."""
        rows = self._read("SELECT subject_ids, exam_date FROM courses WHERE student_id = ?", (student_id,))
        if not rows:
            return {"subject_ids": [], "exam_date": None}
        return {"subject_ids": json.loads(rows[0]["subject_ids"]), "exam_date": rows[0]["exam_date"]}

    def clear(self, student_id: str) -> None:
        self._write("DELETE FROM events WHERE student_id = ?", (student_id,))
        self._write("DELETE FROM courses WHERE student_id = ?", (student_id,))
