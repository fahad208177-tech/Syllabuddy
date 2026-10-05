"""The simulated Alexa+ agent: tool loop over real MCP, and each brain's plumbing."""

import asyncio
import json

import pytest

from assistant.agent import Assistant, BedrockBrain, BrainReply, OfflineBrain, ToolCall, _clean_for_speech


def collect(assistant, session, student, text):
    async def go():
        return [event async for event in assistant.turn(session, student, text)]
    return asyncio.run(go())


class ScriptedBrain:
    """Calls one tool, then answers using whatever the tool returned."""

    name = "scripted"

    def __init__(self, tool, args):
        self.tool, self.args, self.seen_tools = tool, args, None

    async def chat(self, messages, tools):
        self.seen_tools = [t["name"] for t in tools]
        if messages[-1]["role"] == "tool":
            data = json.loads(messages[-1]["content"])
            return BrainReply(text=f"**Verdict:** {data['verdict']}")
        return BrainReply(tool_calls=[ToolCall("c1", self.tool, self.args)])


def test_agent_loop_runs_tools_over_mcp(server_url):
    brain = ScriptedBrain("check_examinable", {"topic": "shortest distance between two skew lines", "subject": "H2 Maths"})
    events = collect(Assistant(brain, server_url), "s1", "agent-test", "are skew lines examinable?")
    kinds = [e["type"] for e in events]
    assert kinds == ["tool_call", "tool_result", "answer"]
    assert "check_examinable" in brain.seen_tools and "my_revision_list" in brain.seen_tools
    assert events[1]["result"]["verdict"] == "excluded"
    assert events[2]["text"] == "Verdict: excluded"  # markdown stripped for speech


@pytest.mark.parametrize("utterance, tool, verdict", [
    ("Is the shortest distance between two skew lines in the H2 Maths syllabus?", "check_examinable", "excluded"),
    ("Do I need to know simple harmonic motion for H2 Physics?", "check_examinable", "examinable"),
])
def test_offline_brain_end_to_end(server_url, utterance, tool, verdict):
    events = collect(Assistant(OfflineBrain(), server_url), "s2", "offline-test", utterance)
    call = next(e for e in events if e["type"] == "tool_call")
    result = next(e for e in events if e["type"] == "tool_result")
    answer = events[-1]
    assert call["name"] == tool
    assert result["result"]["verdict"] == verdict
    assert answer["type"] == "answer" and len(answer["text"]) > 20


def test_offline_quiz_flow(server_url):
    assistant = Assistant(OfflineBrain(), server_url)
    first = collect(assistant, "quiz", "offline-quiz", "Quiz me on H2 Physics")
    assert first[0]["name"] == "start_quiz" and first[-1]["text"].startswith("Quiz time")
    second = collect(assistant, "quiz", "offline-quiz", "I am not sure")
    assert second[0]["name"] == "record_quiz_result"
    assert second[1]["result"]["stats"]["quizzed"] == 1


def test_unreachable_server_is_reported():
    events = collect(Assistant(OfflineBrain(), "http://127.0.0.1:9/mcp"), "s", "x", "hello")
    assert events[-1]["type"] == "error" and "MCP server" in events[-1]["message"]


# ---- Bedrock, with a stubbed client (no AWS account needed to test the plumbing)

class FakeBedrock:
    def __init__(self):
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return {"output": {"message": {"role": "assistant", "content": [
                {"text": "Let me check."},
                {"toolUse": {"toolUseId": "tu1", "name": "check_examinable",
                             "input": {"topic": "shortest distance between skew lines", "subject": "H2 Maths"}}}]}},
                "stopReason": "tool_use"}
        return {"output": {"message": {"role": "assistant", "content": [{"text": "No, that's excluded."}]}},
                "stopReason": "end_turn"}


def test_bedrock_brain_tool_round_trip(server_url):
    fake = FakeBedrock()
    events = collect(Assistant(BedrockBrain("us.amazon.nova-pro-v1:0", client=fake), server_url),
                     "b", "bedrock-test", "Are skew lines on my H2 Maths exam?")
    assert [e["type"] for e in events] == ["tool_call", "tool_result", "answer"]
    first, second = fake.calls
    assert first["modelId"] == "us.amazon.nova-pro-v1:0"
    assert first["system"][0]["text"].startswith("You are Alexa+")
    specs = {t["toolSpec"]["name"]: t["toolSpec"] for t in first["toolConfig"]["tools"]}
    assert specs["check_examinable"]["inputSchema"]["json"]["type"] == "object"
    # The second call must carry the tool use and its result in Converse's shape.
    assistant_msg, result_msg = second["messages"][-2], second["messages"][-1]
    assert assistant_msg["content"][-1]["toolUse"]["toolUseId"] == "tu1"
    tool_result = result_msg["content"][0]["toolResult"]
    assert result_msg["role"] == "user" and tool_result["toolUseId"] == "tu1"
    assert tool_result["content"][0]["json"]["verdict"] == "excluded"
    assert events[-1]["text"] == "No, that's excluded."


def test_converse_groups_parallel_tool_results():
    history = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "list_subjects", "arguments": "{}"}},
            {"id": "b", "type": "function", "function": {"name": "my_revision_list", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "a", "name": "list_subjects", "content": "{\"subjects\": []}"},
        {"role": "tool", "tool_call_id": "b", "name": "my_revision_list", "content": "{\"revise_first\": []}"},
    ]
    system, messages = BedrockBrain.to_converse(history)
    assert system == [{"text": "sys"}]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert [c["toolResult"]["toolUseId"] for c in messages[-1]["content"]] == ["a", "b"]


def test_speech_cleanup():
    assert _clean_for_speech("**Yes.** It's *examinable*.\n- objective 9758.3.3") == "Yes. It's examinable. objective 9758.3.3"


def test_compact_shrinks_old_tool_results_only():
    from assistant.agent import _compact

    card = {"verdict": "excluded", "objective": {"objective_id": "9758.3.3", "title": "3D vectors",
                                                 "syllabus_requires": ["a long list"] * 5}}
    history = [
        {"role": "tool", "tool_call_id": "orphan", "name": "x", "content": "{}"},   # trimmed window artefact
        {"role": "user", "content": "first"},
        {"role": "tool", "tool_call_id": "a", "name": "check_examinable", "content": json.dumps(card)},
        {"role": "user", "content": "second"},
        {"role": "tool", "tool_call_id": "b", "name": "check_examinable", "content": json.dumps(card)},
    ]
    out = _compact(history)
    assert out[0]["role"] == "user"
    old, new = json.loads(out[1]["content"]), json.loads(out[3]["content"])
    assert old == {"verdict": "excluded", "objective": {"objective_id": "9758.3.3", "title": "3D vectors"}}
    assert new == card


def test_tool_schemas_are_simplified_for_every_model():
    from assistant.agent import _simplify_schema

    raw = {"type": "object", "title": "check_examinableArguments", "properties": {
        "topic": {"title": "Topic", "type": "string"},
        "subject": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Subject"}},
        "required": ["topic"]}
    assert _simplify_schema(raw) == {"type": "object", "properties": {
        "topic": {"type": "string"}, "subject": {"type": "string"}}, "required": ["topic"]}


class BrokenBrain:
    name = "broken"

    async def chat(self, messages, tools):
        raise RuntimeError("429 rate limited")


def test_falls_back_to_syllabus_when_model_fails(server_url):
    events = collect(Assistant(BrokenBrain(), server_url), "fb", "fallback-test",
                     "Is the shortest distance between two skew lines in the H2 Maths syllabus?")
    kinds = [e["type"] for e in events]
    assert kinds[0] == "status" and kinds[-1] == "answer"
    assert next(e for e in events if e["type"] == "tool_result")["result"]["verdict"] == "excluded"
    assert events[-1]["brain"] == "offline"


class SlowBrain:
    name = "slow"

    async def chat(self, messages, tools):
        await asyncio.sleep(30)


def test_turn_deadline_falls_back_instead_of_hanging(server_url, monkeypatch):
    import time as _time

    import assistant.agent as agent

    monkeypatch.setattr(agent, "TURN_DEADLINE", 1.0)
    started = _time.perf_counter()
    events = collect(Assistant(SlowBrain(), server_url), "slow", "slow-test",
                     "Is the shortest distance between two skew lines in the H2 Maths syllabus?")
    assert _time.perf_counter() - started < 15
    assert events[-1]["type"] == "answer" and events[-1]["brain"] == "offline"


@pytest.mark.parametrize("utterance, tool, args", [
    ("Quiz me on 9758.3.3", "start_quiz", {"objective_id": "9758.3.3"}),
    ("What does 9758.3.3 require?", "get_objective", {"objective_id": "9758.3.3"}),
    ("Is anything excluded from 9478.9.d?", "get_objective", {"objective_id": "9478.9.d"}),
    ("Quiz me again", "start_quiz", {}),
])
def test_offline_brain_understands_follow_up_chips(utterance, tool, args):
    reply = asyncio.run(OfflineBrain().chat([{"role": "user", "content": utterance}], []))
    assert reply.tool_calls[0].name == tool and reply.tool_calls[0].arguments == args


def test_offline_get_objective_speech(server_url):
    events = collect(Assistant(OfflineBrain(), server_url), "go", "go-test", "What does 9758.3.3 require?")
    assert events[-1]["text"].startswith("Objective 9758.3.3") and "skew" in events[-1]["text"]


def test_offline_brain_saves_courses_with_exam_date():
    reply = asyncio.run(OfflineBrain().chat(
        [{"role": "user", "content": "I'm taking AP Calc BC and the SAT, my exam is May 11"}], []))
    [call] = reply.tool_calls
    assert call.name == "set_my_courses"
    assert call.arguments["courses"] == ["AP Calc BC", "SAT"]
    assert call.arguments["exam_date"].endswith("-05-11")


def test_offline_sat_question_end_to_end(server_url):
    events = collect(Assistant(OfflineBrain(), server_url), "sat", "sat-test", "Are circles on the PSAT 8/9?")
    result = next(e for e in events if e["type"] == "tool_result")["result"]
    assert result["verdict"] == "excluded"
    assert "not examinable" in events[-1]["text"] or "excluded" in events[-1]["text"]


def test_saved_courses_flow_end_to_end(server_url):
    assistant = Assistant(OfflineBrain(), server_url)
    first = collect(assistant, "courses", "courses-test", "I'm doing the PSAT 8/9, my exam is Oct 15")
    assert "PSAT 8/9 Math" in first[-1]["text"] and "days" in first[-1]["text"]
    later = collect(assistant, "courses", "courses-test", "What should I revise?")
    assert "days" in later[-1]["text"]


@pytest.mark.parametrize("utterance, args", [
    # Two subject names: the exam is the one after "on the", the other is the topic.
    ("Is calculus on the SAT?", {"topic": "calculus", "subject": "SAT"}),
    ("Is multiplying matrices on the ACT?", {"topic": "multiplying matrices", "subject": "ACT"}),
    ("Is the ratio test on the AP Calculus AB exam?", {"topic": "ratio test", "subject": "AP Calculus AB"}),
])
def test_offline_brain_finds_the_exam_and_the_topic(utterance, args):
    reply = asyncio.run(OfflineBrain().chat([{"role": "user", "content": utterance}], []))
    assert reply.tool_calls[0].name == "check_examinable" and reply.tool_calls[0].arguments == args


def test_stalled_tool_call_cannot_stretch_a_turn(server_url, monkeypatch):
    import assistant.agent as agent_module
    from mcp import Client

    async def stalled(self, *args, **kwargs):
        await asyncio.sleep(120)

    monkeypatch.setattr(agent_module, "TURN_DEADLINE", 1.0)
    monkeypatch.setattr(agent_module, "TOOL_TIMEOUT", 2.0)
    monkeypatch.setattr(Client, "call_tool", stalled)
    brain = ScriptedBrain("check_examinable", {"topic": "skew lines", "subject": "H2 Maths"})
    import time as _time
    started = _time.perf_counter()
    events = collect(Assistant(brain, server_url), "stall", "stall-test", "are skew lines examinable?")
    assert _time.perf_counter() - started < 20
    assert "too long" in events[1]["result"]["error"]


def test_speech_cleanup_drops_a_draft_repeated_in_the_same_message():
    # A real gpt-oss reply: a draft and the final answer, run together.
    raw = ("Focus first on limits and continuity in AP Calculus BC, especially the objective CALCBC-1.1 about "
           "instantaneous change.Your weakest area right now is limits and continuity in AP Calculus BC, start with "
           "objective CALCBC-1.1 on instantaneous change before moving on to the other topics.")
    assert _clean_for_speech(raw).startswith("Your weakest area right now")
    # Ordinary multi-sentence answers are untouched.
    normal = "No. The ratio test is BC only. It is topic 10.8 of AP Calculus BC, under infinite sequences and series."
    assert _clean_for_speech(normal) == normal
