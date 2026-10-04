"""Parser for the "Topic / Content / Learning Outcomes" syllabus format.

Used by Physics 9478 and Chemistry 9729. Unlike the Mathematics table or
Computing's numbered outcomes, this format separates topic-level themes from the
actual examinable objectives:

    SECTION I FOUNDATIONS OF PHYSICS      <- section
    1 Quantities and Measurement           <- topic
    Content
    •  Physical quantities and SI units    <- topic-level themes, not objectives
    •  Errors and uncertainties
    Learning Outcomes
    (a) recall and use the following SI base quantities ...   <- the objectives
    (b) recall and use the following prefixes ...

Chemistry additionally nests some topics into lettered sub-topics
(``10.1 Acid-base Equilibria``, ``10.2 Solubility Equilibria``); each becomes its
own topic in the schema, since only they carry a "Learning Outcomes" section.
A bare parent topic that has no outcomes of its own (because all its content
lives in its sub-topics) is dropped rather than kept as an empty topic.

Neither subject marks exclusions with an "Exclude:" heading the way Mathematics
does. Where content is out of scope it appears inline, e.g. "(knowledge of
wave functions is not required)", so it is left as part of the outcome text
rather than pulled into a separate field.
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

START_HEADINGS = re.compile(r"^(CONTENT OVERVIEW|CONTENT MAP|STRUCTURE OF SYLLABUS)$")
END_HEADINGS = re.compile(
    r"^(PRACTICAL ASSESSMENT|MATHEMATICAL REQUIREMENTS|GLOSSARY OF TERMS"
    r"|TEXTBOOKS( AND REFERENCES)?)$"
)

SECTION = re.compile(r"^(SECTION\s+[IVXLCDM]+\b.*|CORE IDEA\s+\d+.*)$")

# Biology numbers its Extension Topic(s) by letter rather than by digit (e.g.
# "A Impact of Climate Change on Animals and Plants", "B Infectious
# Diseases"). Letter-numbered headings are only tried once this marker has
# been seen, since a bare "single capital letter, space, capitalised word" is
# otherwise a completely ordinary way for an English sentence to start.
EXTENSION_MARKER = re.compile(r"^(I{1,3}V?\s+)?EXTENSION TOPICS?$")
EXTENSION_TOPIC = re.compile(r"^([A-Z])\s+([A-Z][A-Za-z].*)$")

# A topic name must start with two letters, not one: this is what rejects
# formula fragments like "1 Q Q_{12}" that survive as stray lines from a
# scrambled equation, the same failure mode fixed for Mathematics in
# content_table.py.
TOPIC = re.compile(r"^(\d{1,2})\.?\s+([A-Z][A-Za-z].*)$")
SUBTOPIC = re.compile(r"^(\d{1,2}\.\d{1,2})\s+([A-Z][A-Za-z].*)$")

CONTENT_HEADING = re.compile(r"^Content$")
LEARNING_OUTCOMES_HEADING = re.compile(r"^Learning Outcomes$")

CONTENT_BULLET = re.compile(r"^[•●▪]\s*(.+)$")
OUTCOME = re.compile(r"^\(([a-z])\)\s+(.+)$")
# A lettered outcome can itself list roman-numeral sub-items, e.g. "(l) ...
# based on: (i) half-life ... (ii) penetrating abilities ...". "(i)" is
# ambiguous with the 9th top-level letter — resolved in the parse loop by only
# accepting OUTCOME when the letter matches the expected next one in sequence.
SUB_OUTCOME = re.compile(r"^\((i{1,3}|iv|vi{0,3}|ix|x)\)\s+(.+)$")


class _TopicBuilder:
    def __init__(self, number: str, name: str) -> None:
        self.number = number
        self.name = name
        self.content_themes: list[str] = []
        self.outcomes: list[_OutcomeBuilder] = []

    def to_topic(self, subject_id: str, section: str) -> Topic:
        return Topic(
            topic_id=f"{subject_id}.{self.number}",
            number=self.number,
            name=self.name,
            section=section,
            statement="; ".join(self.content_themes),
        )


class _OutcomeBuilder:
    def __init__(self, letter: str, page: int) -> None:
        self.letter = letter
        self.parts: list[str] = []
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
    topic: _TopicBuilder | None = None
    outcome: _OutcomeBuilder | None = None
    # "content" while reading the topic-level bullet themes, "outcomes" once
    # "Learning Outcomes" has been seen, "" before either has started.
    mode = ""
    started = False
    # Flipped on once an "Extension Topic" marker is seen, so a letter-numbered
    # heading is only tried in the part of the document known to use them.
    letter_topics_allowed = False
    # Outcomes run a, b, c, ... within a topic; only a line matching this exact
    # next letter is accepted as a new top-level outcome, which is what
    # disambiguates "(i)" the letter from "(i)" the roman-numeral sub-item.
    next_letter = "a"

    # Flattened so a heading can be confirmed by peeking at the line that
    # follows it, including across a page break.
    flat: list[tuple[int, str]] = [
        (page.page, line) for page in pages for line in page.lines
    ]

    def flush_outcome() -> None:
        nonlocal outcome
        if outcome is not None and topic is not None and outcome.statement:
            topic.outcomes.append(outcome)
        outcome = None

    def flush_topic() -> None:
        nonlocal topic
        flush_outcome()
        # A parent topic whose content lives entirely in numbered sub-topics
        # (Chemistry's 10.1/10.2 pattern) has no outcomes of its own and would
        # otherwise appear as a hollow topic with zero learning objectives.
        if topic is not None and topic.outcomes:
            built = topic.to_topic(subject_id, section)
            for outcome_builder in topic.outcomes:
                built.learning_objectives.append(
                    _build(outcome_builder, subject, built, source)
                )
            subject.topics.append(built)
        topic = None

    total = len(flat)
    index = 0
    while index < total:
        page_number, line = flat[index]
        index += 1

        if not started:
            started = bool(START_HEADINGS.match(line))
            continue

        if END_HEADINGS.match(line):
            flush_topic()
            return subject

        if match := SECTION.match(line):
            flush_topic()
            section = match.group(1).strip()
            continue

        if EXTENSION_MARKER.match(line):
            letter_topics_allowed = True
            continue

        # A numbered heading only becomes a real topic/sub-topic once a
        # "Content" or "Learning Outcomes" marker is reached before any other
        # heading-shaped line interrupts (a short lead-in paragraph, as
        # Chemistry's extension topics carry, is allowed in between). That is
        # what tells a real heading apart from a summary list of topic names,
        # which some subjects (e.g. Biology's "STRUCTURE OF SYLLABUS") print
        # ahead of the real section and which would otherwise be mistaken for
        # topics of their own, throwing off a purely sequential topic count.
        heading = SUBTOPIC.match(line) or TOPIC.match(line)
        if heading is None and letter_topics_allowed:
            heading = EXTENSION_TOPIC.match(line)
        if match := heading:
            if _confirmed_by_body(flat, index, total):
                flush_topic()
                topic = _TopicBuilder(match.group(1), match.group(2).strip())
                mode = ""
                next_letter = "a"
                continue
            # Otherwise this is a summary-list entry or a stray numbered line;
            # fall through and let the general handling below deal with it.

        if topic is None:
            continue

        if CONTENT_HEADING.match(line):
            mode = "content"
            continue

        if LEARNING_OUTCOMES_HEADING.match(line):
            mode = "outcomes"
            continue

        if mode == "content":
            if bullet := CONTENT_BULLET.match(line):
                topic.content_themes.append(bullet.group(1).strip())
            elif topic.content_themes:
                # A wrapped continuation of the previous theme.
                topic.content_themes[-1] = f"{topic.content_themes[-1]} {line.strip()}"
            continue

        if mode == "outcomes":
            if (match := OUTCOME.match(line)) and match.group(1) == next_letter:
                flush_outcome()
                outcome = _OutcomeBuilder(match.group(1), page_number)
                outcome.extend(match.group(2))
                next_letter = chr(ord(next_letter) + 1)
            elif match := SUB_OUTCOME.match(line):
                if outcome is not None:
                    outcome.extend(f"({match.group(1)}) {match.group(2)}")
            elif outcome is not None:
                outcome.extend(line)

    flush_topic()
    return subject


# How many lines a heading candidate is allowed to look ahead for its "Content"
# or "Learning Outcomes" marker. A real heading is followed by at most a short
# lead-in paragraph (Chemistry's extension topics carry two sentences of
# prose); anything longer than this is not worth treating as the same topic.
CONFIRMATION_LOOKAHEAD = 15


def _confirmed_by_body(flat: list[tuple[int, str]], index: int, total: int) -> bool:
    """Whether the heading candidate just seen is followed by real content.

    Scans forward from ``index`` for a "Content" or "Learning Outcomes"
    marker, allowing ordinary prose in between but bailing out as soon as
    another heading-shaped line (a new topic, sub-topic, section, or the end
    of the syllabus content) appears first -- that means the candidate was
    never confirmed and was just a summary-list entry or a stray number.
    """
    for offset in range(CONFIRMATION_LOOKAHEAD):
        position = index + offset
        if position >= total:
            return False
        candidate = flat[position][1]
        if CONTENT_HEADING.match(candidate) or LEARNING_OUTCOMES_HEADING.match(candidate):
            return True
        if (
            SECTION.match(candidate)
            or TOPIC.match(candidate)
            or SUBTOPIC.match(candidate)
            or END_HEADINGS.match(candidate)
        ):
            return False
    return False


def _build(
    outcome: _OutcomeBuilder,
    subject: Subject,
    topic: Topic,
    source: str,
) -> LearningObjective:
    statement = outcome.statement
    return LearningObjective(
        subject_id=subject.subject_id,
        subject_name=subject.name,
        topic_id=topic.topic_id,
        topic_name=topic.name,
        lo_id=f"{subject.subject_id}.{topic.number}.{outcome.letter}",
        number=f"{topic.number}.{outcome.letter}",
        title=statement.split(".")[0].strip()[:100] or statement[:100],
        statement=statement,
        include=(statement,),
        exclude=(),
        keywords=derive_keywords(topic.name, statement),
        exam_skills=derive_exam_skills(statement),
        section=topic.section,
        source=source,
        page=outcome.page,
    )
