"""Parse ACT's College and Career Readiness Standards (English, Math, Reading, Science).

Each test's standards are coded by strand and score band: "N 504. Exhibit some
knowledge of the complex numbers" is Number and Quantity, and the hundreds digit
(5) is the 24-27 score range. Each standard becomes a learning objective
(N 504 in ACT Math is ACTM-1.504), under a topic for its strand and score range,
so an answer can say "Number and Quantity, ACT score 24-27".

The ACT publishes no exclusion lists: content outside every standard (calculus,
for example) comes back "not in the syllabus".
"""

from __future__ import annotations

import re
from pathlib import Path

from syllabus_core.syllabus.schema import LearningObjective, Subject, Topic, derive_exam_skills, derive_keywords

SOURCE = "ACT College and Career Readiness Standards"
BANDS = {2: "13–15", 3: "16–19", 4: "20–23", 5: "24–27", 6: "28–32", 7: "33–36"}

# (file, subject id, name, [(strand code, strand name), ...]) in the documents' order.
TESTS = [
    ("English.pdf", "ACTE", "English", [
        ("TOD", "Topic Development in Terms of Purpose and Focus"), ("ORG", "Organization, Unity, and Cohesion"),
        ("KLA", "Knowledge of Language"), ("SST", "Sentence Structure and Formation"),
        ("USG", "Usage Conventions"), ("PUN", "Punctuation Conventions")]),
    ("Math.pdf", "ACTM", "Math", [
        ("N", "Number and Quantity"), ("A", "Algebra"), ("F", "Functions"), ("AF", "Algebra and Functions"),
        ("G", "Geometry"), ("S", "Statistics and Probability")]),
    ("Reading.pdf", "ACTR", "Reading", [
        ("CLR", "Close Reading"), ("IDT", "Central Ideas, Themes, and Summaries"), ("REL", "Relationships"),
        ("WME", "Word Meanings and Word Choice"), ("TST", "Text Structure"), ("PPV", "Purpose and Point of View"),
        ("ARG", "Arguments"), ("SYN", "Multiple Texts")]),
    ("Science.pdf", "ACTS", "Science", [
        ("IOD", "Interpretation of Data"), ("SIN", "Scientific Investigation"),
        ("EMI", "Evaluation of Models, Inferences, and Experimental Results")]),
]

CODE = re.compile(r"(?<![A-Za-z])([A-Z]{1,3}) ([2-7]\d{2})\. ")
# Page furniture that can sit between a standard's lines in the text layer.
FURNITURE = re.compile(
    r"\s*(?:Topics in the flow to.*|SCORE|RANGE|\d{2}–\d{2}|ACT College & Career Readiness Standards|©.*|"
    r"MATHEMATICS|ENGLISH|READING|SCIENCE|[A-Z ,&]+ \([A-Z]{1,3}\)|Note:.*)\s*$")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace(" ", " ")).strip(" .")


def _standards(pdf: Path, strands: set[str]) -> dict[tuple[str, int], list[tuple[str, int, str]]]:
    """{(strand, band digit): [(strand, number, statement), ...]} from one test's PDF."""
    import pymupdf

    found: dict[tuple[str, int], list[tuple[str, int, str]]] = {}
    seen: set[tuple[str, int]] = set()
    for page_index, page in enumerate(pymupdf.open(str(pdf)), 1):
        # A text block holds one or more standards; reading block by block keeps
        # side-by-side columns (Algebra beside Functions) from interleaving.
        for block in page.get_text("blocks"):
            lines = [line for line in block[4].splitlines() if not FURNITURE.fullmatch(line)]
            text = " ".join(lines)
            starts = [m for m in CODE.finditer(text) if m.group(1) in strands]
            for i, match in enumerate(starts):
                end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
                strand, number = match.group(1), int(match.group(2))
                statement = _clean(text[match.end():end])
                if not statement or (strand, number) in seen:
                    continue
                seen.add((strand, number))
                found.setdefault((strand, number // 100), []).append((strand, number, statement, page_index))
    return found


def parse(folder: str | Path) -> list[Subject]:
    folder = Path(folder)
    subjects = []
    for filename, code, name, strands in TESTS:
        pdf = folder / filename
        if not pdf.exists():
            continue
        found = _standards(pdf, {s for s, _ in strands})
        subject = Subject(subject_id=code, name=name, code=code, level="ACT", source=SOURCE)
        # One objective per standard: a standard is ACT's own unit, and on its own
        # it embeds far more precisely than a bag of a whole score band ("Multiply
        # matrices" scores 0.93 against "multiplying matrices", the band 0.70).
        # Topics are strand and score range, so every card says the range.
        for t_index, (strand, strand_name) in enumerate(strands, 1):
            for band, scores in BANDS.items():
                items = sorted(found.get((strand, band), []), key=lambda s: s[1])
                if not items:
                    continue
                topic_name = f"{strand_name} (ACT score {scores})"
                topic = Topic(topic_id=f"{code}-{t_index}.{band}", number=f"{t_index}.{band}", name=topic_name)
                for s, n, text, page in items:
                    number = f"{t_index}.{n}"
                    topic.learning_objectives.append(LearningObjective(
                        subject_id=code, subject_name=name, topic_id=topic.topic_id, topic_name=topic_name,
                        lo_id=f"{code}-{number}", number=number, title=text, statement=text,
                        include=(f"{s} {n}: {text}",), exclude=(),
                        keywords=derive_keywords(strand_name, text), exam_skills=derive_exam_skills(text),
                        source=SOURCE, page=page))
                subject.topics.append(topic)
        subjects.append(subject)
    return subjects
