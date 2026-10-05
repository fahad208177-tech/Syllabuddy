"""Build data/sat_syllabus.json from the College Board's Digital SAT Suite framework.

    python scripts/build_sat.py       # needs syllabus_pdfs/sat/framework.pdf

Source: "Assessment Framework for the Digital SAT Suite" (College Board),
https://satsuite.collegeboard.org/media/pdf/assessment-framework-for-digital-sat-suite.pdf

Appendix B lists every skill/knowledge testing point. Three subjects are built:
SAT Reading and Writing, SAT Math, and PSAT 8/9 Math (SAT content the PSAT 8/9
leaves out is recorded as excluded). PSAT/NMSQT and PSAT 10 test the SAT's
skills, so they resolve to the SAT subjects.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from syllabus_core.syllabus.sat import parse  # noqa: E402

PDF = ROOT / "syllabus_pdfs" / "sat" / "framework.pdf"
OUTPUT = ROOT / "data" / "sat_syllabus.json"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not PDF.exists():
        print(f"missing {PDF.relative_to(ROOT)}; download the framework PDF first")
        return 1
    subjects = parse(PDF)
    for subject in subjects:
        print(f"  {subject.level} {subject.name}: {len(subject.objectives)} skills, "
              f"{sum(len(o.include) for o in subject.objectives)} testing points, "
              f"{sum(len(o.exclude) for o in subject.objectives)} exclusions")
    data = {"exam_board": "College Board", "qualification": "Digital SAT Suite (SAT, PSAT/NMSQT, PSAT 10, PSAT 8/9)",
            "generated_by": "scripts/build_sat.py", "subjects": [s.to_dict() for s in subjects]}
    OUTPUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
