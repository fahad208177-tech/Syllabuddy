"""The structured syllabus backbone.

Everything the tutor does hangs off these objects: retrieval matches a question
to a :class:`LearningObjective`, the prompt quotes its ``include``/``exclude``
lists, marking scores an answer against them, and progress tracking records
weaknesses by ``lo_id``.

The hierarchy is deliberately two levels deep (subject -> topic -> objective)
even though the source documents differ, so one schema covers every subject:

* Mathematics 9758 / Further Mathematics 9649 use a "Topic/Sub-topics | Content"
  table, so a numbered topic (``6 Probability and Statistics``) becomes a topic
  and each sub-topic (``6.5 Hypothesis testing``) becomes an objective carrying
  the ``Include:``/``Exclude:`` bullets.
* Computing 9569 lists explicit numbered outcomes, so a unit (``2.3 Implementing
  Algorithms and Data Structures``) becomes a topic and each outcome (``2.3.1``)
  becomes an objective.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Words that carry no retrieval signal. Kept small and syllabus-specific rather
# than pulling in a full NLP stopword list.
STOPWORDS = frozenset(
    """
    a an the and or but of in on at to for from with without by as is are be being
    been it its this that these those such other others including include includes
    included excluding exclude excludes excluded use used using uses their there
    where when which who whom whose what how why not no nor only own same so than
    too very can will just should now also may might must shall each both any all
    some more most one two three both between into through during above below up
    down out off over under again further then once here about against because
    concept concepts idea ideas simple given form forms terms term case cases
    """.split()
)

# Command words that signal what an exam question will actually ask a student to
# do. Extracted from objective statements so the tutor can tell a student whether
# an objective is examined by calculation, by explanation, or by derivation.
COMMAND_VERBS = frozenset(
    """
    define describe explain state list identify give name outline summarise
    understand know recognise recall
    calculate compute evaluate find determine solve derive prove show verify
    estimate approximate simplify express convert
    sketch draw plot construct represent illustrate label
    use apply implement write code trace design develop create
    compare contrast distinguish discuss analyse interpret justify comment
    deduce infer conclude predict
    """.split()
)

# The maths syllabuses phrase content as noun phrases ("interpretation of the
# results", "solving inequalities") rather than as commands, so the verb list
# alone finds nothing there. Mapping the nominalised forms back to their verb
# recovers the exam skill the objective is really describing.
NOMINALISATIONS = {
    "solving": "solve",
    "formulation": "formulate",
    "formulating": "formulate",
    "interpretation": "interpret",
    "interpreting": "interpret",
    "derivation": "derive",
    "deriving": "derive",
    "calculation": "calculate",
    "calculating": "calculate",
    "proof": "prove",
    "sketching": "sketch",
    "graphing": "sketch",
    "finding": "find",
    "evaluation": "evaluate",
    "evaluating": "evaluate",
    "expressing": "express",
    "conversion": "convert",
    "converting": "convert",
    "representation": "represent",
    "representing": "represent",
    "comparison": "compare",
    "comparing": "compare",
    "testing": "test",
    "modelling": "model",
    "simplification": "simplify",
    "implementation": "implement",
    "application": "apply",
    "applying": "apply",
}

WORD = re.compile(r"[A-Za-z][A-Za-z\-']+")


@dataclass(frozen=True)
class LearningObjective:
    """One examinable outcome, the unit the whole tutor is organised around."""

    subject_id: str
    subject_name: str
    topic_id: str
    topic_name: str
    lo_id: str
    number: str
    title: str
    statement: str
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    exam_skills: tuple[str, ...] = ()
    section: str = ""
    source: str = ""
    page: int = 0

    @property
    def searchable_text(self) -> str:
        """Text used to build this objective's embedding.

        Exclusions are deliberately left out: they describe what is *not*
        examinable, and including them would pull the objective towards
        questions it should not match.
        """
        parts = [
            self.subject_name,
            self.topic_name,
            self.title,
            self.statement,
            " ".join(self.include),
            " ".join(self.keywords),
        ]
        return " ".join(part for part in parts if part)

    @property
    def citation(self) -> str:
        return f"{self.subject_name} {self.number} {self.title} ({self.source} p.{self.page})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "lo_id": self.lo_id,
            "number": self.number,
            "title": self.title,
            "statement": self.statement,
            "include": list(self.include),
            "exclude": list(self.exclude),
            "keywords": list(self.keywords),
            "exam_skills": list(self.exam_skills),
            "source": self.source,
            "page": self.page,
        }


@dataclass
class Topic:
    topic_id: str
    number: str
    name: str
    section: str = ""
    # Some syllabuses introduce a topic with a sentence describing what the whole
    # topic covers, which is useful context above the individual objectives.
    statement: str = ""
    learning_objectives: list[LearningObjective] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "number": self.number,
            "name": self.name,
            "section": self.section,
            "statement": self.statement,
            "learning_objectives": [lo.to_dict() for lo in self.learning_objectives],
        }


@dataclass
class Subject:
    subject_id: str
    name: str
    code: str
    level: str
    source: str
    topics: list[Topic] = field(default_factory=list)

    @property
    def objectives(self) -> list[LearningObjective]:
        return [lo for topic in self.topics for lo in topic.learning_objectives]

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "name": self.name,
            "code": self.code,
            "level": self.level,
            "source": self.source,
            "topics": [topic.to_dict() for topic in self.topics],
        }


def derive_keywords(*texts: str, limit: int = 14) -> tuple[str, ...]:
    """Pull content words out of an objective for lexical matching.

    Deliberately simple and deterministic: frequency order, no stemming. These
    supplement the embedding rather than replace it.
    """
    counts: dict[str, int] = {}
    for text in texts:
        for match in WORD.finditer(text.lower()):
            word = match.group()
            if len(word) > 2 and word not in STOPWORDS:
                counts[word] = counts.get(word, 0) + 1

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return tuple(word for word, _count in ranked[:limit])


def derive_exam_skills(*texts: str) -> tuple[str, ...]:
    """Find the command verbs an objective uses, in syllabus order."""
    seen: list[str] = []
    for text in texts:
        for match in WORD.finditer(text.lower()):
            word = NOMINALISATIONS.get(match.group(), match.group())
            if word in COMMAND_VERBS and word not in seen:
                seen.append(word)
    return tuple(seen)
