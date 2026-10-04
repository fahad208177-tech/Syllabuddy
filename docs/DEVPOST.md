# Devpost: About the project (paste into the story field)

## Inspiration

Every student I know asks the same question at least once a week: *"Is this even in the syllabus?"*

When I'm revising for my A Levels, I can get a chatbot to explain almost anything. What it can't do is tell me whether that thing will actually be tested. Ask a general AI whether the shortest distance between two skew lines is examinable in H2 Maths and it will happily guess. The real answer is one bullet point, on page 8 of the official syllabus PDF, under *Excluded*.

I'd already built a tutor that parses the official syllabus. The Alexa+ track made me realise the most useful part wasn't the explanations; it was the facts. Students shouldn't have to dig through PDFs to ask a quick question. They should just be able to ask.

## What it does

Syllabuddy is an MCP server that answers from the official syllabus, plus a simulated Alexa+ voice experience to talk to it. It covers 24 US AP courses, Canada's Alberta Diploma Physics 30 and Chemistry 30, and the Singapore-Cambridge A-Level I started with: 2,381 learning objectives across 40 subjects.

> "Is the ratio test on the AP Calculus AB exam?"
>
> "No, the ratio test is only assessed on the AP Calculus BC exam."
>
> "What about BC?" / "Yes, it's topic 10.8 of AP Calculus BC, Ratio Test for Convergence."

It tells you whether a topic is examinable, which objective a question belongs to and what that objective requires, quizzes you out loud, and remembers which objectives *you* keep getting wrong, so "what should I revise first?" has a real answer. Alexa+ remembers your shoe size; Syllabuddy remembers your weak spots.

## How I built it

**The syllabus, without an LLM.** The syllabus is the one thing that must never be hallucinated, so it's parsed deterministically from the official documents: the College Board's AP Course and Exam Descriptions, Alberta Education's Programs of Study and the SEAB A-Level syllabuses. Each objective keeps its code, what's included, what's excluded, and the source page. One parser reads every AP course, because the College Board uses the same page layout everywhere.

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

**The MCP server.** Nine tools built on the official MCP Python SDK, over Streamable HTTP (spec 2025-11-25). The tools never call a model, so once warm they answer in 14 to 300 ms, inside Alexa+'s 500 ms budget even on my 2-core laptop. Each request carries a student id, which on real Alexa+ would come from account linking.

**The simulated Alexa+.** A web app with voice in and voice out. Behind it, an agent connects to the MCP server as a real MCP client, hands the tool list to a model, runs the tool calls, and speaks a short answer while the screen shows the syllabus card. The model is swappable: any OpenAI-compatible API (I used Groq), Amazon Bedrock's Converse API (implemented, but not run live), or an offline mode that needs no keys at all. If the model is slow or rate-limited, the turn is answered straight from the syllabus instead of failing. There's also an Agent Skill that teaches any agent how to use the tools.

## Challenges I ran into

**"Excluded" is subtle.** My first version said hypothesis testing was excluded from H2 Maths. It isn't: the *correlation* objective excludes "hypothesis tests" on correlation, while objective 9758.6.5 teaches hypothesis testing. I had to make exclusions count only when their parent topic is actually relevant, and only when they beat everything that's included.

**Packed bullets.** One H2 Maths bullet excludes three things at once: "the use of the term Type I error, concept of Type II error and testing the difference between two population means". Matched as one sentence, a question about Type II error scored poorly, so bullets are split into clauses. Short terms like "Type II error" still embed badly, so they're also matched word for word, with "Type II" and "type 2" treated as equal.

**Skew lines, twice.** "Skew lines" *are* examinable (relationships between two lines, coplanar or skew); only "the shortest distance between skew lines" is excluded. If the agent shortens the student's words, the answer changes. So the tool description now tells the model to pass the topic exactly as specifically as the student said it.

**Speed on a weak laptop.** Tool calls first took about 500 ms. Profiling showed the copied embedding cache rewrote a 1.8 MB file to disk for every new question. An in-memory query cache fixed it.

**Getting onto Alexa+ from Singapore.** Alexa+ isn't available here. The Alexa AI CLI isn't on public npm, isn't supported on Windows, and needs an AWS account approved by an Amazon Solutions Architect. So I built the simulated Alexa+ experience the track allows, and kept the server standards-based so it's ready to deploy as a real add-on.

**Mirrored pages.** AP documents put the learning objectives on the left on one page and on the right on the next. Fixed column positions read half the pages wrong, so the parser finds each page's columns from its own headings.

**Three kinds of AP codes, and one course with no topic headers.** Calculus uses `LIM-1.A`, the newer sciences use `1.1.A`, and the history courses use "Unit 4: Learning Objective H" with `KC-4.1.IV.C` codes. CS Principles prints no topic headers at all, only an at-a-glance table, so its objectives are regrouped from that table.

**Hidden text.** Formula images carry accessibility text spelled in fragments ("O p en b rac k et R eq u a l s..."), and one PDF uses a control character instead of spaces. Checking every one of the 2,381 objectives for debris is what found these.

**"BC only" is a real exclusion.** The Calculus document marks content "bc only", so for AP Calculus AB those topics are excluded; that's the most useful answer an AB student can get.

**A live bug: Big-O.** Testing by voice, "Is Big-O notation on AP CS Principles?" came back examinable, though the document says formal Big-O analysis is out of scope. The words didn't match ("notation" isn't in the exclusion, and "big" also appears in "big data"). Now a distinctive term that a subject mentions only in an exclusion decides the answer.

## What I learned

- An AI reads each tool's description to decide when and how to call it. Writing "pass the topic as specifically as the student said it" fixed a real bug.
- Keeping the facts deterministic and letting the model only do the talking is what makes the answers trustworthy.
- How Streamable HTTP works, and why tools need to stay fast for voice.
- Tests catch real mistakes: several of my own assumptions about the syllabus were wrong until I checked them against the parsed data.

## What's next

- Deploy the server and add OAuth account linking to publish a real Alexa+ add-on.
- More exams: Alberta Biology 30 and Mathematics 30-1, Cambridge International A Levels, and other provinces.
- Quizzes drawn from past papers for each objective.
