"""Parser for Economics's "numbered item + Additional information" format.

Used by Economics 8843 (H1) and 9570 (H2). The content outline is a
two-column table, but unlike History and Geography its column header shares
a row with the *first* content item rather than heading the table on a row
of its own:

    Theme 1.1 Scarcity as the Central Economic Problem
    Economics Content
    1.1.1 Scarcity, choice and resource allocation   Additional information
    a. The Central Economic Problem is scarcity, arising from limited
    resources and unlimited wants
    b. Scarcity implies that choices have to be made ...

``extract_table_columns`` needs a clean header row to anchor on and cannot
be used here. "Additional information" is exam-scope commentary (typically
"... is/is not required"), not examinable content in its own right, so
rather than build another bespoke column splitter this drops it outright:
``extract_pages_excluding`` discards every span to the right of where that
column starts, and the remaining single column is read exactly as
``extract_pages`` reads any other syllabus.

Each "Theme N.M Title" becomes a :class:`Topic`; each numbered item under it
("N.M.K Title") becomes a :class:`LearningObjective`, with its lettered
points ("a.", "b.", ...) as ``include``.
"""

from __future__ import annotations

import re

from syllabus_core.pdf_text import PageText, extract_pages_excluding, strip_furniture
from syllabus_core.syllabus.schema import (
    LearningObjective,
    Subject,
    Topic,
    derive_exam_skills,
    derive_keywords,
)

# Measured from the PDF: the "Additional information" column starts around
# x=395; the primary column's own wrapped lines stay well under this even at
# their widest observed extent (~360), so a threshold of 385 keeps a safety
# margin on both sides without needing to guess more precisely.
ADDITIONAL_INFO_MIN_X0 = 385.0

START_HEADING = re.compile(r"^SYLLABUS CONTENT$")
TOPIC_HEADING = re.compile(r"^Theme (\d+\.\d+)\s+(.+?)(\s*\(continued\))?$")
ITEM_HEADING = re.compile(r"^(\d+\.\d+\.\d+)\s+(.+)$")
LETTER_POINT = re.compile(r"^([a-z])\.\s+(.+)$")
TRAILER_HEADING = re.compile(r"^Concepts and Tools of Analysis$")

NOISE_LINES = {"Economics Content"}


class _ItemBuilder:
    def __init__(self, number: str, title: str, page: int) -> None:
        self.number = number
        self.title = title
        self.page = page
        self.points: list[str] = []

    def start_point(self, text: str) -> None:
        self.points.append(text.strip())

    def extend(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self.points:
            self.points[-1] = f"{self.points[-1]} {text}"
        else:
            self.title = f"{self.title} {text}".strip()


def parse(
    pages: list[PageText],  # unused: this format needs the raw PDF path
    subject_id: str,
    subject_name: str,
    code: str,
    level: str,
    source: str,
    *,
    path: str | None = None,
) -> Subject:
    """Build a :class:`Subject` from an Economics-format syllabus PDF."""
    if path is None:
        raise ValueError("economics_table.parse requires the source PDF path")

    subject = Subject(
        subject_id=subject_id, name=subject_name, code=code, level=level, source=source
    )

    content_pages = strip_furniture(extract_pages_excluding(path, ADDITIONAL_INFO_MIN_X0))

    topic: Topic | None = None
    item: _ItemBuilder | None = None
    last_topic_number: str | None = None
    started = False
    in_trailer = False

    def flush_item() -> None:
        nonlocal item
        if item is not None and topic is not None and item.points:
            topic.learning_objectives.append(_build(item, subject, topic, source))
        item = None

    def flush_topic() -> None:
        nonlocal topic
        flush_item()
        if topic is not None and topic.learning_objectives:
            subject.topics.append(topic)
        topic = None

    for page in content_pages:
        for line in page.lines:
            if not started:
                started = bool(START_HEADING.match(line))
                continue

            if match := TOPIC_HEADING.match(line):
                number = match.group(1)
                if number == last_topic_number:
                    # The "(continued)" reprint at the top of a page break,
                    # not a second Theme sharing the same number.
                    in_trailer = False
                    continue
                flush_topic()
                topic = Topic(
                    topic_id=f"{subject_id}.{number}",
                    number=number,
                    name=match.group(2).strip(),
                )
                last_topic_number = number
                in_trailer = False
                continue

            if topic is None:
                continue

            if match := ITEM_HEADING.match(line):
                flush_item()
                item = _ItemBuilder(match.group(1), match.group(2).strip(), page.page)
                in_trailer = False
                continue

            if TRAILER_HEADING.match(line):
                # "Concepts and Tools of Analysis" is a keyword recap after
                # each item's lettered points, not further content of its own.
                flush_item()
                in_trailer = True
                continue

            if in_trailer or line in NOISE_LINES:
                continue

            if item is None:
                continue

            if match := LETTER_POINT.match(line):
                item.start_point(match.group(2))
            else:
                item.extend(line)

    flush_topic()
    return subject


def _build(item: _ItemBuilder, subject: Subject, topic: Topic, source: str) -> LearningObjective:
    statement = "; ".join(item.points)
    return LearningObjective(
        subject_id=subject.subject_id,
        subject_name=subject.name,
        topic_id=topic.topic_id,
        topic_name=topic.name,
        lo_id=f"{subject.subject_id}.{item.number}",
        number=item.number,
        title=item.title[:100],
        statement=statement,
        include=tuple(item.points),
        exclude=(),
        keywords=derive_keywords(topic.name, item.title, statement),
        exam_skills=derive_exam_skills(item.title, statement),
        section=topic.name,
        source=source,
        page=item.page,
    )
