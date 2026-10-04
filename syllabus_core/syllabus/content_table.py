"""Parser for the "Topic/Sub-topics | Content" syllabus format.

Used by Mathematics 9758 and Further Mathematics 9649. The content outline is a
two-column table that reads like this once extracted:

    SECTION A: PURE MATHEMATICS
    6 Probability and Statistics
    6.5 Hypothesis testing            Include:
    •  concepts of null hypothesis ( H_0 ) and alternative
    hypotheses ( H_1 ), test statistic, critical region
    •  1-tail and 2-tail tests
    Exclude the use of the term 'Type I error'.

A numbered heading without a dot opens a topic; one with a dot opens a
sub-topic, which we treat as the learning objective. Bullets accumulate into
``include`` until an ``Exclude`` marker flips the target to ``exclude``.
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

# The content outline starts here. The table-of-contents entry for the same
# heading carries a trailing page number, so requiring end-of-line skips it.
START_HEADING = re.compile(r"^CONTENT OUTLINE$")

# Everything after the examinable content: prior knowledge and symbol glossaries.
END_HEADINGS = re.compile(r"^(ASSUMED KNOWLEDGE|MATHEMATICAL NOTATION)$")

SECTION = re.compile(r"^(SECTION [A-Z]:.*)$")

# A topic heading is a bare number and a name, e.g. "6 Probability and Statistics".
# Requiring the name to begin with a capital Latin letter rejects the formula
# fragments that also start with a digit, such as "1 1 1 1" and "1 β_2".
TOPIC = re.compile(r"^(\d{1,2})\s+([A-Z][A-Za-z].*)$")

SUBTOPIC = re.compile(r"^(\d+\.\d+)\s+(.+)$")
TABLE_HEADER = re.compile(r"^Topic/Sub-topics\b")

BULLET = "•"
SUB_BULLET = re.compile(r"^[-–—]\s*")
INCLUDE_MARKER = re.compile(r"\bInclude[:\s]*$")
EXCLUDE_MARKER = re.compile(r"^Exclude[sd]?\b[:\s]*")


class _ObjectiveBuilder:
    """Accumulates one sub-topic's bullets as we walk down the page."""

    def __init__(self, number: str, title: str, page: int) -> None:
        self.number = number
        self.title = title
        self.page = page
        self.include: list[str] = []
        self.exclude: list[str] = []
        self.in_exclude = False

    @property
    def _target(self) -> list[str]:
        return self.exclude if self.in_exclude else self.include

    def start_bullet(self, text: str) -> None:
        text = text.strip()
        if text:
            self._target.append(text)

    def extend_bullet(self, text: str) -> None:
        """Continue the current bullet, or start one if none is open."""
        text = text.strip()
        if not text:
            return
        target = self._target
        if target:
            target[-1] = f"{target[-1]} {text}"
        else:
            target.append(text)

    def extend_title(self, text: str) -> None:
        self.title = f"{self.title} {text.strip()}".strip()

    @property
    def has_content(self) -> bool:
        return bool(self.include or self.exclude)


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
    builder: _ObjectiveBuilder | None = None
    started = False
    # Topics are numbered consecutively through the document. Tracking the count
    # rejects stray formula lines that survive the heading pattern.
    expected_topic = 1

    def flush() -> None:
        nonlocal builder
        if builder is not None and topic is not None and builder.has_content:
            topic.learning_objectives.append(
                _build(builder, subject, topic, section, source)
            )
        builder = None

    for page in pages:
        for line in page.lines:
            if not started:
                started = bool(START_HEADING.match(line))
                continue

            if END_HEADINGS.match(line):
                flush()
                return subject

            if TABLE_HEADER.match(line):
                continue

            if match := SECTION.match(line):
                flush()
                section = match.group(1).strip()
                continue

            # Checked before the sub-topic pattern, which is stricter about the dot.
            if (match := TOPIC.match(line)) and int(match.group(1)) == expected_topic:
                flush()
                number, name = match.group(1), match.group(2).strip()
                expected_topic += 1
                topic = Topic(
                    topic_id=f"{subject_id}.{number}",
                    number=number,
                    name=name,
                    section=section,
                )
                subject.topics.append(topic)
                continue

            if match := SUBTOPIC.match(line):
                flush()
                if topic is None:
                    # Defensive: a sub-topic before any topic heading.
                    topic = Topic(
                        topic_id=f"{subject_id}.0",
                        number="0",
                        name="Uncategorised",
                        section=section,
                    )
                    subject.topics.append(topic)

                number = match.group(1)
                remainder = match.group(2)
                title, rest = _split_include(remainder)
                builder = _ObjectiveBuilder(number, title, page.page)
                if rest:
                    _consume_content(builder, rest)
                continue

            if builder is not None:
                _consume_content(builder, line)

    flush()
    return subject


def _split_include(text: str) -> tuple[str, str]:
    """Separate a sub-topic title from content sharing its row.

    The title sits in the left column and ``Include:`` in the right, so they
    arrive on one line: ``6.5 Hypothesis testing  Include:``.
    """
    if match := INCLUDE_MARKER.search(text):
        return text[: match.start()].strip(), ""

    # The title column can also share a row with the first bullet.
    if BULLET in text:
        head, _, tail = text.partition(BULLET)
        return head.strip(), f"{BULLET}{tail}"

    return text.strip(), ""


def _consume_content(builder: _ObjectiveBuilder, line: str) -> None:
    """Route one content line into the objective being built."""
    line = line.strip()
    if not line or INCLUDE_MARKER.match(line):
        return

    # A wrapped title continues in the left column, so it can share a row with
    # the first bullet: "dimensions  •  addition and subtraction of vectors".
    if BULLET in line and not line.startswith(BULLET):
        head, _, tail = line.partition(BULLET)
        head = head.strip()
        if head:
            if builder.has_content:
                builder.extend_bullet(head)
            else:
                builder.extend_title(head)
        line = f"{BULLET}{tail}"

    for part in _split_bullets(line):
        if match := EXCLUDE_MARKER.match(part):
            builder.in_exclude = True
            builder.start_bullet(part[match.end() :])
        elif part.startswith(BULLET):
            builder.start_bullet(part[len(BULLET) :])
        elif SUB_BULLET.match(part):
            # Sub-items qualify the bullet above them, so keep them attached
            # rather than promoting them to bullets in their own right.
            builder.extend_bullet(f"- {SUB_BULLET.sub('', part)}")
        else:
            builder.extend_bullet(part)


def _split_bullets(line: str) -> list[str]:
    """Split a row carrying several bullets back into individual ones."""
    if line.count(BULLET) <= 1:
        return [line]
    return [
        f"{BULLET}{part}".strip()
        for part in line.split(BULLET)
        if part.strip()
    ]


def _build(
    builder: _ObjectiveBuilder,
    subject: Subject,
    topic: Topic,
    section: str,
    source: str,
) -> LearningObjective:
    statement = "; ".join(builder.include)
    return LearningObjective(
        subject_id=subject.subject_id,
        subject_name=subject.name,
        topic_id=topic.topic_id,
        topic_name=topic.name,
        lo_id=f"{subject.subject_id}.{builder.number}",
        number=builder.number,
        title=builder.title,
        statement=statement,
        include=tuple(builder.include),
        exclude=tuple(builder.exclude),
        keywords=derive_keywords(builder.title, statement),
        exam_skills=derive_exam_skills(builder.title, statement),
        section=section,
        source=source,
        page=builder.page,
    )
