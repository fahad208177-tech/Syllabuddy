"""Parser for the numbered "Learning Outcome" syllabus format.

Used by Computing 9569, whose content outline reads:

    Section 2: Programming
    Units
    2.1 Coding Standards          <- summary list, ignored
    2.2 Programming Elements and Constructs
    2.1 Coding Standards          <- the real unit heading
    Use common coding standards for programming style.   <- unit statement
    Ref.  Learning Outcome
    2.1.1 Use indentation and white space.
    2.1.2 Use naming conventions (e.g. meaningful identifier names).

Each unit is announced twice: once in a summary list under ``Units`` and once as
the heading of its own block. Only the second is followed by a ``Ref.`` header,
so we treat a ``Ref.`` line as the signal that the most recent unit heading was
the real one, and discard whatever the summary list left pending.
"""

from __future__ import annotations

import re

from syllabus_core.pdf_text import PageText
from syllabus_core.syllabus.schema import (
    LearningObjective,
    Subject,
    Topic,
    derive_exam_skills,
    derive_keywords,
)

START_HEADING = re.compile(r"^LEARNING OUTCOMES$")
SECTION = re.compile(r"^Section (\d+):\s*(.+)$")
UNIT = re.compile(r"^(\d+\.\d+)\.?\s+(\D.*)$")
OUTCOME = re.compile(r"^(\d+\.\d+\.\d+)\s+(.+)$")
REF_HEADER = re.compile(r"^Ref\.?\s+Learning Outcomes?$")
UNITS_SUMMARY = re.compile(r"^Units$")
EXCLUDE_MARKER = re.compile(r"^Exclude[sd]?\b[:\s]*")
SUB_BULLET = re.compile(r"^[-–—•]\s*")


class _OutcomeBuilder:
    def __init__(self, number: str, statement: str, page: int) -> None:
        self.number = number
        self.parts: list[str] = [statement.strip()]
        self.exclude: list[str] = []
        self.page = page

    def extend(self, text: str) -> None:
        text = text.strip()
        if text:
            self.parts.append(text)

    @property
    def statement(self) -> str:
        return " ".join(part for part in self.parts if part).strip()


def parse(
    pages: list[PageText],
    subject_id: str,
    subject_name: str,
    code: str,
    level: str,
    source: str,
    *,
    path: str | None = None,
) -> Subject:
    subject = Subject(
        subject_id=subject_id, name=subject_name, code=code, level=level, source=source
    )

    section = ""
    topic: Topic | None = None
    builder: _OutcomeBuilder | None = None

    # A unit heading is only confirmed once a "Ref." header follows it.
    pending_unit: tuple[str, str] | None = None
    pending_statement: list[str] = []
    in_summary = False
    started = False

    def flush_outcome() -> None:
        nonlocal builder
        if builder is not None and topic is not None:
            topic.learning_objectives.append(_build(builder, subject, topic, section, source))
        builder = None

    for page in pages:
        for line in page.lines:
            if not started:
                started = bool(START_HEADING.match(line))
                continue

            if match := SECTION.match(line):
                flush_outcome()
                section = f"Section {match.group(1)}: {match.group(2).strip()}"
                pending_unit = None
                pending_statement = []
                in_summary = False
                continue

            if UNITS_SUMMARY.match(line):
                in_summary = True
                continue

            if REF_HEADER.match(line):
                # Confirms the pending heading is a real unit, not a summary entry.
                flush_outcome()
                if pending_unit is not None:
                    number, name = pending_unit
                    topic = Topic(
                        topic_id=f"{subject_id}.{number}",
                        number=number,
                        name=name,
                        section=section,
                    )
                    topic.statement = " ".join(pending_statement).strip()
                    subject.topics.append(topic)
                pending_unit = None
                pending_statement = []
                continue

            if match := OUTCOME.match(line):
                flush_outcome()
                builder = _OutcomeBuilder(match.group(1), match.group(2), page.page)
                continue

            if match := UNIT.match(line):
                flush_outcome()
                pending_unit = (match.group(1), match.group(2).strip())
                pending_statement = []
                in_summary = False
                continue

            if in_summary:
                continue

            if builder is not None:
                if match := EXCLUDE_MARKER.match(line):
                    builder.exclude.append(line[match.end() :].strip())
                elif SUB_BULLET.match(line):
                    builder.extend(f"- {SUB_BULLET.sub('', line)}")
                else:
                    builder.extend(line)
            elif pending_unit is not None:
                # Prose between a unit heading and its "Ref." header is the
                # unit-level statement describing what the whole unit covers.
                pending_statement.append(line)

    flush_outcome()
    return subject


def _build(
    builder: _OutcomeBuilder,
    subject: Subject,
    topic: Topic,
    section: str,
    source: str,
) -> LearningObjective:
    statement = builder.statement
    # The outcome's first sentence works as its title; the rest is detail.
    title = statement.split(".")[0].strip() or statement[:80]
    return LearningObjective(
        subject_id=subject.subject_id,
        subject_name=subject.name,
        topic_id=topic.topic_id,
        topic_name=topic.name,
        lo_id=f"{subject.subject_id}.{builder.number}",
        number=builder.number,
        title=title,
        statement=statement,
        include=(statement,),
        exclude=tuple(builder.exclude),
        keywords=derive_keywords(topic.name, statement),
        exam_skills=derive_exam_skills(statement),
        section=section,
        source=source,
        page=builder.page,
    )
