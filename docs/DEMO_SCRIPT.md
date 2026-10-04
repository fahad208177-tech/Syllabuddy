# Demo video script (target 2:40, hard limit 3:00)

Leads with AP: the judges are US/Canada-based.

Judges may stop at 3:00, so the best moment comes first. Record the screen at
1080p with your voice. Start the app with `python run.py`. Before recording,
click "Start a new conversation", and ask one warm-up question off camera so
the first answer isn't slow.

| Time | Show | Say / do |
|---|---|---|
| 0:00–0:12 | The app, welcome screen | "Every student asks this before an exam: *is this even on the test?* General AI guesses. Syllabuddy checks the official syllabus." |
| 0:12–0:35 | **Hold the mic**: "Is the ratio test on the AP Calculus AB exam?" | The tool chip appears, then **NOT EXAMINABLE**: BC only. "The College Board's own document marks it BC only." |
| 0:35–0:50 | Follow-up: "What about BC?" | Examinable, topic 10.8, Ratio Test for Convergence. "It knows AB from BC." |
| 0:50–1:05 | "Do I need the epsilon-delta definition of a limit?" | Excluded, quoting the CED's exclusion statement. |
| 1:05–1:20 | "Is Big-O notation on AP CS Principles?" | Excluded: "formal analysis of algorithms (Big-O)... outside the scope". |
| 1:20–1:35 | "Is the photoelectric effect on the Physics 30 diploma?" | Examinable, Alberta outcome C2. "24 AP courses, Alberta's diploma exams, and the Singapore A-Level: 2,381 objectives." |
| 1:35–2:00 | "Quiz me on AP Physics 1", answer out loud (get it wrong on purpose), then "What should I revise first?" | Quiz card, spoken marking, revision list updates. "Alexa+ remembers your shoe size. Syllabuddy remembers what you got wrong." |
| 2:00–2:30 | Split screen: `mcp_server/server.py` + `python scripts/eval_all.py` summary + `pytest -q` | "A standard MCP server over Streamable HTTP, spec 2025-11-25. No LLM inside the tools. Every one of the 2,381 objectives is tested." |
| 2:30–2:40 | README roadmap | "Next: account linking and a real Alexa+ add-on, and more exams." |

Shortcut: `python scripts/record_demo.py` (with the app running) records a clean
1600×900 capture of the real app answering this exact script and saves
`artifacts/demo_capture.mp4`. It's silent, so add your voice-over and the
code and test shots on top.

Checklist before recording:
- [ ] Status pill shows "MCP connected · 9 tools" and the "brain:" line shows Groq.
- [ ] Machine idle (close other apps): on a busy 2-core laptop turns slow down and fall back to templated answers.
- [ ] Ask questions about 20–30 s apart (Groq free tier), or cut the pauses when editing.
- [ ] Browser zoom 110–125% so text is readable in the video.
- [ ] No API keys, emails or personal details on screen.
- [ ] Upload to YouTube or Vimeo as **public**, in English, with no copyrighted music.
