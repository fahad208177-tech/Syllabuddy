# Demo video script (target 2:40, hard limit 3:00)

Judges may stop at 3:00, so the best moment comes first. Record the screen at
1080p with your voice. Start the app with `python run.py`. Before recording,
click "Start a new conversation", and ask one warm-up question off camera so
the first answer isn't slow.

| Time | Show | Say / do |
|---|---|---|
| 0:00–0:12 | The app, welcome screen | "Every A-Level student asks this every week: *is this even in the syllabus?* General AI guesses. Syllabuddy checks." |
| 0:12–0:40 | **Hold the mic**: "Is the shortest distance between two skew lines on the H2 Maths exam?" | Let the tool chip appear and the answer play. Point at **NOT EXAMINABLE**, objective **9758.3.3**, and the red highlighted bullet. "That's the syllabus's own wording, page 8." |
| 0:40–0:55 | Follow-up: "What about the distance from a point to a plane?" | Examinable, same objective. "It knows the difference. Only the skew-lines case is excluded." |
| 0:55–1:10 | "Do I need to know Type II error?" | Excluded, from a bullet that packs three exclusions together. |
| 1:10–1:45 | "Quiz me on H2 Physics", then answer out loud (get it wrong on purpose) | The quiz card, the spoken marking, and the revision list updating on the right. |
| 1:45–2:00 | "What should I revise first?" | "Alexa+ remembers your shoe size. Syllabuddy remembers what you got wrong." |
| 2:00–2:30 | Split screen: `mcp_server/server.py` tool list + `pytest -q` passing | "It's a standard MCP server over Streamable HTTP, spec 2025-11-25. No LLM inside the tools: 916 objectives parsed from the official PDFs. The brain is Amazon Bedrock." Show `.env` with `SYLLABUDDY_BRAIN=bedrock` (hide keys!). |
| 2:30–2:40 | README roadmap | "Next: account linking and a real Alexa+ add-on, and more exams beyond Singapore." |

Shortcut: `python scripts/record_demo.py` (with the app running) records a clean
1600×900 capture of the real app answering this exact script and saves
`artifacts/demo_capture.mp4`. It's silent, so add your voice-over and the
code and test shots on top.

Checklist before recording:
- [ ] Brain set to Bedrock (for the AWS Builder entry) or Groq. Check the status pill and the "brain:" line.
- [ ] Browser zoom 110–125% so text is readable in the video.
- [ ] No API keys, emails or personal details on screen.
- [ ] Upload to YouTube or Vimeo as **public**, in English, with no copyrighted music.
