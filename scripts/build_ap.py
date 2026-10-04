"""Build data/ap_syllabus.json from College Board AP Course and Exam Descriptions.

    python scripts/build_ap.py            # needs the CED PDFs in syllabus_pdfs/ap/

Download the PDFs from AP Central (apcentral.collegeboard.org); the file names
below are the URL slugs, e.g. ap-physics-1-course-and-exam-description.pdf is
saved as physics-1.pdf. The CEDs are not redistributed with this repo.

Courses whose CEDs are skills-based with no content topics (world languages,
English Language and Literature, Seminar, Research, Art and Design) or that
list required artworks rather than objectives (Art History) are not included:
"is this on the exam?" has no syllabus answer there.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from syllabus_core.syllabus.ap_ced import parse_ced, to_subject  # noqa: E402

PDFS = ROOT / "syllabus_pdfs" / "ap"
OUTPUT = ROOT / "data" / "ap_syllabus.json"

# (pdf slug, subject code, subject name). Calculus becomes two subjects.
COURSES = [
    ("biology", "BIO", "Biology"),
    ("chemistry", "CHEM", "Chemistry"),
    ("environmental-science", "ENVSCI", "Environmental Science"),
    ("physics-1", "PHYS1", "Physics 1"),
    ("physics-2", "PHYS2", "Physics 2"),
    ("physics-c-mechanics", "PHYSCM", "Physics C: Mechanics"),
    ("physics-c-electricity-and-magnetism", "PHYSCE", "Physics C: Electricity and Magnetism"),
    ("precalculus", "PRECALC", "Precalculus"),
    ("statistics", "STAT", "Statistics"),
    ("computer-science-a", "CSA", "Computer Science A"),
    ("computer-science-principles", "CSP", "Computer Science Principles"),
    ("macroeconomics", "MACRO", "Macroeconomics"),
    ("microeconomics", "MICRO", "Microeconomics"),
    ("psychology", "PSYCH", "Psychology"),
    ("human-geography", "HUMGEO", "Human Geography"),
    ("us-government-and-politics", "USGOV", "United States Government and Politics"),
    ("comparative-government-and-politics", "COMPGOV", "Comparative Government and Politics"),
    ("us-history", "USHIST", "United States History"),
    ("world-history-modern", "WHIST", "World History: Modern"),
    ("european-history", "EUROHIST", "European History"),
    ("african-american-studies", "AAS", "African American Studies"),
    ("music-theory", "MUSIC", "Music Theory"),
]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    subjects = []
    for slug, code, name in COURSES:
        pdf = PDFS / f"{slug}.pdf"
        if not pdf.exists():
            print(f"  missing {pdf.name}, skipped")
            continue
        topics = parse_ced(pdf)
        source = f"AP {name} CED"
        subjects.append(to_subject(topics, code=code, name=name, source=source))
        print(f"  AP {name:40s} {len(subjects[-1].objectives):4d} objectives")

    calculus = PDFS / "calculus.pdf"
    if calculus.exists():
        topics = parse_ced(calculus)
        subjects.append(to_subject(topics, code="CALCAB", name="Calculus AB", source="AP Calculus CED",
                                   bc_handling="exclude"))
        subjects.append(to_subject(topics, code="CALCBC", name="Calculus BC", source="AP Calculus CED"))
        print(f"  AP Calculus AB / BC {len(subjects[-2].objectives)} / {len(subjects[-1].objectives)} objectives")

    data = {
        "exam_board": "College Board",
        "qualification": "Advanced Placement (AP)",
        "generated_by": "scripts/build_ap.py",
        "subjects": [s.to_dict() for s in subjects],
    }
    OUTPUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    total = sum(len(s.objectives) for s in subjects)
    print(f"\nWrote {total} objectives across {len(subjects)} AP subjects to {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
