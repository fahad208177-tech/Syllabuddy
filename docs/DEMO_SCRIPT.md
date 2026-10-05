# Demo video script (target 2:45, hard limit 3:00)

A pitch, not a tutorial: **problem → it working → who it's for → how it uses
Alexa+ → what's real.** The track's tool (an **Alexa+ add-on built as an MCP
server**) is named out loud three times: at 0:20, 1:50 and 2:15.

Judges may stop early, so the best moment comes first. Open with the launch
video (`brag-output/brag.mp4`, 20 s) or go straight to the app.

| Time | Show | Say / do |
|---|---|---|
| 0:00–0:20 | Launch video, or the welcome screen | **The problem.** "Every student asks it before an exam: *is this even on the test?* Ask a chatbot and it guesses. The real answer is one line in a 200-page syllabus PDF that nobody reads." |
| 0:20–0:30 | The app's header: "Syllabuddy for Alexa+" | **The solution, and the track's tool.** "Syllabuddy is an **Alexa+ add-on**: an **MCP server** that gives Alexa+ the official syllabus for the SAT, the ACT, 24 AP courses and more." |
| 0:30–0:55 | **Hold the mic**: "Is the ratio test on the AP Calculus AB exam?" | The `check_examinable` tool row appears, then **NOT EXAMINABLE: BC only**. "That comes from the College Board's own document, quoted, with the topic number." |
| 0:55–1:05 | "What about BC?" | Examinable, topic 10.8. "It knows AB from BC." |
| 1:05–1:20 | "Are circles on the PSAT 8/9?" | Excluded: SAT and PSAT/NMSQT only. "Same for the PSAT 8/9, which leaves things out that the SAT tests." |
| 1:20–1:30 | "Is Big-O notation on AP CS Principles?" | Excluded, quoting "outside the scope of this course and the AP Exam". |
| 1:30–1:50 | "I'm taking AP Calc BC and the SAT, my exam is May 11", then "What should I revise first?" | The "My courses" card, the countdown and progress bars, then the revision list. "Alexa+ remembers your shoe size. **Syllabuddy remembers your exams.**" |
| 1:50–2:15 | Split screen: the tool calls on screen + `mcp_server/server.py` + the account-linking page (`/link`) | **How it uses Alexa+.** "Under the hood it's a standard **MCP server over Streamable HTTP**, the way Alexa+ add-ons work: 10 tools, resources and prompts. It does its own **OAuth account linking**, so one sign-in follows a student from Alexa+ to their laptop. The tools never call an AI, so they can't make things up." |
| 2:15–2:35 | Terminal: `pytest -q` (182 passed) and the `eval_all.py` summary | **Why trust it.** "2,883 objectives parsed from the official documents, and every one is tested: every exclusion comes back excluded." |
| 2:35–2:45 | Closing card: name, live link | **Who it's for.** "Last year, more than 2 million US students took the SAT, 1.4 million the ACT, and 1.3 million public-school graduates took AP exams. Syllabuddy gives each of them the real answer, by voice." |

## Recording tips

- **Use Windows' built-in recorder (Win+Alt+R, Xbox Game Bar)** or OBS. They encode on the graphics card. Browser-based recording on this 2-core laptop starves the server and turns fall back to template answers.
- Better still, record against the hosted Space once it's live. Its CPU is faster, and the link in the video is then the one judges can try.
- Before recording: open the app, click "Start a new conversation", and ask one warm-up question off camera.
- Ask questions about 30 seconds apart (Groq free tier), and cut the pauses when editing.
- Browser zoom 110–125% so text is readable.
- Say "Alexa+", "add-on" and "MCP server" clearly; captions help too.
- No API keys, emails or personal details on screen. Upload to YouTube or Vimeo as **public**, in English, with no copyrighted music. The launch video's music is generated, so it's safe.

## Checklist

- [ ] Status pill shows "MCP connected · 10 tools", and the brain line shows Groq.
- [ ] Under 3:00 (aim for 2:45).
- [ ] The problem is stated in the first 20 seconds.
- [ ] "Alexa+ add-on" and "MCP server" are said out loud.
