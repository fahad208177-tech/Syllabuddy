"""US (College Board AP) and Canada (Alberta Diploma) syllabuses.

Expected answers come from the official documents: the AP Calculus AB and BC
CED marks content "bc only" and has exclusion statements (epsilon-delta limits);
AP CS Principles excludes formal Big-O analysis; Alberta Physics 30 General
Outcome A1 is momentum and impulse.
"""

import pytest

from syllabus_core.service import SyllabusService


@pytest.fixture(scope="module")
def svc():
    return SyllabusService()


@pytest.mark.parametrize("text, ids", [
    ("AP Calc AB", ["CALCAB"]),
    ("ap calculus bc", ["CALCBC"]),
    ("calculus", ["CALCAB", "CALCBC"]),
    ("APUSH", ["USHIST"]),
    ("AP Chem", ["CHEM"]),
    ("chem", ["8873", "9729"]),            # no "AP": the Singapore A-Level
    ("AP Physics 1", ["PHYS1"]),
    ("Physics C E&M", ["PHYSCE"]),
    ("stats", ["STAT"]),
    ("AP CSA", ["CSA"]),
    ("computer science principles", ["CSP"]),
    ("macro", ["MACRO"]),
    ("Physics 30", ["PHYS30"]),
    ("Alberta chemistry", ["CHEM30"]),
    ("H2 Physics", ["9478"]),
    ("CALCBC", ["CALCBC"]),
])
def test_resolve_us_canada_subjects(svc, text, ids):
    assert sorted(svc.resolve_subject(text)) == sorted(ids)


@pytest.mark.parametrize("topic, subject, verdict", [
    # "bc only" in the CED: excluded from AB, examinable in BC
    ("ratio test", "AP Calculus AB", "excluded"),
    ("ratio test for convergence", "AP Calculus BC", "examinable"),
    ("integration by parts", "AP Calc AB", "excluded"),
    ("integration by parts", "AP Calc BC", "examinable"),
    # an exclusion statement in both
    ("epsilon-delta definition of a limit", "AP Calculus BC", "excluded"),
    ("epsilon-delta definition of a limit", "AP Calculus AB", "excluded"),
    ("estimating limits from graphs", "AP Calculus AB", "examinable"),
    # CS Principles exclusion statements
    ("formal analysis of algorithms using Big-O", "AP CSP", "excluded"),
    ("linked lists", "AP Computer Science Principles", "excluded"),
    ("binary search", "AP CSP", "examinable"),
    ("momentum and impulse", "Physics 30", "examinable"),
])
def test_examinable_us_canada(svc, topic, subject, verdict):
    assert svc.check_examinable(topic, subject)["verdict"] == verdict


@pytest.mark.parametrize("question, subject, expected", [
    ("binary search", "AP CSP", "CSP-3.11"),
    ("conservation of momentum in collisions", "Physics 30", "PHYS30-A1"),
    ("photoelectric effect", "Physics 30", "PHYS30-C2"),   # Unit C: Electromagnetic Radiation
    ("electrochemical cells and redox reactions", "Chemistry 30", "CHEM30-B"),
])
def test_find_objective_us_canada(svc, question, subject, expected):
    top = svc.find_objective(question, subject)["objectives"][0]["objective_id"]
    assert top.startswith(expected)


def test_ab_bc_only_list_cites_the_topic(svc):
    result = svc.check_examinable("ratio test", "AP Calculus AB")
    assert result["objective"]["objective_id"] == "CALCAB-BC"
    assert "Ratio Test" in result["excluded_item"] and "BC only" in result["excluded_item"]


def test_every_exam_is_loaded(svc):
    levels = {s.level for s in svc.subjects}
    assert {"AP", "Alberta Diploma", "H1", "H2"} <= levels
    assert sum(1 for s in svc.subjects if s.level == "AP") == 24


@pytest.mark.parametrize("topic, subject, verdict", [
    # Found live: the CSP CED excludes "formal analysis of algorithms (Big-O)"
    ("Big-O notation", "AP Computer Science Principles", "excluded"),
    ("big data", "AP CSP", "examinable"),
    ("algorithmic efficiency", "AP CSP", "examinable"),
])
def test_distinctive_terms(svc, topic, subject, verdict):
    assert svc.check_examinable(topic, subject)["verdict"] == verdict


# ---- Digital SAT Suite (College Board assessment framework, Appendix B) ----

@pytest.mark.parametrize("text, ids", [
    ("SAT", ["SATM", "SATRW"]),
    ("digital SAT", ["SATM", "SATRW"]),
    ("SAT math", ["SATM"]),
    ("SAT reading and writing", ["SATRW"]),
    ("PSAT/NMSQT", ["SATM", "SATRW"]),     # the PSAT/NMSQT tests the SAT's skills
    ("PSAT 8/9", ["PSAT89M"]),
    ("psat 8/9 reading", ["SATRW"]),
])
def test_resolve_sat(svc, text, ids):
    assert sorted(svc.resolve_subject(text)) == sorted(ids)


@pytest.mark.parametrize("topic, subject, verdict", [
    # The SAT stops before calculus, matrices and logarithms
    ("calculus", "SAT", "not_in_syllabus"),
    ("matrices", "SAT math", "not_in_syllabus"),
    ("logarithms", "SAT math", "not_in_syllabus"),
    ("who won the world cup", "SAT", "not_in_syllabus"),
    # PSAT 8/9 leaves out circles, margin of error, trig ratios and exponential models
    ("circles", "PSAT 8/9", "excluded"),
    ("equation of a circle", "SAT math", "examinable"),
    ("margin of error", "PSAT 8/9", "excluded"),
    ("sine and cosine of complementary angles", "PSAT 8/9", "excluded"),
    ("sine and cosine of complementary angles", "SAT math", "examinable"),
    ("special right triangles", "PSAT 8/9", "excluded"),
    ("the Pythagorean theorem", "PSAT 8/9", "examinable"),
    ("quadratic formula", "PSAT 8/9", "examinable"),
    # Reading and Writing skills
    ("subject verb agreement", "SAT", "examinable"),
    ("vocabulary in context", "SAT", "examinable"),
    ("transition words", "SAT", "examinable"),
])
def test_examinable_sat(svc, topic, subject, verdict):
    assert svc.check_examinable(topic, subject)["verdict"] == verdict


def test_sat_cites_the_skill(svc):
    result = svc.check_examinable("sine and cosine of complementary angles", "PSAT 8/9")
    assert result["objective"]["objective_id"] == "PSAT89M-4.3"
    assert "not PSAT 8/9" in result["excluded_item"]



# ---- ACT (College and Career Readiness Standards) ----

@pytest.mark.parametrize("text, ids", [
    ("ACT", ["ACTE", "ACTM", "ACTR", "ACTS"]),
    ("ACT math", ["ACTM"]),
    ("act science", ["ACTS"]),
])
def test_resolve_act(svc, text, ids):
    assert sorted(svc.resolve_subject(text)) == sorted(ids)


@pytest.mark.parametrize("topic, subject, verdict", [
    ("multiplying matrices", "ACT math", "examinable"),
    ("complex numbers", "ACT math", "examinable"),     # on the ACT, unlike the SAT
    ("derivatives", "ACT math", "not_in_syllabus"),
    ("logarithms", "ACT math", "examinable"),
    ("vertical asymptotes", "ACT math", "examinable"),
    ("semicolons", "ACT English", "examinable"),
    ("who won the world cup", "ACT", "not_in_syllabus"),
])
def test_examinable_act(svc, topic, subject, verdict):
    assert svc.check_examinable(topic, subject)["verdict"] == verdict


def test_act_cites_the_score_band(svc):
    result = svc.check_examinable("multiplying matrices", "ACT math")
    assert result["objective"]["objective_id"] == "ACTM-1.705"   # N 705: Multiply matrices
    assert "33–36" in result["objective"]["topic"]


def test_word_the_syllabus_never_uses_is_not_covered(svc):
    # ACT Math is full of "functions" but never mentions limits.
    assert svc.check_examinable("limits of functions", "ACT math")["verdict"] != "examinable"
