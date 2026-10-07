# Devpost: About the project (paste into the story field)

**Built With** (paste into the Built With field): `alexa-plus`, `model-context-protocol`, `mcp-python-sdk`, `streamable-http`, `oauth2`, `agent-skills`, `python`, `starlette`, `uvicorn`, `sqlite`, `fastembed`, `onnx`, `pymupdf`, `groq`, `javascript`, `web-speech-api`

---

## Inspiration

A year ago, my teacher told our class something that changed how I study: **stop revising only from the textbook, and study from the syllabus document instead.** The textbook covers whatever its author found interesting. The syllabus is the exam board's own list of exactly what can be tested, and, just as useful, what can't.

So I tried it. Before starting a topic, I read its learning objectives first, checked the *Excluded* bullets, and only then opened the textbook. I stopped spending hours on things that were never going to come up, and I finally knew what each objective was actually asking me to do. It worked.

But it was slow. The syllabus is a long PDF, and the question I kept asking, *"is this even on the exam?"*, meant scrolling through it again every time. A chatbot couldn't help either. Ask a general AI whether the shortest distance between two skew lines is examinable in H2 Maths and it will confidently guess. The real answer is one bullet point, on page 8 of the official syllabus, under *Excluded*.

Then I saw this hackathon's Alexa+ track, and it clicked. What my teacher taught me shouldn't depend on having a teacher who tells you, or the patience to dig through PDFs. It should be something you can just ask, out loud. I had already started parsing my own A-Level syllabus for a small study tool, so I turned that idea into Syllabuddy and extended it to the exams millions of students in the US and Canada take: the SAT, the ACT and AP.

**Who it's for.** In the US class of 2025, more than 2 million students took the SAT, 1,380,130 took the ACT, and 1,307,781 public-school graduates took more than 4.8 million AP exams (College Board and ACT annual reports). Each has an official syllabus that settles what's tested; almost none of them read it.

**What students said.** Five students tried Syllabuddy before submission. Quotes are lightly edited for spelling and grammar.

> "Pretty shocking that many things I thought were in the syllabus weren't, and I finally understood what I was actually going to be asked on."
> <br>— student tester

> "I was quite shocked by how it remembered my weaknesses and tested me on those weaknesses to ensure that I don't get it wrong in the exam."
> <br>— student tester

> "It was really accurate. I look at the syllabus requirements monthly for math, and from what I tested, it was super accurate."
> <br>— student tester, math

> "I didn't even know there were syllabus learning objectives for exams, and after trying this I'm pretty confident that I will do well in my exams."
> <br>— student tester

> "This new study method is really cool. I have been using it for a week, and my marks on practice papers went from just passing to a high B. Very awesome product."
> <br>— student tester

## What it does

Syllabuddy is an **Alexa+ add-on**: an **MCP server** (Streamable HTTP, with OAuth 2.1 account linking and an Agent Skill) that answers from the official syllabus, plus a simulated Alexa+ voice experience to talk to it. It covers the digital SAT and PSAT, the ACT, 24 US AP courses, Canada's Alberta Diploma Physics 30 and Chemistry 30, and the Singapore-Cambridge A-Level I started with: 2,883 learning objectives across 47 subjects.

> "Is the ratio test on the AP Calculus AB exam?"
>
> "No, the ratio test is only assessed on the AP Calculus BC exam."
>
> "What about BC?" / "Yes, it's topic 10.8 of AP Calculus BC, Ratio Test for Convergence."

> "Are circles on the PSAT 8/9?"
>
> "No. Circles are on the SAT and PSAT/NMSQT, but the PSAT 8/9 leaves them out."

It tells you whether a topic is examinable, which objective a question belongs to and what that objective requires, and quizzes you out loud. Say "I'm taking AP Calc BC and the SAT, my exam is May 11" once, and every later question is checked against those two syllabuses. It remembers which objectives *you* keep getting wrong and how much of each syllabus you've practised, so "what should I revise first?" comes back with your weak spots and the days left. Alexa+ remembers your shoe size; Syllabuddy remembers your exams.

## How I built it

**The syllabus, without an LLM.** The syllabus is the one thing that must never be hallucinated, so it's parsed deterministically from the official documents: the College Board's SAT Suite assessment framework and AP Course and Exam Descriptions, ACT's College and Career Readiness Standards, Alberta Education's Programs of Study and the SEAB A-Level syllabuses. Each objective keeps its code, what's included, what's excluded, and the source page. One parser reads every AP course, because the College Board uses the same page layout everywhere.

**Matching questions.** A hybrid search (BM25 plus `bge-small` embeddings, fused with Reciprocal Rank Fusion) finds the closest objective. The best cosine similarity $c$ acts as a confidence score, calibrated on real questions:

$$
\text{verdict} =
\begin{cases}
\text{examinable} & c \ge 0.62 \\
\text{unclear (maybe assumed knowledge)} & 0.58 \le c < 0.62 \\
\text{not in the syllabus} & c < 0.58
\end{cases}
$$

**Deciding "excluded".** Every Excluded bullet is indexed separately. Let $e$ be the best exclusion match and $i$ the best *included* match. An exclusion only wins when

$$
e \ge 0.85 \quad\text{and}\quad e \ge i + 0.05,
$$

and only inside its own topic.

**The MCP server.** Ten tools, three resources (`syllabus://objective/{id}` and friends) and two prompts (a revision plan, "is it on my exam?") built on the official MCP Python SDK, over Streamable HTTP (spec 2025-11-25). It is also its own OAuth 2.1 authorization server, the way Alexa+ account linking works: a client registers itself, the student signs in once with a username and PIN, and the same revision list follows them from Alexa+ to the web app to Claude. The tools never call a model, so once warm they answer in 14 to 300 ms, inside Alexa+'s 500 ms budget even on my 2-core laptop. Each request carries a student id, which on real Alexa+ would come from account linking.

**The simulated Alexa+.** A web app with voice in and voice out. Behind it, an agent connects to the MCP server as a real MCP client, hands the tool list to a model, runs the tool calls, and speaks a short answer while the screen shows the syllabus card. The model is swappable: any OpenAI-compatible API (I used Groq), Amazon Bedrock's Converse API (implemented, but not run live), or an offline mode that needs no keys at all. If the model is slow or rate-limited, the turn is answered straight from the syllabus instead of failing. There's also an Agent Skill that teaches any agent how to use the tools.

## Challenges I ran into

**"Excluded" is subtle.** My first version said hypothesis testing was excluded from H2 Maths. It isn't: the *correlation* objective excludes "hypothesis tests" on correlation, while objective 9758.6.5 teaches hypothesis testing. I had to make exclusions count only when their parent topic is actually relevant, and only when they beat everything that's included.

**Packed bullets.** One H2 Maths bullet excludes three things at once: "the use of the term Type I error, concept of Type II error and testing the difference between two population means". Matched as one sentence, a question about Type II error scored poorly, so bullets are split into clauses. Short terms like "Type II error" still embed badly, so they're also matched word for word, with "Type II" and "type 2" treated as equal.

**Skew lines, twice.** "Skew lines" *are* examinable (relationships between two lines, coplanar or skew); only "the shortest distance between skew lines" is excluded. If the agent shortens the student's words, the answer changes. So the tool description now tells the model to pass the topic exactly as specifically as the student said it.

**Speed on a weak laptop.** Tool calls first took about 500 ms. Profiling showed the copied embedding cache rewrote a 1.8 MB file to disk for every new question. An in-memory query cache fixed it.

**Getting onto Alexa+ from Singapore.** Alexa+ isn't available here. The Alexa AI CLI isn't on public npm, isn't supported on Windows, and needs an AWS account approved by an Amazon Solutions Architect. So I built the simulated Alexa+ experience the track allows, and kept the server standards-based so it's ready to deploy as a real add-on.

**Mirrored pages.** AP documents put the learning objectives on the left on one page and on the right on the next. Fixed column positions read half the pages wrong, so the parser finds each page's columns from its own headings.

**Three kinds of AP codes, and one course with no topic headers.** Calculus uses `LIM-1.A`, the newer sciences use `1.1.A`, and the history courses use "Unit 4: Learning Objective H" with `KC-4.1.IV.C` codes. CS Principles prints no topic headers at all, only an at-a-glance table, so its objectives are regrouped from that table.

**Hidden text.** Formula images carry accessibility text spelled in fragments ("O p en b rac k et R eq u a l s..."), and one PDF uses a control character instead of spaces. Checking every one of the 2,883 objectives for debris is what found these.

**"BC only" is a real exclusion.** The Calculus document marks content "bc only", so for AP Calculus AB those topics are excluded; that's the most useful answer an AB student can get.

**One table, three exams.** The SAT framework lists every math skill in a table with three description columns: SAT, PSAT/NMSQT and PSAT 8/9. Text extraction merged the columns on shared baselines, the column positions change from page to page, and bullets nest two levels deep. The parser now works span by span, finds each page's column edges from its most common left margins, rebuilds bullets from indentation, and then compares the SAT and PSAT 8/9 columns bullet by bullet. Whatever the PSAT 8/9 drops (circles, margin of error, trig ratios) becomes a PSAT 8/9 exclusion.

**A live bug: Big-O.** Testing by voice, "Is Big-O notation on AP CS Principles?" came back examinable, though the document says formal Big-O analysis is out of scope. The words didn't match ("notation" isn't in the exclusion, and "big" also appears in "big data"). Now a distinctive term that a subject mentions only in an exclusion decides the answer.

## What I learned

- My teacher was right, and it scales: once the syllabus is structured data, "is this on the exam?" takes milliseconds instead of a PDF search, and five student testers felt the same difference I did.
- An AI reads each tool's description to decide when and how to call it. Writing "pass the topic as specifically as the student said it" fixed a real bug.
- Keeping the facts deterministic and letting the model only do the talking is what makes the answers trustworthy.
- How Streamable HTTP works, and why tools need to stay fast for voice.
- Tests catch real mistakes: several of my own assumptions about the syllabus were wrong until I checked them against the parsed data.

## What's next

- Publish it as a real Alexa+ add-on. The server, OAuth account linking and manifest are ready; it needs Amazon's allow-listed Alexa AI CLI.
- More exams: GED and CLEP next, then Alberta Biology 30 and Mathematics 30-1 and other provinces.
- Quizzes drawn from past papers for each objective.
- Grow [syllabus-parsers](https://github.com/fahad208177-tech/syllabus-parsers), the open-source library I split out of this project, so other study tools can use official syllabus data too.
