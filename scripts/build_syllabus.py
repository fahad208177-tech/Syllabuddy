"""Build data/syllabus.json from the syllabus PDFs.

    python scripts/build_syllabus.py

This is the step that turns PDFs into the structured backbone the tutor reasons
over. Re-run it whenever a syllabus PDF changes or a parser is improved, then
read the summary it prints and spot-check the JSON: the parsers are
deterministic, but the source PDFs are not, and a silently mis-parsed objective
would quietly corrupt every answer that cites it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from syllabus_core.syllabus import registry  # noqa: E402

SYLLABUS_FOLDER = Path("syllabus_pdfs")  # download the official SEAB PDFs here
OUTPUT = Path("data") / "syllabus.json"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not SYLLABUS_FOLDER.exists():
        print(f"No syllabus folder at {SYLLABUS_FOLDER}.")
        return 1

    data = registry.build(SYLLABUS_FOLDER)
    if not data["subjects"]:
        print(f"No registered syllabus PDFs found in {SYLLABUS_FOLDER}.")
        print("Registered filenames:", ", ".join(s.filename for s in registry.SOURCES))
        return 1

    OUTPUT.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    total = 0
    for subject in data["subjects"]:
        objectives = sum(len(t["learning_objectives"]) for t in subject["topics"])
        total += objectives
        print(f"\n{subject['code']} {subject['name']} ({subject['source']})")
        print(f"  {len(subject['topics'])} topics, {objectives} learning objectives")
        for topic in subject["topics"]:
            count = len(topic["learning_objectives"])
            print(f"    {topic['number']:>5}  {topic['name'][:52]:<52} {count:>3} LOs")

    print(f"\nWrote {total} learning objectives to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
