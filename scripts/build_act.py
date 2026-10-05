"""Build data/act_syllabus.json from ACT's College and Career Readiness Standards.

    python scripts/build_act.py       # needs the PDFs in syllabus_pdfs/act/

Sources (ACT, https://www.act.org/standard):
  English.pdf  https://www.act.org/content/dam/act/unsecured/documents/CCRS-EnglishStandards.pdf
  Math.pdf     https://www.act.org/content/dam/act/unsecured/documents/CCRS-MathStandards.pdf
  Reading.pdf  https://www.act.org/content/dam/act/unsecured/documents/CCRS-ReadingStandards.pdf
  Science.pdf  https://www.act.org/content/dam/act/unsecured/documents/CCRS-ScienceStandards.pdf
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from syllabus_core.syllabus.act import parse  # noqa: E402

PDFS = ROOT / "syllabus_pdfs" / "act"
OUTPUT = ROOT / "data" / "act_syllabus.json"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    subjects = parse(PDFS)
    if not subjects:
        print(f"no PDFs in {PDFS.relative_to(ROOT)}; download them first (see the docstring)")
        return 1
    for subject in subjects:
        print(f"  ACT {subject.name}: {len(subject.objectives)} standards as objectives, "
              f"{len(subject.topics)} strand and score-range topics")
    data = {"exam_board": "ACT", "qualification": "The ACT (College and Career Readiness Standards)",
            "generated_by": "scripts/build_act.py", "subjects": [s.to_dict() for s in subjects]}
    OUTPUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
