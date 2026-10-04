"""Syllabus answers, checked against the official documents.

Each expectation below was verified by reading data/syllabus.json, which is
parsed from the SEAB syllabus PDFs. If a threshold change breaks one of these,
the change is wrong, not the test.
"""

import pytest

from syllabus_core.service import SyllabusService, _clauses


@pytest.fixture(scope="module")
def svc():
    return SyllabusService()


@pytest.mark.parametrize("topic, subject, verdict", [
    # 9758.3.3 excludes these explicitly
    ("shortest distance between two skew lines", "H2 Maths", "excluded"),
    ("distance between skew lines", "maths", "excluded"),
    ("common perpendicular of skew lines", "H2 Maths", "excluded"),
    # ...but the neighbouring topics are taught
    ("distance from a point to a plane", "H2 Maths", "examinable"),
    ("distance between two planes", "H2 Maths", "examinable"),
    # 9758.6.5 teaches hypothesis testing; 9758.6.6 only excludes hypothesis tests *on correlation*
    ("hypothesis testing", "H2 Maths", "examinable"),
    # ...and 9758.6.5 packs three exclusions into one bullet
    ("type I error", "H2 Maths", "excluded"),
    ("the Type II error", "H2 Maths", "excluded"),        # short terms embed poorly; matched literally
    ("type 2 errors", "H2 Maths", "excluded"),
    ("skew lines", "H2 Maths", "examinable"),             # included: relationships between two lines (coplanar or skew)
    ("testing the difference between two population means", "H2 Maths", "excluded"),
    ("simple harmonic motion", "H2 Physics", "examinable"),
    ("binary search trees", "Computing", "examinable"),
    ("monopoly pricing", "econs", "examinable"),
    ("photosynthesis", "H2 Biology", "examinable"),
    ("who won the world cup", None, "not_in_syllabus"),
    ("how to bake sourdough", None, "not_in_syllabus"),
])
def test_check_examinable(svc, topic, subject, verdict):
    got = svc.check_examinable(topic, subject)["verdict"]
    assert got == verdict


def test_excluded_answer_quotes_the_syllabus(svc):
    result = svc.check_examinable("shortest distance between two skew lines", "H2 Maths")
    assert result["objective"]["objective_id"] == "9758.3.3"
    assert result["excluded_item"] == "shortest distance between two skew lines"
    assert "H2math.pdf p.8" == result["objective"]["source"]


def test_packed_exclusion_quotes_whole_bullet(svc):
    result = svc.check_examinable("type I error", "H2 Maths")
    assert result["objective"]["objective_id"] == "9758.6.5"
    assert "Type II error" in result["excluded_item"]


@pytest.mark.parametrize("question, subject, expected", [
    ("how to find the distance between two planes", "H2 Maths", "9758.3.3"),
    ("what is simple harmonic motion", "H2 Physics", "9478.9.d"),
    # A user-reported bug: these went to Newton's law of *gravitation* (9478.8.b)
    ("definition of Newton's third law", "H2 Physics", "9478.3.h"),
    ("newtons third law", "H2 Physics", "9478.3.h"),
    ("Newton's law of gravitation", "H2 Physics", "9478.8.a"),
])
def test_find_objective(svc, question, subject, expected):
    result = svc.find_objective(question, subject)
    assert result["objectives"][0]["objective_id"] == expected
    assert result["match"] in ("matched", "approximate")


@pytest.mark.parametrize("text, ids", [
    ("H2 Maths", ["9758"]),
    ("h1 maths", ["8865"]),
    ("9729", ["9729"]),
    ("econs", ["8843", "9570"]),
    ("H2 computing", ["9569"]),
    ("Physics", ["8867", "9478"]),
    ("", []),
    (None, []),
])
def test_resolve_subject(svc, text, ids):
    assert sorted(svc.resolve_subject(text)) == sorted(ids)


def test_unknown_subject_is_an_error(svc):
    with pytest.raises(ValueError):
        svc.resolve_subject("underwater basket weaving")


def test_clauses_split_packed_bullets():
    bullet = "the use of the term ‘Type I error’, concept of Type II error and testing the difference between two population means."
    parts = _clauses(bullet)
    assert parts[0].startswith("the use of the term")
    assert "concept of Type II error" in parts
    assert "testing the difference between two population means" in parts
    assert all(len(p.split()) >= 3 for p in parts)


def test_quiz_prefers_weak_objectives(svc):
    lo = svc.pick_quiz_objective("H2 Physics", avoid=[], prefer=["9478.9.d"])
    assert lo.lo_id == "9478.9.d"
    fresh = svc.pick_quiz_objective("H2 Physics", avoid=["9478.9.d"])
    assert fresh.subject_id == "9478" and fresh.lo_id != "9478.9.d"


def test_content_words_normalise_type_numerals():
    from syllabus_core.service import _content_words

    assert _content_words("Do I need to know the Type II error?") == {"type", "2", "error"}
    assert _content_words("concept of Type II error") == {"type", "2", "error"}


from paraphrases import PARAPHRASES  # noqa: E402


@pytest.mark.parametrize("topic, subject, verdict", PARAPHRASES)
def test_student_paraphrases(svc, topic, subject, verdict):
    assert svc.check_examinable(topic, subject)["verdict"] == verdict


def test_corrections_replace_mangled_bullets(svc):
    exclude = svc.by_id["8865.2.1"].exclude
    assert "use of dy/dx = 1 ÷ (dx/dy)" in exclude
    assert "derivatives of products and quotients of functions" in exclude
    assert not any("Topics/Sub-topics" in e for lo in svc.objectives for e in lo.exclude + lo.include)
