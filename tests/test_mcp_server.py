"""End-to-end over the wire: a real MCP client talking Streamable HTTP to the server."""

import asyncio
import time
from contextlib import AsyncExitStack

import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from assistant.agent import _result_data

EXPECTED_TOOLS = {"check_examinable", "find_objective", "get_objective", "list_subjects", "list_topics",
                  "start_quiz", "record_quiz_result", "my_revision_list", "clear_my_history", "set_my_courses"}


async def _call(url, student, calls):
    async with AsyncExitStack() as stack:
        http = await stack.enter_async_context(create_mcp_http_client(headers={"X-Syllabuddy-Student": student}))
        client = await stack.enter_async_context(Client(streamable_http_client(url, http_client=http)))
        out = []
        for name, args in calls:
            if name == "__list__":
                out.append(await client.list_tools())
            elif name == "__read__":
                out.append(await client.read_resource(args))
            elif name == "__resources__":
                out.append((await client.list_resources(), await client.list_resource_templates(), await client.list_prompts()))
            elif name == "__prompt__":
                out.append(await client.get_prompt(*args))
            else:
                t = time.perf_counter()
                result = await client.call_tool(name, args)
                out.append((_result_data(result), (time.perf_counter() - t) * 1000))
        return out


def run(coro):
    return asyncio.run(coro)


def test_lists_all_tools_with_descriptions(server_url):
    [listed] = run(_call(server_url, "t1", [("__list__", None)]))
    names = {t.name for t in listed.tools}
    assert names == EXPECTED_TOOLS
    for tool in listed.tools:
        assert len(tool.description or "") > 40, tool.name
        props = (tool.input_schema if hasattr(tool, "input_schema") else tool.inputSchema).get("properties", {})
        assert "ctx" not in props, f"{tool.name} leaks the Context parameter into its schema"


def test_check_examinable_over_mcp(server_url):
    # Warm the query path once, then measure: Alexa+ needs < 500 ms round trips.
    (_, _), (result, ms) = run(_call(server_url, "t2", [
        ("check_examinable", {"topic": "warm up the model", "subject": "H2 Maths"}),
        ("check_examinable", {"topic": "shortest distance between two skew lines", "subject": "H2 Maths"}),
    ]))
    assert result["verdict"] == "excluded"
    assert result["objective"]["objective_id"] == "9758.3.3"
    print(f"check_examinable round trip: {ms:.0f} ms")


def test_bad_subject_is_a_friendly_error(server_url):
    [(result, _)] = run(_call(server_url, "t3", [("check_examinable", {"topic": "x", "subject": "basket weaving"})]))
    assert "error" in result


def test_history_is_per_student(server_url):
    run(_call(server_url, "alice", [
        ("start_quiz", {"objective_id": "9478.9.d"}),
        ("record_quiz_result", {"objective_id": "9478.9.d", "correct": False, "note": "forgot the minus sign"}),
    ]))
    [(alice, _)] = run(_call(server_url, "alice", [("my_revision_list", {})]))
    [(bob, _)] = run(_call(server_url, "bob", [("my_revision_list", {})]))
    assert alice["revise_first"][0]["objective_id"] == "9478.9.d"
    assert alice["stats"] == {"asked": 0, "quizzed": 1, "right": 0}
    assert bob["revise_first"] == [] and bob["stats"]["quizzed"] == 0


def test_quiz_comes_back_to_weak_spot(server_url):
    [(quiz, _)] = run(_call(server_url, "alice", [("start_quiz", {"subject": "H2 Physics"})]))
    assert quiz["quiz_objective"]["objective_id"] == "9478.9.d"


def test_clear_history_is_confirmed_by_the_server(server_url):
    run(_call(server_url, "carol", [("record_quiz_result", {"objective_id": "9478.9.d", "correct": False})]))
    # A model that "confirms" on its own, twice in a row, deletes nothing.
    [(first, _), (second, _)] = run(_call(server_url, "carol", [("clear_my_history", {"confirm": True}),
                                                               ("clear_my_history", {"confirm": True})]))
    assert first["deleted"] is False and first["needs_confirmation"] is True
    assert first["stats"]["quizzed"] == 1
    assert second["deleted"] is False
    time.sleep(3.2)  # the student answers
    [(done, _), (after, _)] = run(_call(server_url, "carol", [("clear_my_history", {"confirm": True}),
                                                             ("my_revision_list", {})]))
    assert done["deleted"] is True and after["stats"] == {"asked": 0, "quizzed": 0, "right": 0}


def test_clear_history_can_be_cancelled(server_url):
    run(_call(server_url, "dave", [("record_quiz_result", {"objective_id": "9478.9.d", "correct": True})]))
    [(armed, _), (cancelled, _)] = run(_call(server_url, "dave", [("clear_my_history", {}),
                                                                  ("clear_my_history", {"confirm": False})]))
    assert armed["needs_confirmation"] and cancelled["cancelled"]
    [(after, _)] = run(_call(server_url, "dave", [("my_revision_list", {})]))
    assert after["stats"]["quizzed"] == 1


def test_saved_courses_scope_questions_and_track_progress(server_url):
    (saved, _), (plain, _), (revision, _) = run(_call(server_url, "carol", [
        ("set_my_courses", {"courses": ["PSAT 8/9"], "exam_date": "2099-10-15"}),
        # no subject: the saved course is used, where circles are left out
        ("check_examinable", {"topic": "circles"}),
        ("my_revision_list", {}),
    ]))
    assert saved["courses"] == ["PSAT 8/9 Math (PSAT89M)"] and saved["days_to_exam"] > 0
    assert plain["verdict"] == "excluded"
    [course] = revision["my_courses"]
    assert course["objectives"] > 10 and len(course["not_started"]) == 3
    assert revision["days_to_exam"] == saved["days_to_exam"]


def test_set_my_courses_rejects_unknown_courses(server_url):
    [(result, _)] = run(_call(server_url, "dave", [("set_my_courses", {"courses": ["basket weaving"]})]))
    assert "error" in result


def test_resources_and_prompts(server_url):
    [(resources, templates, prompts), objective] = run(_call(server_url, "erin", [
        ("__resources__", None), ("__read__", "syllabus://objective/CALCBC-10.8")]))
    assert "syllabus://subjects" in {str(r.uri) for r in resources.resources}
    assert {t.uri_template if hasattr(t, "uri_template") else t.uriTemplate for t in templates.resource_templates} >= {
        "syllabus://subject/{subject_id}", "syllabus://objective/{objective_id}"}
    assert {p.name for p in prompts.prompts} >= {"revision_plan", "is_it_on_my_exam"}
    assert "CALCBC-10.8" in objective.contents[0].text
    [plan] = run(_call(server_url, "erin", [("__prompt__", ("revision_plan", {"subject": "SAT math", "days": "5"}))]))
    assert "5-day" in plan.messages[0].content.text


def test_past_exam_date_means_the_next_one(server_url):
    # "May 11" said in October, or a model that assumed last year: the next May 11
    [(saved, _)] = run(_call(server_url, "frank", [("set_my_courses", {"courses": ["SAT"], "exam_date": "2020-05-11"})]))
    assert saved["exam_date"].endswith("-05-11") and 0 <= saved["days_to_exam"] <= 366


def test_revision_list_puts_saved_courses_first(server_url):
    run(_call(server_url, "gina", [
        ("check_examinable", {"topic": "multiplying matrices", "subject": "ACT math"}),
        ("check_examinable", {"topic": "multiplying matrices", "subject": "ACT math"}),
        ("check_examinable", {"topic": "equation of a circle", "subject": "SAT math"}),
        ("set_my_courses", {"courses": ["SAT"]}),
    ]))
    [(revision, _)] = run(_call(server_url, "gina", [("my_revision_list", {})]))
    # Asked about ACT twice, but the student is taking the SAT: that comes first.
    assert revision["revise_first"][0]["objective_id"].startswith("SATM")
