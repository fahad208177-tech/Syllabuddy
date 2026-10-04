"""Parser for Geography's "Key Question / Content" table format.

Used by Geography 8834 (H1) and 9173 (H2). Like History (see
``history_table.py``), the syllabus content is a genuine side-by-side table
rather than a single flowing column:

    Topic 1.1 Environment and Resources
    ...intro paragraphs...
    Key Question                          Content
    Students will understand:
    1. Understanding Sustainable Development
    What is sustainable                   * The concept of sustainable
    development?                          development, as defined in ...

A naive single-column read interleaves the two columns word-by-word into
nonsense wherever they share a vertical position; ``extract_table_columns``
is what repairs this.

Unlike History, there is no separate "Learning Outcomes" column -- the
Content column bullets are themselves the examinable material. Each numbered
heading in the Key Question column (e.g. "1. Understanding Sustainable
Development") becomes one objective, combining that heading with the
"Key Question" sentences under it; the whole Topic's Content-column bullets
are attached as shared supporting context, the same role "Content" plays for
the sciences' lettered-outcomes format. Splitting Content bullets more
finely, one group per numbered heading, was tried and abandoned: nothing in
the rendered text says which bullet belongs under which heading once the two
columns have been read back out independently, and guessing would risk
attaching the wrong content to the wrong objective -- worse than the coarser
but certainly-correct grouping used here.
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
END_HEADING = re.compile(r"^(CLUSTER 4|APPENDI(X|CES))\b")

CLUSTER = re.compile(r"^CLUSTER \d+:\s*(.+)$")
TOPIC_HEADING = re.compile(r"^Topic (\d+\.\d+)\s+(.+)$")
NUMBERED_HEADING = re.compile(r"^(\d+)\.\s+(.+)$")

COLUMN_LABELS = ("Key Question", "Content")

NOISE_LINES = {"(continued)"}
REPEATED_HEADER = re.compile(r"^Key Questions?\s+Content$")
REPEATED_HEADER_SUBSTRING = re.compile(r"Key Questions?\s+Content")
BARE_BULLET = re.compile(r"^[•●▪▪\-–—−\s]+$")


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
    """Build a :class:`Subject` from a Geography-format syllabus PDF.

    Like :func:`history_table.parse`, this needs the original PDF path
    (passed by the registry) to re-read the raw page layout and split it into
    columns, rather than the pre-extracted single-column pages every other
    parser works from.
    """
    if path is None:
        raise ValueError("geography_table.parse requires the source PDF path")

    subject = Subject(
        subject_id=subject_id, name=subject_name, code=code, level=level, source=source
    )

    topics_found = _scan_topic_boundaries(pages)
    if not topics_found:
        return subject

    columns = extract_table_columns(path, COLUMN_LABELS)
    question_by_page = _lines_by_page(columns["Key Question"])
    content_by_page = _lines_by_page(columns["Content"])

    for position, (cluster, number, name, page_number) in enumerate(topics_found):
        end_page = topics_found[position + 1][3] if position + 1 < len(topics_found) else 10**6
        page_range = range(page_number, end_page)

        question_lines = _collect(question_by_page, page_range)
        content_lines = _collect(content_by_page, page_range)
        segments = _split_into_segments(question_lines)
        if not segments:
            continue

        statement = "; ".join(content_lines)
        topic = Topic(
            topic_id=f"{subject_id}.{number}",
            number=number,
            name=name,
            section=cluster,
            statement=statement,
        )

        for outcome_number, (heading, detail) in enumerate(segments, start=1):
            objective_statement = f"{heading}. {detail}" if detail else f"{heading}."
            topic.learning_objectives.append(
                LearningObjective(
                    subject_id=subject.subject_id,
                    subject_name=subject.name,
                    topic_id=topic.topic_id,
                    topic_name=topic.name,
                    lo_id=f"{subject.subject_id}.{number}.{outcome_number}",
                    number=f"{number}.{outcome_number}",
                    title=heading[:100],
                    statement=objective_statement,
                    include=(statement,) if statement else (),
                    exclude=(),
                    keywords=derive_keywords(topic.name, heading, detail),
                    exam_skills=derive_exam_skills(heading, detail),
                    section=topic.section,
                    source=source,
                    page=page_number,
                )
            )
        subject.topics.append(topic)

    return subject


def _scan_topic_boundaries(pages: list[PageText]) -> list[tuple[str, str, str, int]]:
    """Find every "CLUSTER N: ..." and "Topic X.Y Name" heading.

    Both are printed as ordinary single-column text outside the table, so a
    plain single-column extraction finds them reliably; only the table body
    itself needs column-aware extraction.
    """
    topics: list[tuple[str, str, str, int]] = []
    started = False
    cluster = ""
    for page in pages:
        for line in page.lines:
            if not started:
                started = bool(START_HEADING.match(line))
                continue
            if END_HEADING.match(line):
                return topics
            if match := CLUSTER.match(line):
                cluster = match.group(1).strip()
                continue
            if match := TOPIC_HEADING.match(line):
                topics.append((cluster, match.group(1), match.group(2).strip(), page.page))
    return topics


def _lines_by_page(column_pages: list[PageText]) -> dict[int, tuple[str, ...]]:
    return {page.page: page.lines for page in column_pages}


def _collect(by_page: dict[int, tuple[str, ...]], page_range: range) -> list[str]:
    lines: list[str] = []
    for page_number in page_range:
        for line in by_page.get(page_number, ()):
            stripped = _clean_line(line.strip())
            if stripped and stripped not in NOISE_LINES and not _looks_like_noise(stripped):
                lines.append(stripped)
    return lines


# A stray "Content" bullet glyph, one column's row narrowly misjudged as
# nearer to the other, occasionally lands mid-line rather than as a row of
# its own (see ``_looks_like_noise``, which only catches the latter).
STRAY_BULLET = re.compile(r"\s*[•●▪]\s*")


def _clean_line(line: str) -> str:
    line = REPEATED_HEADER_SUBSTRING.sub("", line)
    line = STRAY_BULLET.sub(" ", line)
    return line.strip()


def _looks_like_noise(line: str) -> bool:
    """Filter running headers, Topic/Cluster titles, repeated table headers
    and lone bullet glyphs that leak into a column: the first three for the
    same reason as ``history_table._looks_like_noise``, and the bullet glyphs
    because a "Content" bullet marker occasionally renders as its own row,
    close enough to the "Key Question" column's x-position to be assigned
    there instead -- harmless noise once stripped, since the bullet carries
    no text of its own to lose."""
    if line.isdigit():
        return True
    if line.startswith("Students will understand"):
        return True
    if REPEATED_HEADER.match(line) or BARE_BULLET.match(line):
        return True
    return len(line) > 8 and line.isupper()


def _split_into_segments(lines: list[str]) -> list[tuple[str, str]]:
    """Split the Key Question column into ``(numbered heading, detail)`` pairs.

    Everything from one "N. Heading" line up to the next belongs to that
    heading, joined into one detail string.
    """
    segments: list[tuple[str, list[str]]] = []
    for line in lines:
        if match := NUMBERED_HEADING.match(line):
            segments.append((match.group(2).strip(), []))
        elif segments:
            segments[-1][1].append(line)
    return [(heading, " ".join(detail)) for heading, detail in segments]
