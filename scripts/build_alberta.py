"""Build data/alberta_syllabus.json from Alberta Education Programs of Study.

    python scripts/build_alberta.py       # needs the PDFs in syllabus_pdfs/alberta/

Sources (Alberta Education, education.alberta.ca):
  physics20-30.pdf    https://education.alberta.ca/media/159713/phy2030_07.pdf
  chemistry20-30.pdf  https://education.alberta.ca/media/159730/chem2030_07.pdf

Only the 30-level courses are built: those are the Diploma Examination courses.
Biology 30 and Mathematics 30-1 are not included yet: the Biology 20-30 PDF on
open.alberta.ca refuses automated downloads, and the Mathematics 10-12 PDF has
moved. Download them by hand into syllabus_pdfs/alberta/ to add them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from syllabus_core.syllabus.alberta import parse  # noqa: E402

PDFS = ROOT / "syllabus_pdfs" / "alberta"
OUTPUT = ROOT / "data" / "alberta_syllabus.json"
COURSES = [
    ("physics20-30.pdf", "Physics 30", "PHYS30", "Physics 30"),
    ("chemistry20-30.pdf", "Chemistry 30", "CHEM30", "Chemistry 30"),
]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    subjects = []
    for filename, course, code, name in COURSES:
        pdf = PDFS / filename
        if not pdf.exists():
            print(f"  missing {filename}, skipped")
            continue
        subject = parse(pdf, course=course, code=code, name=name, source=f"Alberta {name} Program of Studies")
        subjects.append(subject)
        print(f"  Alberta {name}: {len(subject.objectives)} general outcomes, "
              f"{sum(len(o.include) for o in subject.objectives)} knowledge outcomes")
    data = {"exam_board": "Alberta Education", "qualification": "Alberta Diploma Examinations (Grade 12)",
            "generated_by": "scripts/build_alberta.py", "subjects": [s.to_dict() for s in subjects]}
    OUTPUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
