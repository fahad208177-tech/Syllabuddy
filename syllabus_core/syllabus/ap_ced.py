"""Parse a College Board AP Course and Exam Description (CED) into the shared schema.

Every AP CED's course framework uses the same page layout, so one parser
covers them all:

* a "TOPIC 1.2 <title>" header starts each topic, under a running unit name
  at the top of the page;
* LEARNING OBJECTIVE codes (``LIM-1.A``) and ESSENTIAL KNOWLEDGE codes
  (``LIM-1.A.1``) each head a column, with EXCLUSION STATEMENT boxes among them;
* "bc only" marks content assessed on AP Calculus BC but not AB.

Plain text extraction interleaves the columns (an exclusion box lands in the
middle of an essential-knowledge item), so blocks are read by position. Facing
pages are mirrored, so each page's columns are located from its own headings,
falling back to the last page on the same side when a continuation page has
none.

Mapping onto the schema: an AP *unit* becomes a Topic, an AP *topic* becomes a
LearningObjective (its learning objectives and essential knowledge are what
the syllabus "requires"), and exclusion statements are its "exclude" list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from syllabus_core.syllabus.schema import LearningObjective, Subject, Topic, derive_exam_skills, derive_keywords

# Three generations of code: "LIM-1.A" / "LIM-1.A.1" (Calculus, economics...),
# "1.1.A" / "1.1.A.1" (the newer sciences, CS A, statistics, psychology), and the
# history courses' "Unit 4: Learning Objective H" with "KC-4.1.IV.C" developments.
LO_CODE = re.compile(r"^(?:LO\s+)?((?:[A-Z]{2,5}-\d+|\d+\.\d+)\.[A-Z])(?![.\w])")
EK_CODE = re.compile(r"^(?:EK\s+)?((?:[A-Z]{2,5}-\d+|\d+\.\d+)\.[A-Z]\.\d+|KC-\d+\.\d+\.[IVX]+(?:\.[A-Z])?)(?![.\w])")
# Courses with no TOPIC headers (CS Principles) are organised by enduring understanding.
EU_HEAD = re.compile(r"^(?:ENDURING UNDERSTANDING\s+)?([A-Z]{2,5}-\d+)[ \t]*\n(.+)", re.S)
BIG_IDEA = re.compile(r"BIG\s+IDEA\s+(\d+)")
HISTORY_LO = re.compile(r"^Unit\s+(\d+):\s+Learning\s+Objective\s+([A-Z])\b")
SKILL_TAG = re.compile(r"\[Skills?\s[^\]]*\]")
TOPIC_HEAD = re.compile(r"^TOPIC\s+(\d+\.\d+)\s*(.*)", re.S)
BC_ONLY = re.compile(r"\s*\bbc\s+only\b\s*", re.I)  # the PDF uses a non-breaking space
EK_HEADINGS = ("ESSENTIAL KNOWLEDGE", "HISTORICAL DEVELOPMENTS")
STOP_HEADINGS = ("ENDURING UNDERSTANDING", "LEARNING OBJECTIVE", "SUGGESTED SKILLS", "THEMATIC FOCUS",
                 "AVAILABLE RESOURCES", "Required Course Content", "Return to contents", "RetuRn to contents",
                 "return to Contents", "KEY CONCEPT", "ILLUSTRATIVE EXAMPLES") + EK_HEADINGS
SKILL_NOTE = "This topic is intended to focus"


@dataclass
class _Item:
    code: str
    text: str = ""
    bc_only: bool = False


@dataclass
class _ApTopic:
    number: str
    title: str
    unit_number: str
    unit_name: str
    page: int
    objectives: list[_Item] = field(default_factory=list)
    knowledge: list[_Item] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    note: str = ""
    bc_only_title: bool = False


def _clean(text: str) -> str:
    text = text.replace(" ", " ").replace(" ", " ").replace("\x07", " ")
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)   # words hyphenated across lines
    text = re.sub(r"\s+", " ", text)
    # Kerning splits "Dif ferentiation" / "ef fect", but "of functions" is two real words.
    text = re.sub(r"\b(\w+f) (f\w+)",
                  lambda m: m.group(0) if m.group(1).lower() in {"of", "if", "off", "self", "elf"} else m.group(1) + m.group(2),
                  text)
    return text.strip()


def _is_prose(text: str) -> bool:
    """Formula fragments come out as scattered symbols; keep only real sentences."""
    letters = sum(ch.isalpha() for ch in text)
    return letters >= 12 and letters / max(len(text), 1) > 0.55


def parse_ced(pdf_path: str | Path) -> list[_ApTopic]:
    import pymupdf

    doc = pymupdf.open(str(pdf_path))
    topics: dict[str, _ApTopic] = {}
    current: _ApTopic | None = None
    unit_names: dict[str, str] = {}
    layout_by_side: dict[int, tuple[float, float, float | None, bool]] = {}
    texts = [_spaces(page.get_text()) for page in doc]
    # A stray "TOPIC 3.11" in an exam section must not switch the whole course to topic mode.
    by_topic_header = sum(bool(re.search(r"^TOPIC\s+\d+\.\d+", t, re.M)) for t in texts if "Course Framework" in t) >= 5

    for index, page in enumerate(doc):
        raw = texts[index]
        if "Course Framework" not in raw or "long-term takeaways" in raw:
            continue  # only the framework pages; skip the "how to read this page" sample
        blocks = [(b[0], b[1], _spaces(b[4])) for b in page.get_text("blocks") if b[4].strip()]

        layout = _layout(blocks) or layout_by_side.get(index % 2)
        if layout:
            layout_by_side[index % 2] = layout

        page_unit = next((_clean(t) for x, y, t in blocks
                          if y < 70 and "UNIT" not in t and "BIG" not in t and "Course Framework" not in t
                          and _is_prose(t)), "")
        big_idea = BIG_IDEA.search(raw)
        for x, y, text in sorted(blocks, key=lambda b: (b[1], b[0])):
            if by_topic_header:
                match = TOPIC_HEAD.match(text.strip())
                if not match:
                    continue
                number, title = match.group(1), match.group(2)
                unit = number.split(".")[0]
            else:
                match = EU_HEAD.match(text.strip())
                if not match:
                    continue
                number, title = match.group(1), _short_title(match.group(2))
                unit = big_idea.group(1) if big_idea else "1"
            if page_unit:
                unit_names.setdefault(unit, page_unit)
            current = topics.get(number)
            if current is None:
                current = topics[number] = _ApTopic(number, _clean(BC_ONLY.sub(" ", title)), unit, "", index + 1)
            current.bc_only_title = current.bc_only_title or bool(BC_ONLY.search(title))
        if current is None or layout is None:
            continue

        lo_x, ek_x, skills_x, skills_right = layout

        def in_skills(x: float) -> bool:
            if skills_x is None:
                return False
            return x >= skills_x - 5 if skills_right else x < lo_x - 12

        content = [(x, y, t) for x, y, t in blocks if not in_skills(x) and 70 < y < 750]
        for x, y, text in content:
            if text.strip().startswith(SKILL_NOTE) and not current.note:
                current.note = _clean(text)
        _read_column([(y, t) for x, y, t in content if lo_x - 12 <= x < ek_x - 12], current)
        _read_column([(y, t) for x, y, t in content if x >= ek_x - 12], current)

    for topic in topics.values():
        name = re.sub(r"^\d+\s+", "", unit_names.get(topic.unit_number, ""))
        topic.unit_name = name or f"Unit {topic.unit_number}"
    if not by_topic_header:
        glance = _glance_map(texts)
        if glance:
            topics = _regroup(topics, glance)
    return sorted(topics.values(), key=lambda t: [int(p) if p.isdigit() else p for p in re.split(r"[.\-]", t.number)])


GLANCE_CODES = re.compile(r"^(?:[A-Z]{2,5}-\d+\.[A-Z],?\s*)+$")
GLANCE_TOPIC = re.compile(r"^(\d+\.\d+)\s+(.*)$")
GLANCE_SKILL = re.compile(r"^\d\.[A-Z]\s")


def _glance_map(texts: list[str]) -> dict[str, tuple[str, str]]:
    """Learning objective code -> (topic number, topic title) from the "at a glance" tables."""
    mapping: dict[str, tuple[str, str]] = {}
    from collections import Counter

    # Word frequencies from the body text only: the glance tables are where the
    # letter-spacing damage is, so their fragments must not count as words.
    counts = Counter(w.lower() for t in texts if "AT A GLANCE" not in t for w in re.findall(r"[A-Za-z]+", t))

    def respace(title: str) -> str:
        # Letter-spacing splits words ("Binary Sear ch", "Da ta"): rejoin two fragments
        # when the joined word is at least as common in the document as either piece.
        out: list[str] = []
        for word in _clean(title).split(" "):
            if out and word.isalpha() and out[-1].isalpha():
                left, right = out[-1].lower(), word.lower()
                joined = left + right
                fragment = min(len(left), len(right)) == 1 or not counts[left] or not counts[right]
                if counts[joined] and (fragment or counts[joined] >= max(counts[left], counts[right])):
                    out[-1] += word
                    continue
            out.append(word)
        return " ".join(out)

    for text in texts:
        if "AT A GLANCE" not in text:
            continue
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        codes: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if GLANCE_CODES.match(line):
                codes += re.findall(r"[A-Z]{2,5}-\d+\.[A-Z]", line)
            elif codes and GLANCE_TOPIC.match(line):
                number, title = GLANCE_TOPIC.match(line).groups()
                while i + 1 < len(lines) and not GLANCE_SKILL.match(lines[i + 1]) \
                        and not GLANCE_CODES.match(lines[i + 1]) and not GLANCE_TOPIC.match(lines[i + 1]):
                    i += 1
                    title += " " + lines[i]
                for code in codes:
                    mapping.setdefault(code, (number, respace(title)))
                codes = []
            i += 1
    return mapping


def _regroup(by_eu: dict[str, _ApTopic], glance: dict[str, tuple[str, str]]) -> dict[str, _ApTopic]:
    """Move learning objectives (and their knowledge and exclusions) from
    enduring-understanding groups into the course's real topics."""
    topics: dict[str, _ApTopic] = {}
    for eu in by_eu.values():
        placed: dict[str, _ApTopic] = {}
        for objective in eu.objectives:
            if objective.code not in glance:
                continue
            number, title = glance[objective.code]
            topic = topics.setdefault(number, _ApTopic(number, title, number.split(".")[0], eu.unit_name, eu.page))
            topic.objectives.append(objective)
            topic.knowledge += [k for k in eu.knowledge if k.code.startswith(objective.code + ".")]
            placed[objective.code] = topic
        for exclusion in eu.exclusions:
            named = re.search(r"\(EK:?\s*([A-Z]{2,5}-\d+\.[A-Z])", exclusion)
            # An exclusion that names its knowledge item goes with that item's
            # objective; otherwise with the first topic of its enduring understanding.
            topic = placed.get(named.group(1)) if named else None
            topic = topic or next(iter(placed.values()), None)
            if topic is not None:
                topic.exclusions.append(re.sub(r"^\(EK:?[^)]*\):?\s*", "", exclusion))
    return topics


def _spaces(text: str) -> str:
    """Some CEDs (CS Principles) use the control character U+0003 as a space."""
    return text.replace("\x03", " ")


def _short_title(text: str) -> str:
    """An enduring understanding is a sentence; use its first clause as a topic title."""
    text = _clean(text)
    first = re.split(r"(?<=[.;:])\s", text, maxsplit=1)[0]
    return first if len(first) <= 120 else first[:117].rsplit(" ", 1)[0] + "..."


def _layout(blocks) -> tuple[float, float, float | None, bool] | None:
    """Column positions from this page's own headings, or None if it has none."""
    lo = [x for x, y, t in blocks if t.strip().startswith("LEARNING OBJECTIVE")]
    ek = [x for x, y, t in blocks if t.strip().startswith(EK_HEADINGS)]
    if not lo or not ek:
        return None
    skills = [x for x, y, t in blocks if t.strip().startswith(("SUGGESTED SKILLS", "AVAILABLE RESOURCES"))]
    skills_x = min(skills) if skills else None
    return min(lo), min(ek), skills_x, bool(skills_x is not None and skills_x > min(ek))


def _read_column(blocks: list[tuple[float, str]], topic: _ApTopic) -> None:
    target: _Item | None = None
    in_exclusion = False
    exclusion: list[str] = []

    def flush_exclusion() -> None:
        nonlocal exclusion
        if exclusion:
            text = _clean(" ".join(exclusion))
            if text and text not in topic.exclusions:
                topic.exclusions.append(text)
        exclusion = []

    for _y, text in sorted(blocks):
        stripped = text.strip()
        if "EXCLUSION STATEMENT" in stripped:
            in_exclusion, target = True, None
            rest = stripped.split("EXCLUSION STATEMENT", 1)[1].lstrip(" —–-:\n")
            ref = re.match(r"\(EK:?\s*[^)]*\):?", rest)
            if ref:  # "(EK: AAP-2.P.1):" says which knowledge item it qualifies; keep it for regrouping
                exclusion.append(ref.group(0))
                rest = rest[ref.end():]
            if _is_prose(rest):
                exclusion.append(rest)
            continue
        # A heading can share a block with the first code under it
        # ("LEARNING OBJECTIVE\n1.1.A\nDescribe..."): drop the heading, keep the rest.
        lines = stripped.splitlines()
        dropped = 0
        while lines and lines[0].strip().startswith(STOP_HEADINGS):
            lines.pop(0)
            dropped += 1
        if dropped:
            flush_exclusion()
            in_exclusion, target = False, None
            stripped = "\n".join(lines).strip()
            if not stripped:
                continue
        stripped = SKILL_TAG.sub(" ", stripped)
        history = HISTORY_LO.match(stripped)
        ek, lo = EK_CODE.match(stripped), LO_CODE.match(stripped)
        if ek or lo or history:
            flush_exclusion()
            in_exclusion = False
            if history:
                code = f"U{history.group(1)}.{history.group(2)}"
                matched = history.group(0)
            else:
                code, matched = (ek or lo).group(1), (ek or lo).group(0)
            bucket = topic.knowledge if ek else topic.objectives
            target = next((item for item in bucket if item.code == code), None)
            if target is None:
                target = _Item(code)
                bucket.append(target)
            stripped = stripped[len(matched):]
        elif TOPIC_HEAD.match(stripped) or stripped.startswith(SKILL_NOTE):
            flush_exclusion()
            in_exclusion, target = False, None
            continue
        if in_exclusion:
            if _is_prose(stripped):
                exclusion.append(stripped)
            continue
        if target is not None and (_is_prose(stripped) or BC_ONLY.fullmatch(stripped)):
            if BC_ONLY.search(stripped):
                target.bc_only = True
                stripped = BC_ONLY.sub(" ", stripped)
            piece = _clean(stripped)
            if piece and piece not in target.text:
                target.text = _clean(f"{target.text} {piece}")
    flush_exclusion()


def to_subject(topics: list[_ApTopic], *, code: str, name: str, source: str, level: str = "AP",
               bc_handling: str = "keep") -> Subject:
    """Build a Subject. ``bc_handling="exclude"`` (AP Calculus AB) turns BC-only content into exclusions."""
    subject = Subject(subject_id=code, name=name, code=code, level=level, source=source)
    units: dict[str, Topic] = {}
    bc_only_topics: list[str] = []

    for t in topics:
        for item in (*t.objectives, *t.knowledge):
            item.text = re.sub(r"(\s+\d\.[A-Z])+\s*$", "", item.text)  # trailing skill codes: "... process. 1.B"
        objectives = [o for o in t.objectives if o.text]
        knowledge = [k for k in t.knowledge if k.text]
        exclude = list(t.exclusions)
        if bc_handling == "exclude":
            if t.bc_only_title or (objectives and all(o.bc_only for o in objectives)):
                bc_only_topics.append(f"{t.title} (topic {t.number}, BC only)")
                continue
            exclude += [f"{k.text} (BC only)" for k in knowledge if k.bc_only]
            objectives = [o for o in objectives if not o.bc_only]
            knowledge = [k for k in knowledge if not k.bc_only]
        if not objectives and not knowledge and not t.note:
            continue

        unit = units.setdefault(t.unit_number, Topic(topic_id=f"{code}-U{t.unit_number}", number=t.unit_number,
                                                     name=t.unit_name))
        include = [o.text for o in objectives] + [k.text for k in knowledge] or [t.note]
        statement = " ".join(o.text for o in objectives) or t.note
        unit.learning_objectives.append(LearningObjective(
            subject_id=code, subject_name=name, topic_id=unit.topic_id, topic_name=unit.name,
            lo_id=f"{code}-{t.number}", number=t.number, title=t.title, statement=statement,
            include=tuple(include), exclude=tuple(exclude),
            keywords=derive_keywords(t.title, *include), exam_skills=derive_exam_skills(statement),
            source=source, page=t.page))

    if bc_only_topics:
        unit = Topic(topic_id=f"{code}-BC", number="BC", name="Assessed only on AP Calculus BC")
        unit.learning_objectives.append(LearningObjective(
            subject_id=code, subject_name=name, topic_id=unit.topic_id, topic_name=unit.name,
            lo_id=f"{code}-BC", number="BC", title="Topics assessed only on the BC exam",
            statement="These topics are in the AP Calculus BC course but are not assessed on the AB exam.",
            include=(), exclude=tuple(bc_only_topics), source=source, page=0))
        units["BC"] = unit

    subject.topics = list(units.values())
    return subject
