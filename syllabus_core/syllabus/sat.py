"""Parse the College Board "Assessment Framework for the Digital SAT Suite".

Appendix B tabulates every skill/knowledge testing point:

* Reading and Writing (Table A33): domains, skills and sub-skills, nested by
  indentation ("Standard English Conventions" > "Boundaries" > "Between Sentences");
* Math (Tables A34-A37, one per domain): each skill with three description
  columns, for the SAT, the PSAT/NMSQT and PSAT 10, and the PSAT 8/9.

Each skill becomes a learning objective. Because the PSAT 8/9 column omits some
SAT content, a PSAT 8/9 Math subject is built too, with that content excluded
(the way AP Calculus AB excludes "bc only" topics).
"""

from __future__ import annotations

import re
from pathlib import Path

from syllabus_core.syllabus.schema import LearningObjective, Subject, Topic, derive_exam_skills, derive_keywords

MATH_TABLE = re.compile(r"Table A3[4-7]\.\s*Digital SAT Suite Math Section Skill/Knowledge\s+Testing Points:\s*(.+)")
SOURCE = "SAT Suite Assessment Framework"

# Column boundaries (PDF points) of the math tables: skill | SAT | PSAT/NMSQT | PSAT 8/9
SKILL_MAX_X, SAT_MAX_X, PSAT_MAX_X = 135, 325, 515


def _clean(text: str) -> str:
    text = text.replace(" ", " ").replace(" ", " ").replace("\t", " ")
    text = re.sub(r"\s*•\s*", " • ", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r" \^", "^", text)
    text = re.sub(r" ([,.;:)])", r"\1", text)
    return text.strip(" •")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


FOOTER = "ASSESSMENT FRAMEWORK FOR THE DIGITAL SAT SUITE"


def _blocks(page) -> list[tuple[float, float, str]]:
    return [(b[0], b[1], b[4]) for b in page.get_text("blocks")
            if b[4].strip() and b[1] > 70 and FOOTER not in b[4] and not b[4].startswith("Appendix B")]


def _lines(page) -> list[tuple[float, float, str, bool, float]]:
    """Every span with its position, boldness and size. Spans, not lines: on one
    baseline PyMuPDF can merge text from different table columns into one line."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = span["text"].strip()
                x0, y0 = span["bbox"][0], span["bbox"][1]
                if span["size"] < 6 and len(text) <= 3:
                    text = f"^{text}"   # an exponent, e.g. the 2 of k^2
                elif re.fullmatch(r"\d{1,3}", text):
                    continue            # a page number
                if text and y0 > 95 and FOOTER not in text and not text.startswith("Appendix B"):
                    out.append((x0, y0, text, "Bold" in span["font"], span["size"]))
    return out


def parse(pdf_path: str | Path) -> list[Subject]:
    import pymupdf

    doc = pymupdf.open(str(pdf_path))
    pages = [p for p in doc if "Appendix B: Digital SAT Suite Detailed Skill/Knowledge" in p.get_text()]
    reading = _reading_writing([p for p in pages if "SAT Description" not in p.get_text()])
    math = _math([p for p in pages if "SAT Description" in p.get_text()])
    return [
        _subject("SATRW", "Reading and Writing", "SAT", reading, column="sat"),
        _subject("SATM", "Math", "SAT", math, column="sat"),
        _subject("PSAT89M", "Math", "PSAT 8/9", math, column="psat89", exclude_missing_from="sat"),
    ]


def _reading_writing(pages) -> list[dict]:
    """Domains (x~64) > skills (x~70) > sub-skills (x~79), each "Name\\nStudents will ..."."""
    domains: list[dict] = []
    pending_name = None
    for page in pages:
        for x, y, text in sorted(_blocks(page), key=lambda b: (b[1], b[0])):
            stripped = text.strip()
            if stripped.startswith(("Content Dimension", "Table A", "The following tables")):
                continue
            if x > 150:  # a description printed in its own block, beside its name
                if pending_name is not None:
                    pending_name["desc"] = _clean(f"{pending_name['desc']} {stripped}")
                continue
            if "Students will" in stripped or "The passages" in stripped:
                cut = min(i for i in (stripped.find("Students will"), stripped.find("The passages")) if i >= 0)
                name, desc = stripped[:cut], stripped[cut:]
            else:
                name, desc = stripped, ""
            entry = {"name": _clean(name), "desc": _clean(desc), "subs": [], "page": page.number + 1}
            pending_name = entry
            if x < 67:
                entry["skills"] = []
                domains.append(entry)
            elif x < 75 and domains:
                domains[-1]["skills"].append(entry)
            elif domains and domains[-1]["skills"]:
                domains[-1]["skills"][-1]["subs"].append(entry)
    out = []
    for domain in domains:
        if not domain["skills"]:
            continue  # "Text Complexity" describes passages, not a skill
        skills = []
        for skill in domain["skills"]:
            include = [skill["desc"]] + [f"{s['name']}: {s['desc']}" for s in skill["subs"]]
            skills.append({"name": skill["name"], "page": skill["page"], "sat": [i for i in include if i], "psat89": [i for i in include if i]})
        out.append({"name": domain["name"], "skills": skills})
    return out


COLUMNS = ("sat", "psat", "psat89")
GLYPHS = {"•", "»"}


def _column_starts(spans) -> list[tuple[float, str]]:
    """Left edges of the description columns on one page, labelled from the header
    row. Pages differ in width, so the edges are found from the most common left
    margins of regular text rather than fixed positions."""
    headers = sorted((x, t) for x, y, t, bold, size in spans if bold and t.endswith("Description") and y < 125)
    labels = ["psat89" if "8/9" in t else "psat" if "NMSQT" in t else "sat" for _, t in headers]
    counts: dict[int, int] = {}
    for x, y, t, bold, size in spans:
        if not bold and x >= SKILL_MAX_X and t not in GLYPHS:
            counts[round(x)] = counts.get(round(x), 0) + 1
    starts: list[float] = []
    for x, _ in sorted(counts.items(), key=lambda kv: -kv[1]):
        if all(abs(x - s) > 100 for s in starts):
            starts.append(x)
        if len(starts) == len(labels):
            break
    if not labels or len(starts) != len(labels):
        return [(SKILL_MAX_X, "sat"), (SAT_MAX_X, "psat"), (PSAT_MAX_X, "psat89")]
    # A bullet's text is indented ~9pt; the column edge is the smallest common margin near the peak.
    starts = sorted(min(x for x in counts if 0 <= s - x <= 12 or x == s) for s in starts)
    return list(zip(starts, labels))


def _column(x: float, starts: list[tuple[float, str]]) -> str:
    label = starts[0][1]
    for start, name in starts:
        if x >= start - 4:
            label = name
    return label


def _expand(statement: dict) -> list[str]:
    """A statement with bullets becomes one testing point per bullet (per sub-bullet),
    each prefixed with its stem, so the SAT and PSAT 8/9 versions compare bullet by bullet."""
    if not statement["bullets"]:
        return [_clean(statement["text"])]
    stem = statement["text"].strip()
    if not stem.endswith(":") and len(stem.split()) > 25:
        # A long explanatory paragraph followed by bullets: keep them apart.
        return [_clean(stem)] + [_clean(f"{b['text']} {' '.join(b['subs'])}") for b in statement["bullets"]]
    out = []
    for bullet in statement["bullets"]:
        if bullet["subs"]:
            out += [_clean(f"{statement['text']} {bullet['text']} {sub}") for sub in bullet["subs"]]
        else:
            out.append(_clean(f"{statement['text']} {bullet['text']}"))
    return out


def _math(pages) -> list[dict]:
    """Per domain table: bold skill names at the left, then SAT / PSAT / PSAT 8/9
    description columns. Inside a column, statements sit at the column edge, bullet
    text ~9pt in and sub-bullet text ~18pt in; lines of one statement are 10pt apart
    and consecutive statements 13pt apart."""
    domains: list[dict] = []
    for page in pages:
        title = MATH_TABLE.search(" ".join(page.get_text().split()))
        if title:
            name = re.sub(r"\s*\(SAT.*$", "", re.split(r"\s+Content\b", title.group(1))[0]).strip()
            domains.append({"name": name, "skills": []})
        if not domains:
            continue
        domain = domains[-1]
        raw = _lines(page)
        starts = _column_starts(raw)
        spans = [(y, x, t, bold) for x, y, t, bold, size in raw
                 if t not in GLYPHS
                 and not (bold and (t.startswith(("Content", "Dimension", "Table A")) or t.endswith("Description")))]
        # Group description spans into visual rows per column (superscripts and italic
        # variables sit a few points off the baseline), so a row's indent is its first span's.
        rows: list[list] = []
        for y, x, t, bold in sorted(spans):
            if x < SKILL_MAX_X:
                rows.append([y, x, t, True if bold else None])
                continue
            column = _column(x, starts)
            row = next((r for r in reversed(rows[-12:]) if r[3] == column and abs(r[0] - y) < 4.5), None)
            if row is None:
                rows.append([y, x, t, column, [(x, t)]])
            else:
                row[4].append((x, t))
                row[1] = min(row[1], x)
        for row in rows:
            if len(row) == 5:
                row[2] = " ".join(t for _, t in sorted(row[4]))
        rows.sort(key=lambda r: r[0])
        edge = {c: min((r[1] for r in rows if r[3] == c), default=0) for c in COLUMNS}
        current = None
        last_name_y = -100.0
        last: dict[str, tuple[float, int]] = {}
        for row in rows:
            y, x, t = row[0], row[1], re.sub(r"\s*\(continued\)\s*", " ", row[2]).strip()
            if x < SKILL_MAX_X:
                if row[3] is not True or not t:
                    continue
                if current is not None and y - last_name_y < 16 and current["_open"]:
                    current["name"] = _clean(f"{current['name']} {t}")   # a wrapped skill name
                else:
                    if current is not None:
                        current["_open"] = False
                    current = {"name": _clean(t), "_open": True, "page": page.number + 1, **{c: [] for c in COLUMNS}}
                    domain["skills"].append(current)
                last_name_y = y
                continue
            if current is None or not t:
                continue
            column = row[3]
            level = min(2, max(0, round((x - edge[column]) / 9)))
            statements = current[column]
            prev_y, prev_level = last.get(column, (-100.0, -1))
            continues = y - prev_y < 11.5 and level == prev_level and statements
            if level == 0:
                if continues:
                    statements[-1]["text"] += f" {t}"
                else:
                    statements.append({"text": t, "bullets": []})
            elif statements:
                bullets = statements[-1]["bullets"]
                if level == 1:
                    if continues and bullets:
                        bullets[-1]["text"] += f" {t}"
                    else:
                        bullets.append({"text": t, "subs": []})
                elif bullets:
                    subs = bullets[-1]["subs"]
                    if continues and subs:
                        subs[-1] += f" {t}"
                    else:
                        subs.append(t)
            last[column] = (y, level)
    # Skills split across pages print their name again with "(continued)": merge them.
    for domain in domains:
        merged: list[dict] = []
        for skill in domain["skills"]:
            skill.pop("_open", None)
            for c in COLUMNS:
                points: list[str] = []
                for statement in skill[c]:
                    points += [p for p in _expand(statement) if len(re.findall(r"[a-z]{3,}", p)) >= 3]
                skill[c] = points
            same = next((m for m in merged if _norm(m["name"]) == _norm(skill["name"])), None)
            if same is None:
                merged.append(skill)
            else:
                for c in COLUMNS:
                    same[c] += [i for i in skill[c] if i not in same[c]]
        domain["skills"] = [s for s in merged if s["name"]]
    return domains


def _subject(code: str, name: str, level: str, domains: list[dict], *, column: str,
             exclude_missing_from: str | None = None) -> Subject:
    subject = Subject(subject_id=code, name=name, code=code, level=level, source=SOURCE)
    absent_skills: list[str] = []
    absent_page = 0
    for d_index, domain in enumerate(domains, 1):
        topic = Topic(topic_id=f"{code}-{d_index}", number=str(d_index), name=domain["name"])
        for s_index, skill in enumerate(domain["skills"], 1):
            include = list(skill.get(column) or [])
            exclude: list[str] = []
            if exclude_missing_from:
                theirs = skill.get(exclude_missing_from) or []
                mine = {_norm(i) for i in include}
                exclude = [f"{t} (SAT and PSAT/NMSQT only, not PSAT 8/9)" for t in theirs if _norm(t) not in mine]
                if not include:
                    absent_skills.append(f"{skill['name']} (SAT and PSAT/NMSQT only, not PSAT 8/9)")
                    absent_page = absent_page or skill["page"]
                    continue
            if not include:
                continue
            number = f"{d_index}.{s_index}"
            topic.learning_objectives.append(LearningObjective(
                subject_id=code, subject_name=name, topic_id=topic.topic_id, topic_name=topic.name,
                lo_id=f"{code}-{number}", number=number, title=skill["name"], statement=include[0],
                include=tuple(include), exclude=tuple(exclude),
                keywords=derive_keywords(skill["name"], *include), exam_skills=derive_exam_skills(*include),
                source=SOURCE, page=skill["page"]))
        if topic.learning_objectives:
            subject.topics.append(topic)
    if absent_skills:
        topic = Topic(topic_id=f"{code}-X", number="X", name="Not assessed on the PSAT 8/9")
        topic.learning_objectives.append(LearningObjective(
            subject_id=code, subject_name=name, topic_id=topic.topic_id, topic_name=topic.name,
            lo_id=f"{code}-X", number="X", title="SAT skills not assessed on the PSAT 8/9",
            statement="These skills are assessed on the SAT and PSAT/NMSQT but not on the PSAT 8/9.",
            include=(), exclude=tuple(absent_skills), source=SOURCE, page=absent_page))
        subject.topics.append(topic)
    return subject
