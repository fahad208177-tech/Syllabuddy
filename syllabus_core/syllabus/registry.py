"""Which parser handles which syllabus, and how to build syllabus.json.

Adding a subject means dropping its PDF into ``resources/syllabus/`` and adding
one :class:`SyllabusSource` entry here. If a new subject uses a layout no
existing parser understands, write a new parser module exposing the same
``parse(pages, subject_id, subject_name, code, level, source, *, path)``
signature. ``pages`` is the syllabus PDF already extracted single-column and
furniture-stripped, which is all the science/maths parsers need; a parser for
a genuinely multi-column layout (see ``history_table.py``,
``geography_table.py``, ``economics_table.py``) instead re-reads the raw PDF
itself from ``path`` (passed by :func:`parse_syllabus` below), since a
single-column extraction interleaves multiple columns' text into nonsense.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from syllabus_core.syllabus import (
    content_table,
    economics_table,
    geography_table,
    history_table,
    lettered_outcomes,
    outcomes,
)
from syllabus_core.syllabus.schema import LearningObjective, Subject, Topic

Parser = Callable[..., Subject]

EXAM_BOARD = "Singapore-Cambridge"
# Informational only (each Subject carries its own accurate H1/H2 in `level`)
# -- the active set spans both, not just H2.
QUALIFICATION = "GCE Advanced Level (H1/H2)"


@dataclass(frozen=True)
class SyllabusSource:
    filename: str
    code: str
    name: str
    level: str
    parser: Parser

    @property
    def subject_id(self) -> str:
        return self.code


SOURCES: tuple[SyllabusSource, ...] = (
    SyllabusSource("Physics_syllabus.pdf", "9478", "Physics", "H2", lettered_outcomes.parse),
    SyllabusSource("H2Computing.pdf", "9569", "Computing", "H2", outcomes.parse),
    SyllabusSource("Chemistry_syllabus.pdf", "9729", "Chemistry", "H2", lettered_outcomes.parse),
    SyllabusSource("H1Physics.pdf", "8867", "Physics", "H1", lettered_outcomes.parse),
    SyllabusSource("H1Chemistry.pdf", "8873", "Chemistry", "H1", lettered_outcomes.parse),
    SyllabusSource("H1Biology.pdf", "8876", "Biology", "H1", lettered_outcomes.parse),
    SyllabusSource("H2Biology.pdf", "9477", "Biology", "H2", lettered_outcomes.parse),
    SyllabusSource("H1Math.pdf", "8865", "Mathematics", "H1", content_table.parse),
    SyllabusSource("H2math.pdf", "9758", "Mathematics", "H2", content_table.parse),
    SyllabusSource("H2History.pdf", "9174", "History", "H2", history_table.parse),
    SyllabusSource("H1Geography.pdf", "8834", "Geography", "H1", geography_table.parse),
    SyllabusSource("H2Geography.pdf", "9173", "Geography", "H2", geography_table.parse),
    SyllabusSource("H1Economics.pdf", "8843", "Economics", "H1", economics_table.parse),
    SyllabusSource("H2economics.pdf", "9570", "Economics", "H2", economics_table.parse),
)


def find_source(filename: str) -> SyllabusSource | None:
    for source in SOURCES:
        if source.filename.lower() == filename.lower():
            return source
    return None


def parse_syllabus(pdf_path: str | Path, source: SyllabusSource) -> Subject:
    # Imported here so loading syllabus.json never needs the PDF toolchain.
    from syllabus_core.pdf_text import extract_pages, strip_furniture

    pages = strip_furniture(extract_pages(pdf_path))
    return source.parser(
        pages,
        source.subject_id,
        source.name,
        source.code,
        source.level,
        source.filename,
        path=pdf_path,
    )


def build(folder: str | Path) -> dict[str, Any]:
    """Parse every registered syllabus PDF found in ``folder``."""
    folder_path = Path(folder)
    subjects: list[Subject] = []

    for source in SOURCES:
        pdf_path = folder_path / source.filename
        if not pdf_path.exists():
            continue
        subjects.append(parse_syllabus(pdf_path, source))

    return {
        "exam_board": EXAM_BOARD,
        "qualification": QUALIFICATION,
        "generated_by": "scripts/build_syllabus.py",
        "subjects": [subject.to_dict() for subject in subjects],
    }


def load(path: str | Path) -> list[Subject]:
    """Read a built syllabus.json back into typed objects."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    subjects: list[Subject] = []

    for raw_subject in data.get("subjects", []):
        subject = Subject(
            subject_id=raw_subject["subject_id"],
            name=raw_subject["name"],
            code=raw_subject.get("code", raw_subject["subject_id"]),
            level=raw_subject.get("level", ""),
            source=raw_subject.get("source", ""),
        )
        for raw_topic in raw_subject.get("topics", []):
            topic = Topic(
                topic_id=raw_topic["topic_id"],
                number=raw_topic.get("number", ""),
                name=raw_topic["name"],
                section=raw_topic.get("section", ""),
                statement=raw_topic.get("statement", ""),
            )
            for raw in raw_topic.get("learning_objectives", []):
                topic.learning_objectives.append(
                    LearningObjective(
                        subject_id=subject.subject_id,
                        subject_name=subject.name,
                        topic_id=topic.topic_id,
                        topic_name=topic.name,
                        lo_id=raw["lo_id"],
                        number=raw.get("number", ""),
                        title=raw.get("title", ""),
                        statement=raw.get("statement", ""),
                        include=tuple(raw.get("include", [])),
                        exclude=tuple(raw.get("exclude", [])),
                        keywords=tuple(raw.get("keywords", [])),
                        exam_skills=tuple(raw.get("exam_skills", [])),
                        section=topic.section,
                        source=raw.get("source", subject.source),
                        page=raw.get("page", 0),
                    )
                )
            subject.topics.append(topic)
        subjects.append(subject)

    return subjects
