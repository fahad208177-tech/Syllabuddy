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
                  "start_quiz", "record_quiz_result", "my_revision_list"}


async def _call(url, student, calls):
    async with AsyncExitStack() as stack:
        http = await stack.enter_async_context(create_mcp_http_client(headers={"X-Syllabuddy-Student": student}))
        client = await stack.enter_async_context(Client(streamable_http_client(url, http_client=http)))
        out = []
        for name, args in calls:
            if name == "__list__":
                out.append(await client.list_tools())
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
