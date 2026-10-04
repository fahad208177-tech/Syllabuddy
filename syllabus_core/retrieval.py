"""Retrieval over learning objectives and documents.

Two signals are combined, because on their own each fails in a way the other
covers:

* **Dense (embeddings)** matches meaning. "How do I test if a coin is fair?"
  should reach the hypothesis-testing objective even though it shares no words
  with it.
* **Lexical (TF-IDF)** matches exact terms. A student asking about "Maclaurin
  series" or "quicksort" wants that precise objective, and an embedding of a
  small model will happily blur it into a neighbouring one.

They are merged with Reciprocal Rank Fusion, which combines *rankings* rather
than scores. That matters here because cosine similarities and TF-IDF scores are
on different, incomparable scales, so averaging them directly would let whichever
signal happens to produce larger numbers dominate.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Protocol, Sequence, TypeVar

import numpy as np

from syllabus_core.embeddings import EmbeddingStore, EmbeddingUnavailable

# RRF's damping constant. 60 is the value from the original paper and keeps any
# single first-place hit from dominating the fused ranking.
RRF_K = 60

TOKEN = re.compile(r"[a-zA-Z0-9_^]+")


class Searchable(Protocol):
    @property
    def searchable_text(self) -> str: ...


ItemT = TypeVar("ItemT", bound=Searchable)


@dataclass(frozen=True)
class Hit(Generic[ItemT]):
    item: ItemT
    score: float
    # Which signals found this, useful when tuning or explaining a match.
    signals: tuple[str, ...] = ()
    # Raw cosine similarity from the dense index, unlike ``score`` which is a
    # fused rank and carries no absolute meaning. This is what tells us whether
    # the match is genuinely good or merely the best of a bad set, so the tutor
    # can admit a question falls outside the syllabus.
    similarity: float = 0.0


# Spelling variants that should count as the same word for keyword matching.
# Applied to syllabus text and questions alike, so both sides always agree.
ORDINALS = {"first": "1st", "second": "2nd", "third": "3rd"}
POSSESSIVE = re.compile(r"['’]s\b")


def _normalise_word(word: str) -> str:
    word = ORDINALS.get(word, word)
    # "newtons" ~ "Newton's" ~ "Newton", "laws" ~ "law"
    if len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    return word


# How a question is framed, not what it is about. "Definition of Newton's third
# law" must not match "...the definition of gravitational field strength".
# ("state" stays: it is also physics, as in "equation of state".)
FRAMING = frozenset({"definition", "define", "defined", "meaning", "mean", "explain", "explanation", "describe"})


def tokenize(text: str) -> list[str]:
    return [_normalise_word(w) for w in TOKEN.findall(POSSESSIVE.sub("", text.lower())) if w not in FRAMING]


class LexicalIndex(Generic[ItemT]):
    """BM25 ranking over the corpus.

    BM25 rather than plain TF-IDF cosine: it saturates term frequency, so a
    chunk that repeats "vector" twenty times does not outrank one that actually
    answers the question, and it normalises for length so short syllabus
    objectives compete fairly against long textbook passages.
    """

    K1 = 1.5
    B = 0.75

    def __init__(self, items: Sequence[ItemT]) -> None:
        self.items = list(items)
        self.total = len(self.items)
        self.lengths: list[int] = []

        # Inverted index: term -> [(document index, term frequency), ...]. Scoring
        # then touches only the documents that contain a query term, instead of
        # scanning the whole corpus once per term.
        self.postings: dict[str, list[tuple[int, int]]] = {}

        for index, item in enumerate(self.items):
            counts = Counter(tokenize(item.searchable_text))
            self.lengths.append(sum(counts.values()))
            for term, frequency in counts.items():
                self.postings.setdefault(term, []).append((index, frequency))

        self.average_length = (sum(self.lengths) / self.total) if self.total else 0.0

    def search(self, query: str, top_k: int) -> list[tuple[int, float]]:
        terms = tokenize(query)
        if not terms or not self.total:
            return []

        scores = np.zeros(self.total, dtype=np.float32)

        for term in set(terms):
            postings = self.postings.get(term)
            if not postings:
                continue
            # Standard BM25 inverse document frequency, smoothed.
            idf = math.log(1 + (self.total - len(postings) + 0.5) / (len(postings) + 0.5))

            for index, frequency in postings:
                length_norm = 1 - self.B + self.B * (
                    self.lengths[index] / self.average_length if self.average_length else 1
                )
                scores[index] += idf * (frequency * (self.K1 + 1)) / (
                    frequency + self.K1 * length_norm
                )

        return _top_indices(scores, top_k)


class DenseIndex(Generic[ItemT]):
    """Cosine similarity over cached embeddings.

    Vectors are L2-normalised once at build time, which turns cosine similarity
    into a single matrix-vector product at query time.
    """

    def __init__(self, items: Sequence[ItemT], store: EmbeddingStore) -> None:
        self.items = list(items)
        self.store = store
        self.matrix: np.ndarray | None = None
        self.error: str | None = None

        if not self.items:
            return

        try:
            vectors = store.embed([item.searchable_text for item in self.items])
            self.matrix = _normalise(vectors)
        except EmbeddingUnavailable as error:
            self.error = str(error)

    @property
    def available(self) -> bool:
        return self.matrix is not None

    def search(self, query: str, top_k: int) -> list[tuple[int, float]]:
        scores = self._similarities(query)
        if scores is None:
            return []
        return _top_indices(scores, top_k)

    def best_similarity(self, query: str, predicate=None) -> float:
        """Highest cosine similarity to ``query``, optionally restricted to
        items matching ``predicate`` -- e.g. a single subject."""
        scores = self._similarities(query)
        if scores is None or scores.size == 0:
            return 0.0
        if predicate is not None:
            mask = np.fromiter((predicate(item) for item in self.items), dtype=bool, count=len(self.items))
            if not mask.any():
                return 0.0
            scores = scores[mask]
        return max(float(scores.max()), 0.0)

    def _similarities(self, query: str) -> np.ndarray | None:
        if self.matrix is None:
            return None
        try:
            query_vector = _normalise(self.store.embed_query(query))[0]
        except EmbeddingUnavailable as error:
            self.error = str(error)
            return None
        return self.matrix @ query_vector


class HybridRetriever(Generic[ItemT]):
    """Dense and lexical search fused by Reciprocal Rank Fusion."""

    def __init__(
        self,
        items: Sequence[ItemT],
        store: EmbeddingStore | None = None,
        candidate_multiplier: int = 4,
    ) -> None:
        self.items = list(items)
        self.lexical = LexicalIndex(self.items)
        self.dense = DenseIndex(self.items, store) if store is not None else None
        self.candidate_multiplier = candidate_multiplier

    @property
    def dense_available(self) -> bool:
        return self.dense is not None and self.dense.available

    @property
    def error(self) -> str | None:
        return self.dense.error if self.dense is not None else None

    def confidence(self, query: str, predicate=None) -> float:
        """How well the corpus covers this question at all, from 0 to 1.

        The best cosine similarity anywhere in the corpus, restricted to
        ``predicate`` when given. Unlike a fused rank, this is comparable
        across queries, so it can distinguish "the syllabus answers this"
        from "this is the closest of 104 objectives, none of which are about
        it".

        ``predicate`` must match whatever filter (e.g. a subject) the caller
        applied to :meth:`search`, or this measures the wrong thing: with 13
        subjects sharing one corpus, a query that scores well against some
        *other* subject can otherwise report high confidence while the
        objective actually shown -- filtered to the subject the student
        selected -- is nothing like it. A student asking a Physics question
        while "Mathematics" is selected should see that mismatch reflected
        here, not a confidence score borrowed from the Physics objective they
        will never be shown.

        It is a hint rather than a verdict: an off-syllabus question phrased in
        academic language still lands around 0.6, so treat a low score as reason
        to warn the student, never as grounds to refuse.
        """
        if self.dense is None or not self.dense.available:
            return 0.0
        return self.dense.best_similarity(query, predicate)

    def search(
        self,
        query: str,
        top_k: int = 5,
        predicate=None,
    ) -> list[Hit[ItemT]]:
        """Return the best ``top_k`` items, optionally filtered by ``predicate``.

        Filtering happens after retrieval over a widened candidate pool, so a
        subject filter cannot empty the result set as long as enough candidates
        of that subject exist.
        """
        if not self.items:
            return []

        pool = max(top_k * self.candidate_multiplier, top_k)
        if predicate is not None:
            # Rank every item: with thousands of objectives across exams, a small
            # subject (H2 Maths has 19) rarely reaches a global shortlist, and
            # filtering afterwards would silently lose its best match.
            pool = len(self.items)
        rankings: list[tuple[str, list[tuple[int, float]]]] = [
            ("lexical", self.lexical.search(query, pool))
        ]
        if self.dense is not None:
            rankings.append(("dense", self.dense.search(query, pool)))

        fused: dict[int, float] = {}
        signals: dict[int, list[str]] = {}
        similarities: dict[int, float] = {}
        for name, ranking in rankings:
            for rank, (index, score) in enumerate(ranking):
                fused[index] = fused.get(index, 0.0) + 1.0 / (RRF_K + rank + 1)
                signals.setdefault(index, []).append(name)
                if name == "dense":
                    similarities[index] = score

        ordered = sorted(fused.items(), key=lambda item: item[1], reverse=True)
        hits: list[Hit[ItemT]] = []
        for index, score in ordered:
            item = self.items[index]
            if predicate is not None and not predicate(item):
                continue
            hits.append(
                Hit(
                    item=item,
                    score=score,
                    signals=tuple(signals[index]),
                    similarity=similarities.get(index, 0.0),
                )
            )
            if len(hits) >= top_k:
                break

        return hits


def _normalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    # Guard against a zero vector, which would otherwise produce NaNs.
    return vectors / np.maximum(norms, 1e-12)


def _top_indices(scores: np.ndarray, top_k: int) -> list[tuple[int, float]]:
    if scores.size == 0:
        return []
    count = min(top_k, scores.size)
    # argpartition finds the top-k without sorting the whole array.
    candidates = np.argpartition(-scores, count - 1)[:count]
    ranked = candidates[np.argsort(-scores[candidates])]
    return [(int(index), float(scores[index])) for index in ranked if scores[index] > 0]


def build_store(
    model: str | None = None,
    cache_folder: str | Path = "cache",
    backend: str | None = None,
) -> EmbeddingStore:
    """Create the embedding store, one cache file per model."""
    from syllabus_core.embeddings import create_client

    client = create_client(backend=backend, model=model)
    safe_name = client.model.replace(":", "-").replace("/", "-")
    return EmbeddingStore(Path(cache_folder) / f"embeddings-{safe_name}.npz", client)
