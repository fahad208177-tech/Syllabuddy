"""Systematic check of check_examinable, using the syllabus to test itself.

    python scripts/eval_examinable.py [--show 20]

* every "Excluded" bullet, asked verbatim, should come back "excluded"
* every objective title, asked as a topic, should come back "examinable"
  (skipped when the title also appears inside an exclusion of the same subject)

Prints accuracy per check and the failures, so a threshold change can be
judged on hundreds of cases rather than a handful.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from syllabus_core.service import SyllabusService, _content_words  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", type=int, default=15, help="failures to print per check")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    svc = SyllabusService()
    checks: dict[str, list[tuple[str, str, str, str]]] = {"excluded": [], "examinable": []}

    ambiguous = []
    for lo in svc.objectives:
        for bullet in lo.exclude:
            # "hypothesis tests" is excluded from correlation, yet hypothesis testing is
            # its own examinable objective: out of context the right answer is "examinable".
            words = _content_words(bullet)
            taught = any(words <= _content_words(f"{o.title} {' '.join(o.include)}")
                         for o in svc.objectives if o.subject_id == lo.subject_id and o is not lo)
            if taught:
                ambiguous.append((lo.lo_id, bullet))
                continue
            checks["excluded"].append((bullet, lo.subject_id, "excluded", lo.lo_id))
        title = lo.title.strip()
        excluded_text = " ".join(e for o in svc.objectives if o.subject_id == lo.subject_id for e in o.exclude).lower()
        if len(title.split()) >= 2 and title.lower() not in excluded_text:
            checks["examinable"].append((title, lo.subject_id, "examinable", lo.lo_id))

    for lo_id, bullet in ambiguous:
        print(f"   ambiguous out of context, skipped: [{lo_id}] {bullet}")
    worst = 0.0
    for name, cases in checks.items():
        verdicts = Counter()
        failures = []
        for topic, subject, want, lo_id in cases:
            got = svc.check_examinable(topic, subject)["verdict"]
            verdicts[got] += 1
            if got != want:
                failures.append((subject, lo_id, got, topic))
        accuracy = 1 - len(failures) / len(cases) if cases else 1.0
        worst = max(worst, 1 - accuracy)
        print(f"\n== {name}: {accuracy:.1%} of {len(cases)}   verdicts: {dict(verdicts)}")
        for subject, lo_id, got, topic in failures[: args.show]:
            print(f"   [{subject} {lo_id}] got {got:16s} {topic[:110]}")
    return 0




def paraphrases() -> int:
    """Student phrasings from tests/paraphrases.py."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
    from paraphrases import PARAPHRASES

    svc = SyllabusService()
    wrong = 0
    for topic, subject, want in PARAPHRASES:
        r = svc.check_examinable(topic, subject)
        ok = r["verdict"] == want
        wrong += not ok
        print(f"{'ok ' if ok else 'BAD'} {r['verdict']:16s} (want {want:10s}) conf={r['confidence']:.2f}  {subject}: {topic}")
    print(f"\nparaphrases: {len(PARAPHRASES) - wrong}/{len(PARAPHRASES)} correct")
    return wrong


if __name__ == "__main__":
    if "--paraphrases" in sys.argv:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        sys.exit(1 if paraphrases() else 0)
    sys.exit(main())
