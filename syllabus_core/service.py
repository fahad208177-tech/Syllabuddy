"""The syllabus questions Syllabuddy can answer, as plain Python.

Everything the MCP server exposes is a thin wrapper over this module, so the
logic can be tested without a server, a network, or a language model. No
method here calls an LLM: every answer comes from the parsed syllabus, which
is what makes it safe to say "that's not examinable" out loud.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from syllabus_core.retrieval import HybridRetriever, build_store
from syllabus_core.syllabus import registry
from syllabus_core.syllabus.schema import LearningObjective, Subject

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SYLLABUS = ROOT / "data" / "syllabus.json"
DEFAULT_CACHE = ROOT / "cache"

# Confidence bands, carried over from the tutor where they were measured with
# its retrieval evaluation: genuine syllabus questions scored 0.59 to 0.86,
# clearly unrelated ones 0.44 to 0.58.
CONFIDENT = 0.62
PLAUSIBLE = 0.55

# check_examinable only reports "unclear" above this. The tutor's evaluation
# put off-syllabus questions as high as 0.58 and genuine ones from 0.59, so the
# verdict uses the gap rather than the softer PLAUSIBLE band.
UNCLEAR_MIN = 0.58

# An exclusion bullet is only treated as the answer when it matches the topic
# at least this well. Calibrated with tests/test_service.py: real exclusions
# phrased the way students ask them score 0.89 and above, while neighbouring
# examinable topics stay at or below 0.71.
EXCLUSION_MIN = 0.85
# ...and it must beat the best matching *included* bullet by this margin. Many
# objectives are examinable overall with a narrow part excluded ("hypothesis
# testing" is taught, "power of a test" is not), so an exclusion only wins
# when it is clearly more specific to the question than anything included.
EXCLUSION_MARGIN = 0.05
# The exclusion's own objective must be about as relevant as the best match.
PARENT_SLACK = 0.06

SUBJECT_ALIASES = {
    "math": "Mathematics", "maths": "Mathematics", "mathematics": "Mathematics", "a maths": "Mathematics",
    "physics": "Physics", "phys": "Physics", "phy": "Physics",
    "chemistry": "Chemistry", "chem": "Chemistry",
    "biology": "Biology", "bio": "Biology",
    "computing": "Computing", "computer science": "Computing", "cs": "Computing", "comp": "Computing",
    "economics": "Economics", "econs": "Economics", "econ": "Economics", "economy": "Economics",
    "geography": "Geography", "geog": "Geography", "geo": "Geography",
    "history": "History", "hist": "History",
}


@dataclass(frozen=True)
class Exclusion:
    """One "Excluded" clause, indexed on its own so it can be matched directly.

    ``text`` is what gets matched; ``bullet`` is the full syllabus wording that
    gets quoted back, since one bullet often packs several exclusions together.
    """

    text: str
    objective: LearningObjective
    bullet: str = ""

    @property
    def searchable_text(self) -> str:
        return self.text


@dataclass(frozen=True)
class Inclusion:
    """One "the syllabus requires" bullet, the counterweight to an exclusion."""

    text: str
    objective: LearningObjective

    @property
    def searchable_text(self) -> str:
        return self.text


def band(confidence: float) -> str:
    if confidence >= CONFIDENT:
        return "matched"
    if confidence >= PLAUSIBLE:
        return "approximate"
    return "weak"


class SyllabusService:
    def __init__(self, syllabus_path: str | Path = DEFAULT_SYLLABUS, cache_folder: str | Path = DEFAULT_CACHE) -> None:
        self.subjects: list[Subject] = registry.load(syllabus_path)
        self.objectives: list[LearningObjective] = [lo for s in self.subjects for lo in s.objectives]
        self.by_id: dict[str, LearningObjective] = {lo.lo_id: lo for lo in self.objectives}
        self._position = {lo.lo_id: i for i, lo in enumerate(self.objectives)}
        self.subject_by_id: dict[str, Subject] = {s.subject_id: s for s in self.subjects}

        _seed_cache(Path(cache_folder))
        store = build_store(cache_folder=cache_folder)
        store.client._cache_dir = str(Path(cache_folder) / "models")  # keep the model inside the repo cache
        _keep_queries_in_memory(store)
        self.retriever = HybridRetriever(self.objectives, store)
        self.exclusions = [Exclusion(clause, lo, bullet) for lo in self.objectives
                           for bullet in lo.exclude for clause in _clauses(bullet)]
        self.exclusion_retriever = HybridRetriever(self.exclusions, store)
        self.inclusions = [Inclusion(text, lo) for lo in self.objectives for text in (lo.include or (lo.statement,))]
        self.inclusion_retriever = HybridRetriever(self.inclusions, store)
        # Load the ONNX model now, so the first student question isn't the slow one.
        self.retriever.confidence("warm up")

    # ---- subjects -------------------------------------------------------------

    def resolve_subject(self, subject: str | None) -> list[str]:
        """Turn "H2 maths", "physics", "9758" or "econs" into subject ids.

        Returns every matching id (both H1 and H2 when no level is given), or an
        empty list when ``subject`` is blank, meaning "search everything".
        Raises ``ValueError`` when the text names no loaded subject.
        """
        if not subject or not subject.strip():
            return []
        text = subject.lower().strip()
        codes = [code for code in re.findall(r"\b\d{4}\b", text) if code in self.subject_by_id]
        if codes:
            return codes

        level = None
        match = re.search(r"\b(h[123])\b", text)
        if match:
            level = match.group(1).upper()
            text = (text[: match.start()] + text[match.end():]).strip()
        text = re.sub(r"\b(syllabus|subject|level|a-level|a level|gce)\b", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        name = SUBJECT_ALIASES.get(text)
        if name is None:
            for alias, candidate in sorted(SUBJECT_ALIASES.items(), key=lambda kv: -len(kv[0])):
                if re.search(rf"\b{re.escape(alias)}\b", text):
                    name = candidate
                    break
        if name is None:
            raise ValueError(f"No loaded subject matches '{subject}'.")

        ids = [s.subject_id for s in self.subjects if s.name == name and (level is None or s.level == level)]
        if not ids:
            raise ValueError(f"{level or ''} {name} is not loaded.".strip())
        return ids

    def list_subjects(self) -> list[dict[str, Any]]:
        return [
            {"subject": s.name, "level": s.level, "code": s.code,
             "topics": len(s.topics), "objectives": len(s.objectives)}
            for s in sorted(self.subjects, key=lambda s: (s.name, s.level))
        ]

    def list_topics(self, subject: str) -> dict[str, Any]:
        ids = self.resolve_subject(subject)
        if not ids:
            raise ValueError("Say which subject, for example 'H2 Physics'.")
        return {
            "subjects": [
                {
                    "subject": self.subject_label(sid),
                    "topics": [
                        {"number": t.number, "name": t.name, "objectives": len(t.learning_objectives)}
                        for t in self.subject_by_id[sid].topics
                    ],
                }
                for sid in ids
            ]
        }

    def subject_label(self, subject_id: str) -> str:
        s = self.subject_by_id[subject_id]
        return f"{s.level} {s.name} ({s.code})"

    # ---- objectives -----------------------------------------------------------

    def objective_card(self, lo: LearningObjective, *, full: bool = True) -> dict[str, Any]:
        card = {
            "objective_id": lo.lo_id,
            "subject": self.subject_label(lo.subject_id),
            "topic": lo.topic_name,
            "title": lo.title,
            "source": f"{lo.source} p.{lo.page}",
        }
        if full:
            card["syllabus_requires"] = list(lo.include) or [lo.statement]
            card["excluded"] = list(lo.exclude)
            if lo.exam_skills:
                card["assessed_by"] = list(lo.exam_skills)
        return card

    def get_objective(self, objective_id: str) -> dict[str, Any]:
        lo = self.by_id.get(objective_id.strip())
        if lo is None:
            raise ValueError(f"No objective with id '{objective_id}'.")
        return self.objective_card(lo)

    def _predicate(self, subject_ids: Iterable[str]):
        ids = set(subject_ids)
        return (lambda item: getattr(item, "subject_id", None) in ids
                or getattr(getattr(item, "objective", None), "subject_id", None) in ids) if ids else None

    def find_objective(self, question: str, subject: str | None = None, top_k: int = 3) -> dict[str, Any]:
        """Which syllabus objective(s) a question belongs to, with a confidence."""
        ids = self.resolve_subject(subject)
        predicate = self._predicate(ids)
        confidence = self.retriever.confidence(question, predicate)
        hits = self.retriever.search(question, top_k=top_k, predicate=predicate)
        return {
            "question": question,
            "searched": [self.subject_label(i) for i in ids] or "all subjects",
            "confidence": round(confidence, 2),
            "match": band(confidence),
            "objectives": [
                self.objective_card(hit.item, full=(rank == 0)) | {"similarity": round(hit.similarity, 2)}
                for rank, hit in enumerate(hits)
            ],
        }

    def check_examinable(self, topic: str, subject: str | None = None) -> dict[str, Any]:
        """Is ``topic`` examinable? Answers from the syllabus's own Include/Exclude lists.

        Verdicts:
          * ``excluded``: an "Excluded" bullet matches the topic, so it is
            explicitly not examinable.
          * ``examinable``: a learning objective covers it confidently.
          * ``unclear``: only an approximate match, often assumed prior
            knowledge rather than an examinable objective.
          * ``not_in_syllabus``: nothing in the loaded syllabus covers it.
        """
        ids = self.resolve_subject(subject)
        predicate = self._predicate(ids)
        confidence = self.retriever.confidence(topic, predicate)
        hits = self.retriever.search(topic, top_k=2, predicate=predicate)

        exclusion_hits = self.exclusion_retriever.search(topic, top_k=3, predicate=predicate)
        # An exclusion only counts inside its own topic: "hypothesis tests" is excluded
        # from correlation (9758.6.6), but hypothesis testing itself (9758.6.5) is taught.
        exclusion_hits = [h for h in exclusion_hits
                          if self.objective_similarity(topic, h.item.objective) >= confidence - PARENT_SLACK]
        best_exclusion = max(exclusion_hits, key=lambda h: h.similarity, default=None)
        exclusion_sim = best_exclusion.similarity if best_exclusion else 0.0
        # Exact wording beats embeddings for short technical terms ("Type II error"
        # embeds poorly on its own). If every content word of the topic appears in
        # an exclusion and in no included bullet, the syllabus has answered it.
        literal = self._literal_exclusion(topic, ids)
        if literal is not None:
            best_exclusion, exclusion_sim = _LiteralHit(literal), 1.0
        inclusion_sim = self.inclusion_retriever.confidence(topic, predicate) if best_exclusion else 0.0

        result: dict[str, Any] = {"topic": topic,
                                  "searched": [self.subject_label(i) for i in ids] or "all subjects",
                                  "confidence": round(confidence, 2)}

        if best_exclusion and exclusion_sim >= EXCLUSION_MIN and exclusion_sim >= inclusion_sim + EXCLUSION_MARGIN:
            lo = best_exclusion.item.objective
            result |= {
                "verdict": "excluded",
                "explanation": f"Listed under 'Excluded' for objective {lo.lo_id}: \"{best_exclusion.item.bullet}\".",
                "excluded_item": best_exclusion.item.bullet,
                "objective": self.objective_card(lo),
            }
        elif hits and confidence >= CONFIDENT:
            result |= {
                "verdict": "examinable",
                "explanation": f"Covered by objective {hits[0].item.lo_id}, {hits[0].item.title}.",
                "objective": self.objective_card(hits[0].item),
            }
        elif hits and confidence >= UNCLEAR_MIN and self._has_keyword_support(hits):
            result |= {
                "verdict": "unclear",
                "explanation": "Only an approximate match. It may be assumed prior knowledge rather than "
                               "an examinable objective.",
                "closest_objective": self.objective_card(hits[0].item, full=False),
            }
        else:
            result |= {
                "verdict": "not_in_syllabus",
                "explanation": "Nothing in the loaded syllabus covers this.",
                "closest_objective": self.objective_card(hits[0].item, full=False) if hits else None,
            }
        return result

    def objective_similarity(self, text: str, lo: LearningObjective) -> float:
        """Cosine similarity between ``text`` and one objective."""
        scores = self.retriever.dense._similarities(text) if self.retriever.dense else None
        if scores is None:
            return 0.0
        return float(scores[self._position[lo.lo_id]])

    def _literal_exclusion(self, topic: str, subject_ids: list[str]) -> "Exclusion | None":
        words = _content_words(topic)
        if not words:
            return None
        in_scope = lambda item: not subject_ids or item.objective.subject_id in subject_ids
        if any(words <= _content_words(inc.text) for inc in self.inclusions if in_scope(inc)):
            return None
        matches = [exc for exc in self.exclusions if in_scope(exc) and words <= _content_words(exc.text)]
        # The shortest clause is the most specific statement of the exclusion.
        return min(matches, key=lambda exc: len(exc.text)) if matches else None

    @staticmethod
    def _has_keyword_support(hits) -> bool:
        """True when some top match shares actual words with the question.

        Off-topic questions phrased in academic language can still reach the
        approximate band on meaning alone ("who won the world cup" scores 0.55),
        but they share no syllabus vocabulary, so the lexical index finds nothing.
        """
        return any("lexical" in hit.signals for hit in hits)

    def pick_quiz_objective(self, subject: str | None, avoid: Iterable[str] = (), prefer: Iterable[str] = ()) -> LearningObjective:
        """An objective to quiz on: the student's weakest one if known, else a fresh one."""
        ids = set(self.resolve_subject(subject))
        pool = [lo for lo in self.objectives if not ids or lo.subject_id in ids]
        for lo_id in prefer:
            lo = self.by_id.get(lo_id)
            if lo is not None and lo in pool:
                return lo
        avoid = set(avoid)
        fresh = [lo for lo in pool if lo.lo_id not in avoid] or pool
        # Deterministic rotation rather than random, so demos and tests are repeatable.
        return fresh[len(avoid) % len(fresh)]


def _seed_cache(cache_folder: Path) -> None:
    """Start from the vectors shipped in data/, so a fresh clone doesn't spend
    minutes embedding ~1,800 syllabus bullets before answering anything."""
    import shutil

    for shipped in (ROOT / "data").glob("embeddings-*.npz"):
        target = cache_folder / shipped.name
        if not target.exists():
            cache_folder.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(shipped, target)


def _keep_queries_in_memory(store, limit: int = 512) -> None:
    """Embed queries without touching the on-disk cache.

    The tutor's store persists every new vector and rewrites its whole ``.npz``
    when it does, which is right for documents but put a ~450 ms disk write in
    front of every new question. Queries are short-lived, so they get a small
    in-memory LRU instead, keeping tool calls well inside Alexa+'s 500 ms budget.
    """
    import numpy as np

    cache: OrderedDict[str, np.ndarray] = OrderedDict()
    prefix = getattr(store.client, "query_prefix", "")

    def embed_query(query: str) -> np.ndarray:
        key = f"{prefix}{query}"
        vector = cache.get(key)
        if vector is None:
            vector = np.asarray(store.client.embed([key])[0], dtype=np.float32)
            cache[key] = vector
            if len(cache) > limit:
                cache.popitem(last=False)
        else:
            cache.move_to_end(key)
        return vector[None, :]

    store.embed_query = embed_query


def _clauses(bullet: str) -> list[str]:
    """Split a packed exclusion bullet into its separate exclusions.

    "the use of the term 'Type I error', concept of Type II error and testing
    the difference between two population means" is three exclusions; matched
    as one sentence, a question about any single one of them scores poorly.
    The full bullet is kept too, and fragments under three words are dropped
    because they lose their meaning out of context.
    """
    parts = [p.strip(" .;") for p in re.split(r",\s+|;\s*|\s+and\s+", bullet)]
    clauses = [p for p in parts if len(p.split()) >= 3]
    whole = bullet.strip(" .")
    return list(dict.fromkeys([whole] + clauses))


@dataclass(frozen=True)
class _LiteralHit:
    """Stands in for a retrieval hit when an exclusion matched word for word."""

    item: Exclusion
    similarity: float = 1.0


_GENERIC = {"need", "know", "learn", "study", "syllabus", "exam", "examinable", "tested", "topic",
            "maths", "math", "mathematics", "physics", "chemistry", "biology", "computing", "economics",
            "geography", "history", "level", "h1", "h2", "about", "what", "does", "will", "do", "is", "are",
            "my", "we", "you", "have", "learnt", "covered", "included", "come", "out"}


def _content_words(text: str) -> frozenset[str]:
    """Content words for literal matching: "Type II errors" and "type 2 error" come out equal."""
    from syllabus_core.syllabus.schema import STOPWORDS

    text = text.lower().replace("’", "'").replace("‘", "'")
    text = re.sub(r"\btype\s+(iii|ii|i)\b", lambda m: "type " + str(len(m.group(1))), text)
    words = []
    for w in re.findall(r"[a-z0-9]+", text):
        if w in STOPWORDS or w in _GENERIC or (len(w) == 1 and not w.isdigit()):
            continue
        words.append(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w)
    return frozenset(words)
