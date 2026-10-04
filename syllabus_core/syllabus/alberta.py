"""Parse an Alberta Education Program of Studies (science 20-30) into the shared schema.

Only the 30-level course is read: that is what the Alberta Diploma Examination
assesses. The program is organised as

* units ("Unit A: Momentum and Impulse"),
* general outcomes ("General Outcome 1 / Students will explain how momentum is
  conserved..."), which become learning objectives, and
* specific outcomes for knowledge, coded like ``30–A1.3k``, which are what the
  objective requires.

Skills ("s") and science-technology-society ("sts") outcomes describe how the
course is taught rather than examinable content, so they are not included.
"""

from __future__ import annotations

import re
from pathlib import Path

from syllabus_core.syllabus.schema import LearningObjective, Subject, Topic, derive_exam_skills, derive_keywords

UNIT = re.compile(r"^Unit\s+([A-D]):\s+(.+)$", re.M)
GENERAL = re.compile(r"General Outcome\s+(\d+)\s*\n\s*(Students will .+?)(?:\n\s*\n|\Z)", re.S)
KNOWLEDGE = re.compile(r"^30[–-]([A-D]\d)\.(\d+)k\s*\n(.*?)(?=^\s*30[–-][A-D]\d\.\d+[a-z]+\s*$|^\s*Specific Outcomes|^\s*Note:|\Z)",
                       re.M | re.S)


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text.replace("’", "'"))
    return text.strip(" .")


def parse(pdf_path: str | Path, *, course: str, code: str, name: str, source: str) -> Subject:
    import pymupdf

    doc = pymupdf.open(str(pdf_path))
    subject = Subject(subject_id=code, name=name, code=code, level="Alberta Diploma", source=source)
    units: dict[str, Topic] = {}
    outcomes: dict[str, dict] = {}

    for index, page in enumerate(doc):
        text = page.get_text()
        course_re = re.escape(course)
        if not re.search(rf"\b{course_re}\s*/\s*\d+|\d+\s*/\s*{course_re}\b", text):
            continue  # only 30-level pages: the running header is "Physics 30 /43" or "46/ Chemistry 30"
        unit_match = UNIT.search(text)
        if not unit_match:
            continue
        letter, unit_name = unit_match.group(1), _clean(unit_match.group(2))
        unit = units.setdefault(letter, Topic(topic_id=f"{code}-{letter}", number=letter, name=f"Unit {letter}: {unit_name}"))

        general = {m.group(1): _clean(m.group(2)) for m in GENERAL.finditer(text)}
        for m in KNOWLEDGE.finditer(text):
            key, item = m.group(1), _clean(m.group(3))
            entry = outcomes.setdefault(key, {"unit": unit, "general": "", "items": [], "page": index + 1})
            number = key[1:]
            if number in general and not entry["general"]:
                entry["general"] = general[number]
            if item and item not in entry["items"]:
                entry["items"].append(item)
        for number, statement in general.items():
            key = f"{letter}{number}"
            entry = outcomes.setdefault(key, {"unit": unit, "general": statement, "items": [], "page": index + 1})
            entry["general"] = entry["general"] or statement

    for key in sorted(outcomes):
        entry = outcomes[key]
        if not entry["items"]:
            continue
        statement = entry["general"] or entry["items"][0]
        title = re.sub(r"^Students will\s+", "", statement)
        title = title[0].upper() + title[1:]
        unit = entry["unit"]
        unit.learning_objectives.append(LearningObjective(
            subject_id=code, subject_name=name, topic_id=unit.topic_id, topic_name=unit.name,
            lo_id=f"{code}-{key}", number=key, title=title, statement=statement,
            include=tuple(entry["items"]), exclude=(),
            keywords=derive_keywords(title, *entry["items"]), exam_skills=derive_exam_skills(*entry["items"]),
            source=source, page=entry["page"]))
    subject.topics = [units[k] for k in sorted(units)]
    return subject
