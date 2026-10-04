"""Layout-aware PDF text extraction.

The A-Level syllabus PDFs are exported from Word, so three things go wrong with a
naive ``extract_text()`` call:

1. The content stream stores glyphs in authoring order, not reading order, so
   equations come out scrambled (``H0`` arrives as ``( ) 0 H``).
2. Each equation glyph can land in its own layout block, so grouping by the
   PDF's own line structure keeps them apart. We therefore ignore the reported
   blocks and re-cluster every span on the page into visual rows by position.
3. Superscripts and subscripts are ordinary text runs at a smaller font size,
   offset vertically. Without reconstruction ``ax^2`` flattens to ``ax2``, which
   is actively wrong for a maths tutor.

This module handles all three, and returns line-level structure because the
syllabus parsers key off the layout (numbered sub-topics, ``Include:``/
``Exclude:`` blocks) rather than off a flat blob of text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Sequence

import pymupdf

# A span must be this much smaller than the row's body text before we treat it
# as a script rather than as ordinary prose.
SCRIPT_SIZE_RATIO = 0.78

# How far above the body baseline a small span must sit to count as a superscript,
# as a fraction of the body font size. Below this it is read as a subscript.
SUPERSCRIPT_LIFT_RATIO = 0.12

# Scripts are things like "2", "n+1", "max". Anything longer is a font change in
# running prose, not an exponent, so we leave it alone.
MAX_SCRIPT_LENGTH = 4

# Two spans belong to the same visual row when their vertical midpoints sit
# within this multiple of the row's body font size. Midpoints separate rows far
# more reliably than bounding-box overlap: glyph boxes of adjacent rows overlap
# by a few points, and a single tall glyph is enough to chain rows together.
# Loose enough to keep a subscript with its base, tight enough to keep
# consecutive table rows apart.
ROW_MIDPOINT_RATIO = 0.55

# Horizontal gap, in multiples of the body font size, that reads as a column
# break rather than a word space.
COLUMN_GAP_RATIO = 1.5

SCRIPT_BODY = re.compile(r"^[A-Za-z0-9+\-−,()]+$")


@dataclass(frozen=True)
class PageText:
    """One extracted page, kept as lines so parsers can see the layout."""

    source: str
    page: int
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def extract_pages(path: str | Path) -> list[PageText]:
    """Extract every page of a PDF with reading order and scripts repaired."""
    pdf_path = Path(path)
    pages: list[PageText] = []

    with pymupdf.open(str(pdf_path)) as document:
        for page_number, page in enumerate(document, start=1):
            spans = _page_spans(page)
            lines = [
                rendered
                for row in _cluster_rows(spans)
                if (rendered := _render_row(row))
            ]
            pages.append(
                PageText(source=pdf_path.name, page=page_number, lines=tuple(lines))
            )

    return pages


def _page_spans(page: pymupdf.Page) -> list[dict]:
    """Every text span on the page, flattened out of the block/line hierarchy."""
    layout = page.get_text("dict")
    spans: list[dict] = []
    for block in layout.get("blocks", []):
        # Image blocks carry no "lines" key.
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    spans.append(span)
    return spans


def _cluster_rows(spans: list[dict]) -> list[list[dict]]:
    """Group spans into visual rows, then order each row left to right.

    This is what repairs scrambled equations: position on the page decides
    reading order, not the order the glyphs happen to appear in the file.
    """
    if not spans:
        return []

    rows: list[list[dict]] = []
    # Each row is anchored on its tallest span, so a small superscript joins the
    # row without dragging the anchor away from the body text.
    anchor_middle = 0.0
    anchor_size = 0.0

    for span in sorted(spans, key=_middle):
        middle = _middle(span)
        tolerance = max(anchor_size, span["size"]) * ROW_MIDPOINT_RATIO

        if rows and abs(middle - anchor_middle) <= tolerance:
            rows[-1].append(span)
            if span["size"] > anchor_size:
                anchor_middle, anchor_size = middle, span["size"]
        else:
            rows.append([span])
            anchor_middle, anchor_size = middle, span["size"]

    return [sorted(row, key=lambda s: s["bbox"][0]) for row in rows]


def _middle(span: dict) -> float:
    return (span["bbox"][1] + span["bbox"][3]) / 2


def _render_row(row: list[dict]) -> str:
    """Turn one visual row into text, restoring super/subscripts."""
    body_size = _body_size(row)
    body_bottom = _body_bottom(row, body_size)

    # (marker, text) pairs; marker is None for ordinary prose.
    tokens: list[tuple[str | None, str]] = []
    previous_right: float | None = None

    for span in row:
        text = span["text"]
        marker = _script_marker(span, body_size, body_bottom)
        gap = span["bbox"][0] - previous_right if previous_right is not None else 0.0

        if marker is None:
            # Restore the word space that sorting by position discards.
            if tokens and gap > 0.5 and not tokens[-1][1].endswith(" ") and not text.startswith(" "):
                tokens.append((None, "  " if gap > body_size * COLUMN_GAP_RATIO else " "))
            tokens.append((None, text))
        elif tokens and tokens[-1][0] == marker and gap < body_size:
            # "n", "+", "1" arrive as three spans; keep them one subscript.
            tokens[-1] = (marker, tokens[-1][1] + text.strip())
        else:
            # A script binds tightly to what precedes it, so never space it out.
            if tokens and tokens[-1][0] is None and tokens[-1][1].endswith(" "):
                tokens[-1] = (None, tokens[-1][1].rstrip())
            tokens.append((marker, text.strip()))

        previous_right = span["bbox"][2]

    return _collapse_spaces("".join(_format_token(m, t) for m, t in tokens))


def _format_token(marker: str | None, text: str) -> str:
    if marker is None:
        return text
    # Wrap anything longer than one character so "x^{n+1}" stays readable.
    body = text if len(text) == 1 else f"{{{text}}}"
    return f"{marker}{body}"


def _body_size(spans: list[dict]) -> float:
    """The font size of the row's main text.

    Taken as the largest size present, so a row of 10pt prose with one 6.5pt
    exponent reports 10pt, while a row that is entirely small print reports its
    own size and is not mistaken for a row of subscripts.
    """
    return max((span["size"] for span in spans), default=0.0)


def _body_bottom(spans: list[dict], body_size: float) -> float:
    """Baseline of the row's body text, used as the vertical reference."""
    bottoms = [span["bbox"][3] for span in spans if span["size"] >= body_size * 0.9]
    if not bottoms:
        bottoms = [span["bbox"][3] for span in spans]
    return median(bottoms)


def _script_marker(span: dict, body_size: float, body_bottom: float) -> str | None:
    """Return ``^``/``_`` if this span is a script, else ``None``."""
    text = span["text"].strip()
    if not text or len(text) > MAX_SCRIPT_LENGTH or not SCRIPT_BODY.match(text):
        return None
    if body_size <= 0 or span["size"] >= body_size * SCRIPT_SIZE_RATIO:
        return None

    lift = body_bottom - span["bbox"][3]
    return "^" if lift > body_size * SUPERSCRIPT_LIFT_RATIO else "_"


def _collapse_spaces(text: str) -> str:
    # Collapse runs of whitespace but keep the double space that marks a column
    # break, since the syllabus parsers use it to split table cells.
    text = re.sub(r"[\t ]+", " ", text)
    text = re.sub(r" {3,}", "  ", text)
    return text.strip()


def extract_pages_excluding(path: str | Path, min_x0: float) -> list[PageText]:
    """Extract pages exactly as :func:`extract_pages` does, but drop every
    span whose left edge is at or past ``min_x0`` before clustering.

    Some syllabuses (Economics) print a narrow "Additional information"
    column of supplementary exam notes beside the examinable content, with
    no header row clean enough for :func:`extract_table_columns` to anchor
    two columns on (its column header shares a row with the *first* content
    item rather than heading the table on a row of its own). That column is
    peripheral commentary, not examinable content in its own right, so
    dropping it before row-clustering keeps the primary column's reading
    order and wrapped-line handling exactly as ``extract_pages`` produces it,
    rather than trying to recover a second column nobody needs.
    """
    pdf_path = Path(path)
    pages: list[PageText] = []

    with pymupdf.open(str(pdf_path)) as document:
        for page_number, page in enumerate(document, start=1):
            spans = [span for span in _page_spans(page) if span["bbox"][0] < min_x0]
            lines = [
                rendered
                for row in _cluster_rows(spans)
                if (rendered := _render_row(row))
            ]
            pages.append(
                PageText(source=pdf_path.name, page=page_number, lines=tuple(lines))
            )

    return pages


def extract_page_texts(path: str | Path) -> list[str]:
    """Convenience helper: flat text per page."""
    return [page.text for page in extract_pages(path)]


# A lone dash or bullet glyph, which every column in these tables starts each
# of its own lines with -- reliable evidence of where a column's true left
# edge sits, which the header label's position is not: a short word like
# "Content" is often printed roughly centred over a much wider column, well
# to the right of where that column's own bullets actually start.
_BULLET_GLYPHS = frozenset("•●▪-–—−")


def extract_table_columns(
    path: str | Path,
    column_labels: Sequence[str],
    reset_labels: Sequence[Sequence[str]] = (),
) -> dict[str, list[PageText]]:
    """Extract a document laid out as a multi-column table, one stream of
    :class:`PageText` per column.

    Some Humanities syllabuses (History, Geography) print their content as a
    true side-by-side table -- e.g. History's "Concepts | Content | Learning
    Outcomes" -- rather than the single flowing column the sciences use.
    ``extract_pages``'s row clustering assumes one column and so interleaves
    the columns word-by-word into nonsense wherever their text happens to
    share a vertical position.

    This instead looks for a row containing ``column_labels`` as separate
    spans, left to right (e.g. ``("Concepts", "Content", "Learning
    Outcomes")``). Everything between one such header and the next
    (``reset_labels`` match, another ``column_labels`` match, or the end of
    the document) is one "block"; within a block, every bullet glyph's
    x-position (see ``_BULLET_GLYPHS``) is clustered against the header
    positions with a few rounds of 1-D k-means (:func:`_refine_column_centers`)
    to find where each column's text actually starts -- which the header
    label's own position is not a reliable guide to, since a short word like
    "Content" is often printed roughly centred over a much wider column, well
    to the right of where that column's own bullets start. Every span in the
    block, bulleted or not, is then assigned to its nearest refined centre.
    Each column's spans are finally re-clustered into rows with
    :func:`_cluster_rows` and :func:`_render_row`, exactly as the
    single-column path does, so wrapped lines, reading order and scripts are
    restored the same way.

    A table like this typically repeats its header once per topic rather
    than once per page, and is preceded and followed by ordinary prose (an
    overview paragraph, a "making connections" aside) that is laid out with
    its own, different columns. Passing that aside's own header labels as one
    of ``reset_labels`` ends the current block from the point it is seen
    until ``column_labels`` is next found, so that unrelated prose is not
    folded into the table's columns; text before the first ``column_labels``
    match is never collected at all. A ``reset_labels`` match found before
    any ``column_labels`` match is a no-op.
    """
    labels = list(column_labels)
    resets = [list(pattern) for pattern in reset_labels]
    blocks: list[tuple[dict[str, float], list[tuple[int, list[dict]]]]] = []
    block_rows: list[tuple[int, list[dict]]] = []
    block_anchors: dict[str, float] | None = None

    def flush_block() -> None:
        nonlocal block_rows
        if block_anchors is not None and block_rows:
            blocks.append((block_anchors, block_rows))
        block_rows = []

    with pymupdf.open(str(Path(path))) as document:
        for page_number, page in enumerate(document, start=1):
            for row in _cluster_rows(_page_spans(page)):
                matched = _match_row_labels(row, labels)
                if matched is not None:
                    flush_block()
                    block_anchors = {label: span["bbox"][0] for label, span in zip(labels, matched)}
                    continue

                if any(_match_row_labels(row, pattern) is not None for pattern in resets):
                    flush_block()
                    block_anchors = None
                    continue

                if block_anchors is None:
                    continue

                block_rows.append((page_number, row))
        flush_block()

    buckets: dict[str, list[tuple[int, dict]]] = {label: [] for label in labels}
    for seed_anchors, rows in blocks:
        centers = _refine_column_centers(labels, seed_anchors, rows)
        for page_number, row in rows:
            for span in row:
                nearest = min(labels, key=lambda label: abs(span["bbox"][0] - centers[label]))
                buckets[nearest].append((page_number, span))

    result: dict[str, list[PageText]] = {}
    for label in labels:
        by_page: dict[int, list[dict]] = {}
        for page_number, span in buckets[label]:
            by_page.setdefault(page_number, []).append(span)
        result[label] = [
            PageText(
                source=Path(path).name,
                page=page_number,
                lines=tuple(
                    rendered
                    for row in _cluster_rows(page_spans)
                    if (rendered := _render_row(row))
                ),
            )
            for page_number, page_spans in sorted(by_page.items())
        ]

    return result


def _refine_column_centers(
    labels: list[str],
    seed_anchors: dict[str, float],
    rows: list[tuple[int, list[dict]]],
) -> dict[str, float]:
    """Re-estimate each column's x-position from where its bullets actually are.

    Nearest-seed assignment is not enough on its own: seeded with the header
    labels' positions, a column whose header sits well to the right of its
    own bullets (see :func:`extract_table_columns`) misclassifies that
    column's bullets into its left neighbour, and iterative recentring
    (plain k-means) does not reliably fix it either -- a column with many
    more bullets than its neighbour dominates the pooled mean, so the
    minority of misclassified points is not enough to pull the centre far
    enough to reassign correctly.

    What is reliable here is that the columns are far apart relative to how
    close together bullets are *within* one column: sorting every distinct
    bullet x-position and looking for the largest gaps finds the true column
    boundaries directly, regardless of how many bullets land in each one.
    """
    ordered_labels = sorted(labels, key=lambda label: seed_anchors[label])
    positions = sorted({round(span["bbox"][0], 1) for _, row in rows for span in row
                         if span["text"].strip() in _BULLET_GLYPHS})

    if len(positions) < len(ordered_labels):
        # Too few distinct bullet positions to trust a from-scratch split;
        # the header positions are the best information available.
        return dict(seed_anchors)

    gaps = sorted(
        range(len(positions) - 1),
        key=lambda i: positions[i + 1] - positions[i],
        reverse=True,
    )[: len(ordered_labels) - 1]

    groups: list[list[float]] = []
    start = 0
    for split in sorted(gaps):
        groups.append(positions[start : split + 1])
        start = split + 1
    groups.append(positions[start:])

    return {
        label: sum(group) / len(group)
        for label, group in zip(ordered_labels, groups)
    }


def _match_row_labels(row: list[dict], labels: list[str]) -> list[dict] | None:
    """If ``row`` contains every label in order, return the matching spans.

    Matching is exact on stripped text, so a label like ``"Content"`` only
    fires on a genuine column heading, never on a body line that happens to
    contain the word.
    """
    matches: list[dict] = []
    position = 0
    for label in labels:
        found = None
        for index in range(position, len(row)):
            if row[index]["text"].strip() == label:
                found = index
                break
        if found is None:
            return None
        matches.append(row[found])
        position = found + 1
    return matches


# A line repeated on at least this fraction of pages is furniture, not content.
FURNITURE_FREQUENCY = 0.5

BARE_PAGE_NUMBER = re.compile(r"^\d{1,4}$")


def strip_furniture(pages: list[PageText]) -> list[PageText]:
    """Drop running headers, footers and bare page numbers.

    Every syllabus page repeats a banner such as
    ``9758 MATHEMATICS GCE ADVANCED LEVEL H2 SYLLABUS``. Left in, it dominates
    the embedding of every chunk and makes them all look alike to the retriever.
    """
    if len(pages) < 3:
        return pages

    counts: dict[str, int] = {}
    for page in pages:
        for line in set(page.lines):
            counts[line] = counts.get(line, 0) + 1

    threshold = len(pages) * FURNITURE_FREQUENCY
    furniture = {line for line, count in counts.items() if count >= threshold}

    return [
        PageText(
            source=page.source,
            page=page.page,
            lines=tuple(
                line
                for line in page.lines
                if line not in furniture and not BARE_PAGE_NUMBER.match(line)
            ),
        )
        for page in pages
    ]
