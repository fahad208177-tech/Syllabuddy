// Simulated Alexa+ screen: voice in, MCP tool activity, spoken answer, visual card.
(() => {
  const $ = (s) => document.querySelector(s);
  const feed = $("#feed"), screen = $("#screen"), input = $("#text"), mic = $("#mic");

  // ---- identity: one student per browser (stands in for Alexa account linking)
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode: fine */ } },
  };
  const rid = () => Math.random().toString(36).slice(2, 10);
  let student = store.get("syllabuddy.student");
  if (!student) { student = "stu-" + rid(); store.set("syllabuddy.student", student); }
  let session = "s-" + rid();

  // ---- small DOM helpers (textContent only, never innerHTML with data)
  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function list(items, hit) {
    if (!items || !items.length) return el("div", "none", "None listed");
    const ul = el("ul");
    for (const item of items) {
      const li = el("li", hit && item === hit ? "hit" : "", item);
      ul.append(li);
    }
    return ul;
  }
  function scrollDown() { screen.scrollTop = screen.scrollHeight; }
  function setState(state) {
    document.body.classList.remove("listening", "thinking", "speaking");
    if (state) document.body.classList.add(state);
  }

  // ---- visual cards (what an Echo Show would display)
  const VERDICT_LABEL = { excluded: "Not examinable", examinable: "Examinable", unclear: "Unclear",
    not_in_syllabus: "Not in syllabus", matched: "Matched", approximate: "Approximate match", weak: "Weak match" };

  function objectiveCard(o, badgeClass, badgeText, hitExcluded, showLists = true) {
    const card = el("div", "card");
    const head = el("div", "card-head");
    head.append(el("span", `verdict v-${badgeClass}`, badgeText), el("span", "code", o.objective_id));
    card.append(head, el("h3", null, o.title), el("div", "crumb", `${o.subject} › ${o.topic} › ${o.source}`));
    if (showLists && (o.syllabus_requires || o.excluded)) {
      const cols = el("div", "cols");
      const a = el("div"), b = el("div");
      a.append(el("h4", null, "The syllabus requires"), list(o.syllabus_requires));
      b.append(el("h4", null, "Excluded"), list(o.excluded, hitExcluded));
      cols.append(a, b);
      card.append(cols);
    }
    return card;
  }

  // The card must show the objective the spoken answer actually cites. A search
  // returns several candidates and the assistant may rightly pick the second.
  function citedIn(text, objectives) {
    return objectives.find((o) => o && text.includes(o.objective_id)) || null;
  }

  function cardFor(tool, r, answer = "") {
    if (!r || r.error) return null;
    if (tool === "check_examinable") {
      const o = r.objective || r.closest_objective;
      if (!o) return null;
      return objectiveCard(o, r.verdict, VERDICT_LABEL[r.verdict] || r.verdict, r.excluded_item, !!r.objective);
    }
    if (tool === "find_objective" && r.objectives && r.objectives.length) {
      const cited = citedIn(answer, r.objectives);
      if (!cited && answer && /\b(\d{4}\.[0-9a-z]+|[A-Z][A-Z0-9]{1,7}-\d+\.\d+)/i.test(answer)) return null;  // cites something not shown here
      const o = cited || r.objectives[0];
      // Only the top result carries full requires/excludes; others show the header.
      return objectiveCard(o, r.match, VERDICT_LABEL[r.match], null, !!o.syllabus_requires);
    }
    if (tool === "get_objective" && r.objective_id) return objectiveCard(r, "matched", "Objective");
    if (tool === "start_quiz" && r.quiz_objective) {
      // Don't reveal what the answer should contain.
      return objectiveCard(r.quiz_objective, "quiz", "Quiz", null, false);
    }
    if (tool === "my_revision_list") {
      const card = el("div", "card revise-card");
      const head = el("div", "card-head");
      head.append(el("span", "verdict v-quiz", "Revise first"));
      card.append(head);
      const items = r.revise_first || [];
      if (!items.length) { card.append(el("div", "crumb", r.note || "No history yet.")); return card; }
      const ul = el("ul");
      for (const it of items) ul.append(el("li", null, `${it.objective_id} · ${it.title}`));
      card.append(ul);
      return card;
    }
    return null;
  }

  // ---- follow-up suggestions, so a student always knows what they can say next
  function followUps(tool, r) {
    if (!r || r.error) return [];
    const o = r.objective || (r.objectives && r.objectives[0]) || r.quiz_objective || null;
    const id = o && o.objective_id;
    switch (tool) {
      case "check_examinable":
        if (r.verdict === "excluded") return [`What does ${id} require?`, `Quiz me on ${id}`];
        if (r.verdict === "examinable") return [`Quiz me on ${id}`, `Is anything excluded from ${id}?`];
        return ["What subjects do you know?"];
      case "find_objective":
      case "get_objective":
        return id ? [`Quiz me on ${id}`, `Is anything excluded from ${id}?`] : [];
      case "start_quiz":
        return ["I don't know"];
      case "record_quiz_result":
        return ["Quiz me again", "What should I revise first?"];
      case "my_revision_list":
        return (r.revise_first || []).length ? ["Quiz me on my weakest topic"] : ["Quiz me on H2 Physics"];
      default:
        return [];
    }
  }

  function suggestionRow(items) {
    const row = el("div", "follow");
    for (const text of items) {
      const b = el("button", "chip small", text);
      b.type = "button";
      b.addEventListener("click", () => ask(text));
      row.append(b);
    }
    return row;
  }

  // ---- speech out
  let voice = null;
  function pickVoice() {
    const voices = window.speechSynthesis ? speechSynthesis.getVoices() : [];
    voice = voices.find((v) => /en-US/i.test(v.lang) && /(Aria|Jenny|Samantha|Google US|Natural)/i.test(v.name))
      || voices.find((v) => /en-US/i.test(v.lang)) || voices[0] || null;
  }
  if (window.speechSynthesis) { pickVoice(); speechSynthesis.onvoiceschanged = pickVoice; }

  function forSpeech(text) {
    // "9758.3.3" should be read as "9 7 5 8 point 3 point 3", not "nine thousand...".
    // AP ids ("CALCBC-10.8") are read as "topic 10.8"; the subject is already in the sentence.
    return text
      .replace(/\b[A-Z][A-Z0-9]{1,7}-(\d+\.\d+)\b/g, (_, topic) => "topic " + topic)
      .replace(/\b(\d{4})((?:\.[0-9a-z]+)+)\b/gi, (_, code, rest) =>
        code.split("").join(" ") + rest.split(".").filter(Boolean).map((p) => " point " + p).join(""));
  }
  function speak(text) {
    if (!window.speechSynthesis || !text) { setState(null); return; }
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(forSpeech(text));
    if (voice) u.voice = voice;
    u.rate = 1.02;
    u.onstart = () => setState("speaking");
    u.onend = u.onerror = () => setState(null);
    speechSynthesis.speak(u);
  }

  // ---- a turn
  let busy = false;
  async function ask(text) {
    text = (text || "").trim();
    if (!text || busy) return;
    busy = true;
    if (window.speechSynthesis) speechSynthesis.cancel();
    document.body.classList.add("has-turns");
    const user = $("#tplUser").content.firstElementChild.cloneNode(true);
    user.querySelector(".bubble").textContent = text;
    feed.append(user);
    input.value = "";
    setState("thinking");
    scrollDown();

    const results = [];
    let toolRow = null;
    // A visible "still working" line, since a model call can take a few seconds.
    const pending = el("li", "turn pending", "Thinking…");
    feed.append(pending);
    const started = Date.now();
    const tick = setInterval(() => {
      const s = Math.round((Date.now() - started) / 1000);
      if (s >= 2) pending.textContent = `Thinking… ${s}s`;
    }, 500);
    const settle = () => { clearInterval(tick); pending.remove(); };
    try {
      const res = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, session, student }) });
      if (!res.ok || !res.body) throw new Error((await res.json().catch(() => ({}))).error || res.statusText);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, nl).trim();
          buffer = buffer.slice(nl + 1);
          if (!line) continue;
          const ev = JSON.parse(line);
          if (ev.type === "tool_call") {
            toolRow = $("#tplTool").content.firstElementChild.cloneNode(true);
            feed.insertBefore(toolRow, pending);
            const args = Object.entries(ev.arguments || {}).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(", ");
            const t = toolRow.querySelector(".tool-text");
            t.append("Syllabuddy · ", el("b", null, ev.name), `(${args})`);
          } else if (ev.type === "status") {
            feed.insertBefore(el("li", "turn note", ev.message), pending);
          } else if (ev.type === "tool_result") {
            results.push(ev);
            if (toolRow) { toolRow.classList.add("done"); toolRow.querySelector(".tool-ms").textContent = `${ev.ms} ms`; }
          } else if (ev.type === "answer" || ev.type === "error") {
            settle();
            const ans = $("#tplAnswer").content.firstElementChild.cloneNode(true);
            ans.querySelector(".say").textContent = ev.type === "answer" ? ev.text : ev.message;
            if (ev.type === "error") ans.classList.add("error");
            // Show the card for the most informative tool result of this turn.
            for (let i = results.length - 1; i >= 0; i--) {
              const card = cardFor(results[i].name, results[i].result, ev.type === "answer" ? ev.text : "");
              if (card) { ans.append(card); break; }
            }
            if (ev.type === "answer" && results.length) {
              const last = results[results.length - 1];
              const next = followUps(last.name, last.result);
              document.querySelectorAll(".follow").forEach((f) => f.remove());  // only the latest stays
              if (next.length) ans.append(suggestionRow(next));
            }
            feed.append(ans);
            if (ev.type === "answer") speak(ev.text); else setState(null);
          }
          scrollDown();
        }
      }
    } catch (err) {
      settle();
      const ans = $("#tplAnswer").content.firstElementChild.cloneNode(true);
      ans.classList.add("error");
      ans.querySelector(".say").textContent = "Something went wrong: " + err.message;
      feed.append(ans);
      setState(null);
    } finally {
      settle();
      busy = false;
      scrollDown();
      refreshRevision();
    }
  }

  // ---- speech in (Chrome / Edge Web Speech API)
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null, listening = false, heard = "";
  if (Recognition) {
    rec = new Recognition();
    rec.lang = "en-US";
    rec.interimResults = true;
    rec.continuous = false;
    rec.onresult = (e) => {
      heard = Array.from(e.results).map((r) => r[0].transcript).join("");
      input.value = heard;
    };
    rec.onend = () => {
      listening = false;
      setState(busy ? "thinking" : null);
      if (heard.trim()) ask(heard);
      heard = "";
    };
    rec.onerror = () => { listening = false; setState(null); };
  } else {
    mic.classList.add("unsupported");
    mic.title = "Voice input needs Chrome or Edge. Type instead.";
  }
  function startListening() {
    if (!rec || listening || busy) return;
    if (window.speechSynthesis) speechSynthesis.cancel();
    heard = ""; listening = true; setState("listening");
    try { rec.start(); } catch { listening = false; setState(null); }
  }
  function stopListening() { if (rec && listening) rec.stop(); }

  mic.addEventListener("pointerdown", (e) => { e.preventDefault(); startListening(); });
  mic.addEventListener("pointerup", stopListening);
  mic.addEventListener("pointerleave", stopListening);
  document.addEventListener("keydown", (e) => {
    if (e.code === "Space" && document.activeElement !== input && !e.repeat) { e.preventDefault(); startListening(); }
  });
  document.addEventListener("keyup", (e) => { if (e.code === "Space" && document.activeElement !== input) stopListening(); });

  $("#composer").addEventListener("submit", (e) => { e.preventDefault(); ask(input.value); });
  document.querySelectorAll("[data-say]").forEach((b) => b.addEventListener("click", () => ask(b.dataset.say)));
  $("#reset").addEventListener("click", async () => {
    await fetch("/api/reset", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session }) });
    session = "s-" + rid();
    feed.replaceChildren();
    document.body.classList.remove("has-turns");
  });
  $("#refresh").addEventListener("click", refreshRevision);

  // ---- side panel
  async function refreshRevision() {
    try {
      const r = await (await fetch(`/api/revision?student=${encodeURIComponent(student)}`)).json();
      if (r.error) return;
      $("#statAsked").textContent = r.stats.asked;
      $("#statQuiz").textContent = `${r.stats.right}/${r.stats.quizzed}`;
      const ol = $("#revise");
      ol.replaceChildren();
      if (!r.revise_first.length) {
        ol.append(el("li", "empty", "Ask a few questions or try a quiz, and your weak spots show up here."));
        return;
      }
      for (const it of r.revise_first) {
        const li = el("li");
        const why = it.wrong_answers ? `${it.wrong_answers} wrong in quizzes` : `asked ${it.times_asked}×`;
        li.append(el("span", "code", it.objective_id), el("span", null, it.title), el("div", "why", `${it.subject} · ${why}`));
        ol.append(li);
      }
    } catch { /* side panel is optional */ }
  }

  async function health() {
    try {
      const h = await (await fetch("/api/health")).json();
      $("#statusDot").className = "dot " + (h.mcp_ok ? "ok" : "bad");
      $("#statusText").textContent = h.mcp_ok ? `MCP connected · ${h.tools.length} tools` : "MCP server offline";
      $("#meta").textContent = `brain: ${h.brain}\nmcp: ${h.mcp_url}`;
    } catch {
      $("#statusDot").className = "dot bad";
      $("#statusText").textContent = "Assistant offline";
    }
  }

  health();
  refreshRevision();
  setInterval(health, 15000);
})();
