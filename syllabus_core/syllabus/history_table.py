"""Parser for History's "Concepts / Content / Learning Outcomes" table format.

Used by History 9174. Unlike every other syllabus in this project, History is
printed as a genuine side-by-side table rather than a single flowing column:

    CONCEPTS            CONTENT                          LEARNING OUTCOMES
    (Students           (Students study:)                (Students are able to:)
    understand:)
    Historical           Emergence of the Cold War after   * evaluate the causes
    Concepts             the Second World War              of the Cold War
    * accounts           * Causes for the emergence of
    * chronology         tensions between the USA and
                          USSR

A naive single-column read interleaves the three columns word-by-word into
nonsense, since they often share a vertical position on the page.
``syllabus_core.pdf_text.extract_table_columns`` is what repairs this -- see that
function's docstring for how the columns are actually told apart.

Each Theme (e.g. "Theme I: The Development of the Cold War (1945-1991)") maps
to a :class:`Topic`. Within a Theme, the table has no per-outcome numbering
the way the sciences' lettered outcomes do, so each bullet in the LEARNING
OUTCOMES column becomes its own objective, numbered sequentially. The
CONCEPTS and CONTENT columns are not aligned closely enough to individual
outcomes to attribute a bullet to just one of them, so both are folded into
the topic-level statement shared by every outcome in that Theme -- the same
role "Content" plays for the sciences' lettered-outcomes format, just
covering the whole Theme instead of one topic.
"""

from __future__ import annotations

import re

from syllabus_core.pdf_text import PageText, extract_pages, extract_table_columns, strip_furniture
from syllabus_core.syllabus.schema import (
    LearningObjective,
    Subject,
    Topic,
    derive_exam_skills,
    derive_keywords,
)

START_HEADING = re.compile(r"^SYLLABUS CONTENT$")
END_HEADING = re.compile(r"^APPENDI(X|CES)\b")

PAPER = re.compile(r"^Paper (\d+):\s*(.+)$")

# A Theme title is printed as a lone, fully upper-case line -- checked with
# ``str.isupper()`` rather than a character class, since titles carry dashes
# ("1945-1991") using an en dash, not the ASCII hyphen a regex class would
# have to be told about explicitly. These are the other all-caps headings
# that can appear in the same region of the document and must not be
# mistaken for a Theme title.
NOT_A_THEME = {
    "CONCEPTS CONTENT LEARNING OUTCOMES",
    "OVERVIEW MAKING CONNECTIONS",
}
MIN_THEME_TITLE_LENGTH = 10

COLUMN_LABELS = ("CONCEPTS", "CONTENT", "LEARNING OUTCOMES")
RESET_LABELS = (("OVERVIEW", "MAKING CONNECTIONS"),)

BULLET = re.compile(r"^[•●▪]\s*(.+)$")
NOISE_LINES = {"(continued)", "Content Concepts"}


def parse(
    pages: list[PageText],  # unused: this format needs raw page/column access
    subject_id: str,
    subject_name: str,
    code: str,
    level: str,
    source: str,
    *,
    path: str | None = None,
) -> Subject:
    """Build a :class:`Subject` from a History-format syllabus PDF.

    Unlike the other parsers, this one needs the original PDF path (passed
    separately by the registry) rather than pre-extracted single-column
    pages, since it must re-read the raw page layout to split the table into
    columns.
    """
    if path is None:
        raise ValueError("history_table.parse requires the source PDF path")

    subject = Subject(
        subject_id=subject_id, name=subject_name, code=code, level=level, source=source
    )

    events = _scan_theme_boundaries(pages)
    if not events:
        return subject

    columns = extract_table_columns(path, COLUMN_LABELS, reset_labels=RESET_LABELS)
    concepts_by_page = _lines_by_page(columns["CONCEPTS"])
    content_by_page = _lines_by_page(columns["CONTENT"])
    outcomes_by_page = _lines_by_page(columns["LEARNING OUTCOMES"])

    themes = [event for event in events if event[0] == "theme"]

    # Resolve outcomes for every Theme first, so a Theme that turns out to
    # have none (nothing landed in its page range) does not still consume a
    # number in the sequence and leave a gap, e.g. "2.1, 2.3" with no "2.2".
    resolved: list[tuple[str, str, list[str], list[str]]] = []
    for position, (_, page_number, title) in enumerate(themes):
        end_page = themes[position + 1][1] if position + 1 < len(themes) else 10**6
        paper_number = _paper_at(events, page_number)
        page_range = range(page_number, end_page)

        outcomes = _merge_bullets(_collect(outcomes_by_page, page_range))
        if not outcomes:
            continue

        content_lines = _collect(content_by_page, page_range)
        concept_lines = _collect(concepts_by_page, page_range)
        resolved.append((paper_number, title, outcomes, content_lines, concept_lines, page_number))

    theme_index_within_paper: dict[str, int] = {}
    for paper_number, title, outcomes, content_lines, concept_lines, page_number in resolved:
        theme_index_within_paper[paper_number] = theme_index_within_paper.get(paper_number, 0) + 1
        theme_number = f"{paper_number}.{theme_index_within_paper[paper_number]}"

        statement = "; ".join(content_lines)
        topic = Topic(
            topic_id=f"{subject_id}.{theme_number}",
            number=theme_number,
            name=title.title(),
            section=f"Paper {paper_number}",
            statement=statement,
        )

        concept_words = ", ".join(dict.fromkeys(concept_lines))
        for outcome_number, outcome_text in enumerate(outcomes, start=1):
            topic.learning_objectives.append(
                LearningObjective(
                    subject_id=subject.subject_id,
                    subject_name=subject.name,
                    topic_id=topic.topic_id,
                    topic_name=topic.name,
                    lo_id=f"{subject.subject_id}.{theme_number}.{outcome_number}",
                    number=f"{theme_number}.{outcome_number}",
                    title=outcome_text[:100],
                    statement=outcome_text,
                    include=(statement,) if statement else (),
                    exclude=(),
                    keywords=derive_keywords(topic.name, outcome_text, concept_words),
                    exam_skills=derive_exam_skills(outcome_text),
                    section=topic.section,
                    source=source,
                    page=page_number,
                )
            )
        subject.topics.append(topic)

    return subject


def _scan_theme_boundaries(pages: list[PageText]) -> list[tuple[str, int, str]]:
    """Find every "Paper N: ..." and Theme-title heading, in document order.

    Both are printed as ordinary single-column text outside the table, so a
    plain single-column extraction finds them reliably; only the table body
    itself needs column-aware extraction.
    """
    events: list[tuple[str, int, str]] = []
    started = False
    last_theme_title = None
    for page in pages:
        for line in page.lines:
            if not started:
                started = bool(START_HEADING.match(line))
                continue
            if END_HEADING.match(line):
                return events
            if match := PAPER.match(line):
                events.append(("paper", page.page, match.group(1)))
                continue
            if (
                line.isupper()
                and len(line) >= MIN_THEME_TITLE_LENGTH
                and line not in NOT_A_THEME
                and not line.isdigit()
            ):
                # A Theme's title is reprinted at the top of each of its
                # continuation pages; only the first occurrence is the start
                # of a new Theme, not a fresh one appearing every time.
                if line != last_theme_title:
                    events.append(("theme", page.page, line))
                    last_theme_title = line
    return events


def _paper_at(events: list[tuple[str, int, str]], page_number: int) -> str:
    current = "1"
    for kind, event_page, value in events:
        if event_page > page_number:
            break
        if kind == "paper":
            current = value
    return current


def _lines_by_page(column_pages: list[PageText]) -> dict[int, tuple[str, ...]]:
    return {page.page: page.lines for page in column_pages}


def _collect(by_page: dict[int, tuple[str, ...]], page_range: range) -> list[str]:
    lines: list[str] = []
    for page_number in page_range:
        for line in by_page.get(page_number, ()):
            stripped = line.strip()
            if stripped and stripped not in NOISE_LINES and not _looks_like_noise(stripped):
                lines.append(stripped)
    return lines


def _looks_like_noise(line: str) -> bool:
    """Filter out running headers and Theme/Paper titles that leak into a
    column between the end of one page's table and the "Overview / Making
    Connections" aside that starts the next -- neither is a table-header row
    (the only thing that pauses column capture), so their spans get swept
    into whichever column is nearest. No genuine Concepts/Content/Learning
    Outcomes bullet is ever written in pure upper case or as a bare number,
    so both are safe, targeted signals that a line does not belong here.
    """
    if line.isdigit():
        return True
    if line.startswith("(Students"):
        return True
    return len(line) > 8 and line.isupper()


def _merge_bullets(lines: list[str]) -> list[str]:
    """Fold wrapped continuation lines back into the bullet they belong to.

    A bullet that already ends in a full stop is treated as finished, so a
    stray line from the next Theme's own "Key Question" overview -- which can
    land in this column at the exact page where one Theme's table ends and
    the next begins, since it is never itself a bullet -- is dropped instead
    of silently tacked onto the end of an unrelated, already-complete outcome.
    """
    outcomes: list[str] = []
    for line in lines:
        if match := BULLET.match(line):
            outcomes.append(match.group(1).strip())
        elif outcomes and not outcomes[-1].endswith("."):
            outcomes[-1] = f"{outcomes[-1]} {line}".strip()
    return [outcome for outcome in outcomes if outcome]
