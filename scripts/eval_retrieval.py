"""Measure how well a question reaches the right learning objective.

(Carried over from the original A-Level tutor, now run against Syllabuddy's service.)

    python scripts/eval_retrieval.py

Retrieval is the part of this system most likely to degrade silently: a change
that helps maths questions can quietly break computing ones, and you would only
notice through worse answers. This script pins the behaviour to a labelled set
so any change to embedding model, fusion weights or searchable text can be
judged by number rather than by impression.

Metrics are top-1 accuracy (was the best objective ranked first) and MRR
(1/rank of the correct objective, averaged), which rewards near-misses too.

Add cases whenever you find a question the tutor mishandles.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from syllabus_core.retrieval import HybridRetriever  # noqa: E402
from syllabus_core.service import SyllabusService  # noqa: E402

# (question, acceptable learning objective ids). Several are listed where more
# than one objective genuinely covers the question.
CASES: list[tuple[str, tuple[str, ...]]] = [
    # --- Physics 9478 ---
    ("how do I calculate the moment of a force", ("9478.2.d",)),
    ("conservation of momentum in a collision", ("9478.6.b", "9478.6.c")),
    # H1 Physics 8867 shares this early topic near-verbatim with H2 (8867.7.d
    # is word-for-word identical to 9478.7.d), so its equivalent objectives
    # are just as correct an answer once H1 is in the corpus.
    ("centripetal force in circular motion", ("9478.7.f", "9478.7.e", "8867.7.d", "8867.7.i")),
    ("escape velocity from a planet", ("9478.8.i",)),
    ("simple harmonic motion defining equation", ("9478.9.d",)),
    ("using a diffraction grating to find wavelength", ("9478.11.j",)),
    ("ideal gas equation of state", ("9478.12.c",)),
    ("first law of thermodynamics", ("9478.13.f",)),
    ("Coulomb's law between two point charges", ("9478.14.a",)),
    ("energy stored in a charged capacitor", ("9478.14.j", "9478.14.k")),
    ("photoelectric effect threshold frequency", ("9478.19.a",)),
    ("half-life of radioactive decay", ("9478.20.j",)),
    ("binding energy per nucleon and nuclear fission", ("9478.20.t",)),
    # --- Chemistry 9729 ---
    ("predict the shape of a molecule using electron pair repulsion", ("9729.2.d", "9729.2.e")),
    ("Bronsted-Lowry theory of acids and bases", ("9729.4.b",)),
    ("calculate empirical formula from combustion data", ("9729.6.e",)),
    ("rate equation and order of reaction", ("9729.8.a",)),
    ("effect of a catalyst on reaction rate", ("9729.8.i",)),
    ("Le Chatelier's principle", ("9729.9.b",)),
    ("calculate the pH of a buffer solution", ("9729.10.1.g",)),
    ("explain cis-trans isomerism in alkenes", ("9729.11.2.b",)),
    ("nucleophilic substitution mechanism in halogenoalkanes", ("9729.11.4.b",)),
    ("why are CFCs a concern for the atmosphere", ("9729.11.4.h",)),
    ("standard electrode potential and standard cell potential", ("9729.12.b",)),
    ("Faraday constant and charge passed during electrolysis", ("9729.12.n",)),
    ("d orbital splitting in transition metal complexes", ("9729.13.k",)),
    # --- Computing 9569 ---
    ("quicksort time complexity", ("9569.1.2.5", "9569.1.2.1")),
    ("normalise a database to third normal form", ("9569.3.3.4",)),
    ("how does push and pop work on a stack", ("9569.1.3.3", "9569.2.3.3")),
    ("explain encapsulation and information hiding", ("9569.2.5.2",)),
    ("convert a denary number to hexadecimal", ("9569.3.1.1", "9569.3.1.2")),
    ("what is a binary search tree traversal", ("9569.1.3.6", "9569.1.3.7")),
    ("what is polymorphism in object oriented programming", ("9569.2.5.4",)),
    ("validate that an input is within a range", ("9569.2.4.2",)),
    ("what is phishing and how to prevent it", ("9569.4.3.1", "9569.4.3.2")),
    # 9569.4.1.5 ("Explain client-server architecture") answers this at least
    # as directly as the original two codes; a growing corpus shifts BM25's
    # corpus-wide IDF/length-normalisation statistics enough to reorder
    # already-close candidates like these, and this one turned out to have
    # been under-credited rather than the ranking having gotten worse.
    ("how does HTTP work between client and server", ("9569.4.2.1", "9569.4.1.4", "9569.4.1.5")),
    ("design test cases with normal and abnormal data", ("9569.2.4.4",)),
    ("how does recursion work in programming", ("9569.2.2.5",)),
    ("difference between static and dynamic memory allocation", ("9569.1.3.1", "9569.1.3.2")),
    ("draw a flowchart using standard symbols", ("9569.1.1.2",)),
    ("explain inheritance in object oriented programming", ("9569.2.5.3",)),
    ("what is the difference between a primary key and a foreign key", ("9569.3.3.2",)),
    ("how do I write an SQL join across two tables", ("9569.3.3.8",)),
    ("explain IP addressing and DNS", ("9569.4.1.2",)),
    ("what is the difference between a LAN and a WAN", ("9569.4.1.1",)),
    ("why is version control needed in software projects", ("9569.3.3.12",)),
    ("what does a firewall do", ("9569.4.3.2",)),
    ("how does the Personal Data Protection Act apply to data in Singapore", ("9569.3.3.13",)),
    ("how is text represented using ASCII and Unicode", ("9569.3.2.1", "9569.3.2.2")),
    ("difference between data validation and data verification", ("9569.2.4.1",)),
    ("explain socket programming for an iterative server", ("9569.4.1.6",)),
]

TOP_K = 5


def evaluate(retriever: HybridRetriever, label: str) -> None:
    hits_at_1 = 0
    reciprocal_total = 0.0
    misses: list[tuple[str, str, str]] = []
    started = time.time()

    for question, expected in CASES:
        results = retriever.search(question, top_k=TOP_K)
        ranked_ids = [hit.item.lo_id for hit in results]

        rank = next(
            (i + 1 for i, lo_id in enumerate(ranked_ids) if lo_id in expected), 0
        )
        if rank == 1:
            hits_at_1 += 1
        if rank:
            reciprocal_total += 1 / rank
        else:
            misses.append((question, "/".join(expected), ", ".join(ranked_ids[:3])))

    total = len(CASES)
    elapsed = time.time() - started
    print(f"\n{label}")
    print(f"  top-1 {hits_at_1}/{total} ({hits_at_1 / total:.0%})   "
          f"MRR@{TOP_K} {reciprocal_total / total:.3f}   "
          f"{elapsed / total * 1000:.0f}ms/query")
    for question, expected, got in misses:
        print(f"    MISS  {question[:46]:<46} want {expected:<20} got {got}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    service = SyllabusService()  # same retriever, corrections and caches the MCP server uses
    objectives = service.objectives
    print(f"{len(objectives)} objectives, {len(CASES)} evaluation questions")

    retriever = service.retriever
    if not retriever.dense_available:
        print(f"Dense retrieval unavailable: {retriever.error}")

    evaluate(retriever, "hybrid (dense + lexical)")

    # Isolate each signal so a regression can be traced to the right half.
    lexical_only = HybridRetriever(objectives, store=None)
    evaluate(lexical_only, "lexical only (BM25)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
