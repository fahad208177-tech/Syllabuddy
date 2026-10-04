"""The simulated Alexa+ agent: a language model that uses Syllabuddy through MCP.

This plays the part Alexa+ plays in production. Each turn it connects to the
Syllabuddy MCP server over Streamable HTTP as a real MCP client, discovers the
tools, lets a model decide which to call, executes those calls over MCP, and
turns the results into a short spoken reply.

The model ("brain") is swappable:

* ``bedrock``  Amazon Bedrock Converse API (default when AWS credentials exist)
* ``openai``   any OpenAI-compatible chat API: Groq, Ollama, OpenRouter...
* ``offline``  no model at all: a small intent router with spoken templates,
               so the demo still works with no keys and no internet
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

import httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

MCP_URL = os.environ.get("SYLLABUDDY_MCP_URL", "http://127.0.0.1:8765/mcp")
MAX_TOOL_ROUNDS = 4
MAX_RETRY_WAIT = float(os.environ.get("SYLLABUDDY_MAX_RETRY_WAIT", "12"))
# A voice turn must never hang: one slow model call times out, and a whole turn
# that runs long finishes from the syllabus via the fallback brain.
MODEL_TIMEOUT = float(os.environ.get("SYLLABUDDY_MODEL_TIMEOUT", "20"))
TURN_DEADLINE = float(os.environ.get("SYLLABUDDY_TURN_DEADLINE", "40"))
MAX_HISTORY = 12

SYSTEM_PROMPT = """\
You are Alexa+, speaking through a smart speaker with a screen. The student has enabled the \
Syllabuddy add-on, which knows official exam syllabuses: the US College Board AP courses \
(Calculus AB/BC, Physics, Chemistry, Biology, Statistics, CS, History, Government, Economics...), \
the Canadian Alberta Diploma courses (Physics 30, Chemistry 30) and the Singapore-Cambridge A-Level (H1/H2).

How to answer:
- Replies are spoken aloud: one to three short, natural sentences. No markdown, no lists, no emojis.
- Say formulas in words ("a equals minus omega squared x"), never as symbols; the screen shows the syllabus card.
- For anything about the syllabus, the exam, what to study, topics, quizzes or revision, call a \
Syllabuddy tool first. Never guess what is examinable.
- Mention the objective id when you have one, for example "objective 9758.3.3" or, for AP, \
"topic 10.8 of AP Calculus BC" (id CALCBC-10.8), so the student can check it.
- Pass the subject the way the student said it ("AP Calc AB", "APUSH", "H2 Maths"); the tools understand both exams.
- If check_examinable says "excluded", say clearly that it is not examinable and quote the syllabus \
wording briefly. If it says "unclear" or "not_in_syllabus", say that honestly.
- When explaining a concept, keep to what the syllabus requires; offer more detail rather than giving it all.
- Quizzes: call start_quiz, then ask exactly one short question that can be answered out loud in a sentence or two (never ask for code, a diagram or working on paper), and stop. \
When the student answers, judge it against syllabus_requires, tell them if they were right with a \
one-line correction if needed, and call record_quiz_result.
- "What should I revise?" or "how am I doing?": call my_revision_list.
- If the student doesn't say which exam, ask once, or search all subjects."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class BrainReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class Brain(Protocol):
    name: str

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> BrainReply: ...


# ---- brains -------------------------------------------------------------------------

class OpenAICompatibleBrain:
    """Any OpenAI-style /chat/completions endpoint with tool calling."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.name = f"openai:{model}"
        self.reasoning_effort = os.environ.get("SYLLABUDDY_LLM_REASONING")  # e.g. "low" for gpt-oss

    async def chat(self, messages, tools) -> BrainReply:
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": [{"type": "function", "function": t} for t in tools],
            "tool_choice": "auto",
            "temperature": 0.2,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        waited = 0.0
        async with httpx.AsyncClient(timeout=MODEL_TIMEOUT) as http:
            while True:
                response = await http.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
                delay = _retry_after(response)
                # Free tiers rate-limit by tokens per minute. Wait as asked, but never so
                # long that a voice turn feels frozen; past that, the agent falls back.
                if response.status_code not in (429, 500, 502, 503) or waited + delay > MAX_RETRY_WAIT:
                    break
                await asyncio.sleep(delay)
                waited += delay
        if response.status_code >= 400:
            raise RuntimeError(f"{self.name} returned {response.status_code}: {response.text[:300]}")
        message = response.json()["choices"][0]["message"]
        calls = []
        for raw in message.get("tool_calls") or []:
            try:
                args = json.loads(raw["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(raw.get("id") or uuid.uuid4().hex[:12], raw["function"]["name"], args))
        return BrainReply(text=(message.get("content") or "").strip(), tool_calls=calls)


class BedrockBrain:
    """Amazon Bedrock through the Converse API, which handles tool use natively."""

    def __init__(self, model_id: str, region: str | None = None, client: Any = None) -> None:
        self.model_id = model_id
        self.name = f"bedrock:{model_id}"
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client("bedrock-runtime", region_name=region or os.environ.get("AWS_REGION", "us-east-1"),
                                  config=Config(retries={"mode": "adaptive", "max_attempts": 6}))
        self.client = client

    @staticmethod
    def to_converse(messages: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
        """Translate our OpenAI-style history into Converse's system + messages."""
        system = [{"text": m["content"]} for m in messages if m["role"] == "system"]
        out: list[dict] = []
        for m in messages:
            role = m["role"]
            if role == "system":
                continue
            if role == "tool":
                block = {"toolResult": {"toolUseId": m["tool_call_id"], "content": [{"json": _as_json(m["content"])}]}}
                # Converse wants every tool result for one turn inside a single user message.
                if out and out[-1]["role"] == "user" and all("toolResult" in c for c in out[-1]["content"]):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
                continue
            content: list[dict] = []
            if m.get("content"):
                content.append({"text": m["content"]})
            for call in m.get("tool_calls") or []:
                content.append({"toolUse": {"toolUseId": call["id"], "name": call["function"]["name"],
                                            "input": json.loads(call["function"]["arguments"] or "{}")}})
            out.append({"role": role, "content": content})
        return system, out

    async def chat(self, messages, tools) -> BrainReply:
        system, converse_messages = self.to_converse(messages)
        tool_config = {"tools": [{"toolSpec": {"name": t["name"], "description": t["description"],
                                               "inputSchema": {"json": t["parameters"]}}} for t in tools]}

        def call():
            return self.client.converse(modelId=self.model_id, system=system, messages=converse_messages,
                                        toolConfig=tool_config, inferenceConfig={"temperature": 0.2, "maxTokens": 600})

        response = await asyncio.to_thread(call)
        reply = BrainReply()
        for block in response["output"]["message"]["content"]:
            if "text" in block:
                reply.text += block["text"]
            elif "toolUse" in block:
                use = block["toolUse"]
                reply.tool_calls.append(ToolCall(use["toolUseId"], use["name"], use.get("input") or {}))
        reply.text = reply.text.strip()
        return reply


class OfflineBrain:
    """No model, no network: route by intent and speak from templates.

    Deliberately simple. It exists so anyone can run the demo without an API
    key, and so the MCP side can be tested end to end deterministically.
    """

    name = "offline"
    QUIZ = re.compile(r"\b(quiz|test me|ask me)\b", re.I)
    # Singapore "9758.3.3" or AP "CALCAB-10.8" / "CSP-3.11" / "CALCAB-BC"
    OBJECTIVE_ID = re.compile(r"\b(?:\d{4}(?:\.[0-9a-z]+)+|[A-Z][A-Z0-9]{1,7}-(?:\d+(?:\.\d+)*|BC))\b")
    REVISE = re.compile(r"\b(revise|revision|weak|how am i doing|struggl)", re.I)
    EXAMINABLE = re.compile(r"\b(syllabus|examinable|on (the|my) ([\w.&:-]+\s+){0,4}exam|tested|assessed|"
                            r"need to (know|study|learn)|come out|on (apush|the ap\b))", re.I)
    SUBJECT = re.compile(
        # AP course names first (they are more specific), then the Singapore A-Level subjects.
        r"\b((?:ap\s+)?(?:calc(?:ulus)?(?:\s*(?:ab|bc))?|precalc(?:ulus)?|stat(?:istic)?s|psych(?:ology)?|"
        r"macro(?:economics)?|micro(?:economics)?|apush|(?:us|u\.s\.|world|european)\s+history|"
        r"human\s+geography|physics\s*(?:1|2|c|30)|chem(?:istry)?\s*30|computer\s+science\s*(?:a|principles)|csa|csp|"
        r"environmental\s+science|(?:us|u\.s\.|comparative)\s+government|music\s+theory)"
        r"|ap\s+(?:bio(?:logy)?|chem(?:istry)?|physics)"
        r"|(?:h[12]\s+)?(?:maths?|mathematics|physics|chem(?:istry)?|bio(?:logy)?|computing|"
        r"econs?|economics|geog(?:raphy)?|history))\b", re.I)
    FILLER = re.compile(r"^(alexa,?\s*)?(is|are|do i need to know|does|will)\s+|\b(in|on|for)\s+(the|my)\s+"
                        r"(syllabus|exam|a.?levels?)\b|\b(examinable|in the syllabus|on the exam|tested)\b|[?.!]", re.I)

    def __init__(self) -> None:
        self.pending_quiz: dict[str, Any] | None = None

    async def chat(self, messages, tools) -> BrainReply:
        last = messages[-1]
        if last["role"] == "tool":
            return BrainReply(text=self._speak(last["name"], _as_json(last["content"])))
        text = last["content"]
        subject_match = self.SUBJECT.search(text)
        subject = subject_match.group(1) if subject_match else None
        call_id = uuid.uuid4().hex[:12]
        if self.pending_quiz is not None:
            quiz, self.pending_quiz = self.pending_quiz, None
            correct = _overlap(text, " ".join(quiz["syllabus_requires"])) >= 0.25
            return BrainReply(tool_calls=[ToolCall(call_id, "record_quiz_result",
                                                   {"objective_id": quiz["objective_id"], "correct": correct})])
        objective = self.OBJECTIVE_ID.search(text)
        if self.QUIZ.search(text):
            args = {"objective_id": objective.group(0)} if objective else ({"subject": subject} if subject else {})
            return BrainReply(tool_calls=[ToolCall(call_id, "start_quiz", args)])
        if objective:
            return BrainReply(tool_calls=[ToolCall(call_id, "get_objective", {"objective_id": objective.group(0)})])
        if self.REVISE.search(text):
            return BrainReply(tool_calls=[ToolCall(call_id, "my_revision_list", {})])
        # Strip the question framing and the subject, twice: removing "AP Calculus AB"
        # from "on the AP Calculus AB exam" leaves "on the exam" to remove next.
        topic = re.sub(r"\s+", " ", self.SUBJECT.sub(" ", self.FILLER.sub(" ", text)))
        topic = re.sub(r"\s+", " ", self.FILLER.sub(" ", topic)).strip(" ,")
        topic = re.sub(r"^(the|a|an)\s+|\s+(for|in|on|of|the)$", "", topic, flags=re.I).strip() or text
        args = {"subject": subject} if subject else {}
        if self.EXAMINABLE.search(text):
            return BrainReply(tool_calls=[ToolCall(call_id, "check_examinable", {"topic": topic, **args})])
        return BrainReply(tool_calls=[ToolCall(call_id, "find_objective", {"question": text, **args})])

    def _speak(self, tool: str, result: dict[str, Any]) -> str:
        if "error" in result:
            return f"Sorry, {result['error']}"
        if tool == "check_examinable":
            verdict = result.get("verdict")
            if verdict == "excluded":
                o = result["objective"]
                return (f"No. That's excluded from the {o['subject']} syllabus. Objective {o['objective_id']} lists "
                        f"\"{result['excluded_item']}\" as not examinable.")
            if verdict == "examinable":
                o = result["objective"]
                return f"Yes, it's examinable. It's covered by objective {o['objective_id']}, {o['title']}."
            if verdict == "unclear":
                o = result["closest_objective"]
                return (f"I'm not sure. The closest objective is {o['objective_id']}, {o['title']}, but it may be "
                        f"assumed knowledge rather than something you're examined on.")
            return "I couldn't find that anywhere in your syllabus, so it's probably not examinable."
        if tool == "find_objective":
            if not result.get("objectives"):
                return "I couldn't match that to the syllabus."
            o = result["objectives"][0]
            lead = "That's" if result["match"] == "matched" else "That's probably"
            return f"{lead} objective {o['objective_id']} in {o['subject']}: {o['title']}."
        if tool == "start_quiz":
            o = result["quiz_objective"]
            self.pending_quiz = o
            return f"Quiz time, from {o['subject']}. In your own words: {o['syllabus_requires'][0]}?"
        if tool == "record_quiz_result":
            s = result.get("stats", {})
            return f"Noted. You've got {s.get('right', 0)} out of {s.get('quizzed', 0)} quiz questions right so far."
        if tool == "my_revision_list":
            items = result.get("revise_first") or []
            if not items:
                return "You don't have any history yet. Ask me some questions or try a quiz first."
            top = items[0]
            return f"Start with objective {top['objective_id']}, {top['title']}. You've got {len(items)} topics on your list."
        if tool == "get_objective":
            requires = result.get("syllabus_requires") or []
            excluded = result.get("excluded") or []
            said = f"Objective {result['objective_id']}, {result['title']}. "
            said += f"The syllabus asks you to cover {len(requires)} point{'s' if len(requires) != 1 else ''}, shown on screen. "
            said += (f"It excludes {excluded[0]}." if len(excluded) == 1 else
                     f"It excludes {len(excluded)} things: {'; '.join(excluded)}." if excluded else "Nothing is excluded.")
            return said
        if tool == "list_subjects":
            names = sorted({s["subject"] for s in result.get("subjects", [])})
            return "I know the syllabus for " + ", ".join(names[:-1]) + f" and {names[-1]}."
        return "Done."


def make_brain(choice: str | None = None) -> Brain:
    choice = (choice or os.environ.get("SYLLABUDDY_BRAIN") or "auto").lower()
    base = os.environ.get("SYLLABUDDY_LLM_BASE_URL")
    key = os.environ.get("SYLLABUDDY_LLM_API_KEY", "")
    model = os.environ.get("SYLLABUDDY_LLM_MODEL")
    bedrock_model = os.environ.get("BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0")

    if choice == "auto":
        if os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE"):
            choice = "bedrock"
        elif base and model:
            choice = "openai"
        else:
            choice = "offline"
    if choice == "bedrock":
        return BedrockBrain(bedrock_model)
    if choice == "openai":
        if not (base and model):
            raise RuntimeError("Set SYLLABUDDY_LLM_BASE_URL and SYLLABUDDY_LLM_MODEL for the openai brain.")
        return OpenAICompatibleBrain(base, key, model)
    return OfflineBrain()


# ---- the agent loop -------------------------------------------------------------------

class Assistant:
    def __init__(self, brain: Brain | None = None, mcp_url: str = MCP_URL) -> None:
        self.brain = brain or make_brain()
        self.mcp_url = mcp_url
        self.sessions: dict[str, list[dict[str, Any]]] = {}
        self.fallback = OfflineBrain()

    async def _connect(self, stack: AsyncExitStack, student: str) -> Client:
        http = await stack.enter_async_context(create_mcp_http_client(headers={"X-Syllabuddy-Student": student}))
        return await stack.enter_async_context(Client(streamable_http_client(self.mcp_url, http_client=http)))

    @staticmethod
    def _tool_specs(listed) -> list[dict[str, Any]]:
        specs = []
        for tool in listed.tools:
            schema = _simplify_schema(dict(tool.input_schema if hasattr(tool, "input_schema") else tool.inputSchema))
            schema.setdefault("type", "object")
            schema.setdefault("properties", {})
            specs.append({"name": tool.name, "description": tool.description or "", "parameters": schema})
        return specs

    def reset(self, session: str) -> None:
        self.sessions.pop(session, None)

    async def turn(self, session: str, student: str, utterance: str) -> AsyncIterator[dict[str, Any]]:
        """Run one user turn, yielding events for the UI as they happen."""
        history = self.sessions.setdefault(session, [])
        history.append({"role": "user", "content": utterance})
        started = time.perf_counter()

        async with AsyncExitStack() as stack:
            try:
                client = await self._connect(stack, student)
                tools = self._tool_specs(await client.list_tools())
            except Exception as error:  # noqa: BLE001 - surfaced to the user, not swallowed
                yield {"type": "error", "message": f"Couldn't reach the Syllabuddy MCP server at {self.mcp_url} ({error})."}
                return

            brain = self.brain
            for _round in range(MAX_TOOL_ROUNDS + 1):
                messages = [{"role": "system", "content": SYSTEM_PROMPT}] + _compact(history[-MAX_HISTORY:])
                if brain is not self.fallback and time.perf_counter() - started > TURN_DEADLINE:
                    yield {"type": "status", "message": "Taking too long, answering from the syllabus directly"}
                    brain = self.fallback
                try:
                    remaining = max(TURN_DEADLINE - (time.perf_counter() - started), 5)
                    reply = await asyncio.wait_for(brain.chat(messages, tools), timeout=remaining)
                except Exception as error:  # noqa: BLE001
                    if isinstance(brain, OfflineBrain):
                        yield {"type": "error", "message": f"The model ({brain.name}) failed: {error}"}
                        return
                    # Rate-limited or down: answer this turn straight from the syllabus
                    # rather than leaving the student with nothing.
                    yield {"type": "status", "message": f"{brain.name} unavailable, answering from the syllabus directly"}
                    brain = self.fallback
                    reply = await brain.chat(messages, tools)
                if not reply.tool_calls or _round == MAX_TOOL_ROUNDS:
                    text = _clean_for_speech(reply.text) or "Sorry, I didn't catch that."
                    history.append({"role": "assistant", "content": text})
                    print(f"[turn] {time.perf_counter() - started:5.1f}s {brain.name:28s} {utterance[:60]!r}", flush=True)
                    yield {"type": "answer", "text": text, "brain": brain.name,
                           "seconds": round(time.perf_counter() - started, 2)}
                    return

                history.append({"role": "assistant", "content": reply.text or None, "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                    for c in reply.tool_calls]})
                for call in reply.tool_calls:
                    yield {"type": "tool_call", "name": call.name, "arguments": call.arguments}
                    t0 = time.perf_counter()
                    try:
                        result = await client.call_tool(call.name, call.arguments)
                        data = _result_data(result)
                    except Exception as error:  # noqa: BLE001
                        data = {"error": str(error)}
                    yield {"type": "tool_result", "name": call.name, "result": data,
                           "ms": round((time.perf_counter() - t0) * 1000)}
                    history.append({"role": "tool", "tool_call_id": call.id, "name": call.name,
                                    "content": json.dumps(data, ensure_ascii=False)})


# ---- helpers -------------------------------------------------------------------------

def _simplify_schema(node: Any) -> Any:
    """Flatten pydantic's JSON Schema into the plain subset every model accepts.

    ``str | None = None`` arrives as ``anyOf: [string, null]`` with ``default:
    null``. Some Bedrock models reject null types in tool schemas, and the
    titles only cost tokens, so optional fields become plain optional fields.
    """
    if isinstance(node, list):
        return [_simplify_schema(n) for n in node]
    if not isinstance(node, dict):
        return node
    node = {k: v for k, v in node.items() if k != "title"}
    options = node.get("anyOf")
    if isinstance(options, list):
        non_null = [o for o in options if not (isinstance(o, dict) and o.get("type") == "null")]
        if len(non_null) == 1 and len(non_null) < len(options):
            node = {k: v for k, v in node.items() if k != "anyOf"} | non_null[0]
    if node.get("default", "") is None:
        node.pop("default")
    return {k: _simplify_schema(v) for k, v in node.items()}


def _result_data(result) -> dict[str, Any]:
    structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        # Tools returning a dict are wrapped as {"result": {...}} by some SDK versions.
        return structured.get("result", structured) if set(structured) == {"result"} else structured
    texts = [c.text for c in (result.content or []) if getattr(c, "type", "") == "text"]
    joined = "\n".join(texts)
    try:
        return json.loads(joined)
    except json.JSONDecodeError:
        return {"text": joined}


_KEEP = ("verdict", "objective_id", "title", "subject", "excluded_item", "match", "stats", "recorded", "error")


def _summary(data: Any) -> Any:
    """The parts of an old tool result worth remembering: ids and verdicts, not full cards."""
    if isinstance(data, dict):
        kept = {k: _summary(v) for k, v in data.items()
                if k in _KEEP or isinstance(v, dict) or (isinstance(v, list) and any(isinstance(x, dict) for x in v))}
        return {k: v for k, v in kept.items() if v not in ({}, [], None)}
    if isinstance(data, list):
        return [_summary(v) for v in data[:3]]
    return data


def _compact(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shrink tool results from earlier turns before resending the conversation.

    The model needs the full syllabus card only for the question it is
    answering now. Older cards were costing thousands of tokens per turn, which
    is slow everywhere and trips per-minute limits on free API tiers.
    """
    # A trimmed window must start at a user turn, never mid tool exchange.
    start = next((i for i, m in enumerate(history) if m["role"] == "user"), len(history))
    history = history[start:]
    last_user = max((i for i, m in enumerate(history) if m["role"] == "user"), default=0)
    out = []
    for i, m in enumerate(history):
        if m["role"] == "tool" and i < last_user:
            m = m | {"content": json.dumps(_summary(_as_json(m["content"])), ensure_ascii=False)}
        out.append(m)
    return out


def _retry_after(response: httpx.Response) -> float:
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header) + 0.25
        except ValueError:
            pass
    match = re.search(r"try again in ([\d.]+)s", response.text)
    return float(match.group(1)) + 0.25 if match else 2.0


def _as_json(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    try:
        value = json.loads(content)
        return value if isinstance(value, dict) else {"value": value}
    except (TypeError, json.JSONDecodeError):
        return {"text": str(content)}


def _clean_for_speech(text: str) -> str:
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


def _overlap(answer: str, reference: str) -> float:
    words = lambda s: {w for w in re.findall(r"[a-z]{4,}", s.lower())}
    ref = words(reference)
    return len(words(answer) & ref) / len(ref) if ref else 0.0
