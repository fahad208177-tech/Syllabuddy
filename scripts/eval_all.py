"""Test every learning objective in every loaded exam.

    python scripts/eval_all.py            # writes artifacts/eval_report.md

For each objective:

1. data quality: a title, something it requires, no PDF debris (page headers,
   control characters, words split by letter-spacing), a unique id, a page;
2. its title, asked as a topic, comes back "examinable" (titles that are
   themselves inside an exclusion are skipped);
3. each of its exclusion statements comes back "excluded" (statements that are
   also taught elsewhere, e.g. "hypothesis tests", are reported as ambiguous);
4. its own first requirement, used as a question, finds it in the top 3
   (catches objectives that no student question could ever reach).

Prints a table per subject and writes every failure to the report.
"""

from __future__ import annotations

import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from syllabus_core.service import SyllabusService, _content_words  # noqa: E402

# Case-sensitive: "the learning objective" in prose is fine, a stray "LEARNING OBJECTIVE" heading is not,
# and only the footer "Return to Table of Contents" is debris, not the word "return".
DEBRIS = re.compile(r"Topics/Sub-topics|Course Framework|Return to (?:Table of )?Contents|RetuRn|©|\x03|\x07"
                    r"|\bbc\s+only\b|\b(?:[A-Za-z] ){4,}|SUGGESTED SKILLS|ESSENTIAL KNOWLEDGE|LEARNING OBJECTIVE"
                    r"|Course and Exam Description|continued on (?:the )?next page|Content \(continued\)")
REPORT = ROOT / "artifacts" / "eval_report.md"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    started = time.time()
    svc = SyllabusService()
    print(f"{len(svc.subjects)} subjects, {len(svc.objectives)} objectives loaded in {time.time() - started:.0f}s\n")

    stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    failures: dict[str, list[str]] = defaultdict(list)
    seen_ids: set[str] = set()

    for n, lo in enumerate(svc.objectives, 1):
        sid = lo.subject_id
        label = svc.subject_label(sid)
        s = stats[label]
        s["objectives"] += 1

        # 1. data quality
        problems = []
        if not lo.title.strip():
            problems.append("no title")
        if not (lo.include or lo.statement) and not lo.exclude:
            problems.append("requires nothing")
        if lo.lo_id in seen_ids:
            problems.append("duplicate id")
        seen_ids.add(lo.lo_id)
        if lo.page <= 0 and not lo.lo_id.endswith("-BC"):
            problems.append("no page")
        for text in (lo.title, lo.statement, *lo.include, *lo.exclude):
            hit = DEBRIS.search(text)
            if hit:
                problems.append(f"debris {hit.group(0)!r} in {text[:60]!r}")
                break
        if problems:
            s["quality_fail"] += 1
            failures["quality"].append(f"[{lo.lo_id}] {'; '.join(problems)}")

        # 2. title -> examinable
        title_words = _content_words(lo.title)
        in_exclusion = any(title_words and title_words <= _content_words(e) for o in svc.subject_by_id[sid].objectives
                           for e in o.exclude)
        if len(lo.title.split()) >= 2 and not in_exclusion and lo.include:
            verdict = svc.check_examinable(lo.title, sid)["verdict"]
            s["title_checked"] += 1
            if verdict != "examinable":
                s["title_fail"] += 1
                failures["title"].append(f"[{lo.lo_id}] {verdict:15s} {lo.title[:90]}")

        # 3. exclusions -> excluded
        for bullet in lo.exclude:
            words = _content_words(bullet)
            taught = any(words <= _content_words(f"{o.title} {' '.join(o.include)}")
                         for o in svc.subject_by_id[sid].objectives if o is not lo)
            if taught:
                s["exclusion_ambiguous"] += 1
                continue
            verdict = svc.check_examinable(bullet, sid)["verdict"]
            s["exclusion_checked"] += 1
            if verdict != "excluded":
                s["exclusion_fail"] += 1
                failures["exclusion"].append(f"[{lo.lo_id}] {verdict:15s} {bullet[:90]}")

        # 4. self-retrieval
        probe = (lo.include[0] if lo.include else lo.statement).strip()
        if probe:
            hits = svc.retriever.search(probe, top_k=3, predicate=svc._predicate([sid]))
            ids = [h.item.lo_id for h in hits]
            s["retrieval_checked"] += 1
            if ids and ids[0] == lo.lo_id:
                s["retrieval_top1"] += 1
            if lo.lo_id in ids:
                s["retrieval_top3"] += 1
            else:
                failures["retrieval"].append(f"[{lo.lo_id}] got {ids[:3]} for {probe[:70]!r}")

        if n % 250 == 0:
            print(f"  ...{n}/{len(svc.objectives)} ({time.time() - started:.0f}s)", flush=True)

    # ---- report
    def pct(a: int, b: int) -> str:
        return f"{a / b:.0%}" if b else "-"

    header = f"{'subject':48s} {'objs':>5s} {'quality':>8s} {'title':>8s} {'excl':>8s} {'top1':>6s} {'top3':>6s}"
    lines = [header, "-" * len(header)]
    totals: dict[str, int] = defaultdict(int)
    for label in sorted(stats):
        s = stats[label]
        for key, value in s.items():
            totals[key] += value
        lines.append(f"{label[:48]:48s} {s['objectives']:5d} {pct(s['objectives'] - s['quality_fail'], s['objectives']):>8s} "
                     f"{pct(s['title_checked'] - s['title_fail'], s['title_checked']):>8s} "
                     f"{pct(s['exclusion_checked'] - s['exclusion_fail'], s['exclusion_checked']):>8s} "
                     f"{pct(s['retrieval_top1'], s['retrieval_checked']):>6s} {pct(s['retrieval_top3'], s['retrieval_checked']):>6s}")
    t = totals
    lines += ["-" * len(header),
              f"{'ALL':48s} {t['objectives']:5d} {pct(t['objectives'] - t['quality_fail'], t['objectives']):>8s} "
              f"{pct(t['title_checked'] - t['title_fail'], t['title_checked']):>8s} "
              f"{pct(t['exclusion_checked'] - t['exclusion_fail'], t['exclusion_checked']):>8s} "
              f"{pct(t['retrieval_top1'], t['retrieval_checked']):>6s} {pct(t['retrieval_top3'], t['retrieval_checked']):>6s}",
              f"\nexclusions checked {t['exclusion_checked']}, ambiguous out of context {t['exclusion_ambiguous']}; "
              f"titles checked {t['title_checked']}; {time.time() - started:.0f}s"]
    table = "\n".join(lines)
    print("\n" + table)

    REPORT.parent.mkdir(exist_ok=True)
    body = ["# Syllabuddy: every-objective evaluation", "", "```", table, "```", ""]
    for kind in ("quality", "title", "exclusion", "retrieval"):
        body += [f"## {kind} failures ({len(failures[kind])})", ""] + [f"- {f}" for f in failures[kind]] + [""]
    REPORT.write_text("\n".join(body), encoding="utf-8")
    print(f"\nFailures written to {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
