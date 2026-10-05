---
name: syllabuddy
description: Answer students' "is this on my exam?" questions from the official syllabus (digital SAT and PSAT, ACT, US AP courses, Alberta Diploma, Singapore-Cambridge A-Level) using the Syllabuddy MCP server. Use when a student asks whether a topic is examinable or in the syllabus, which syllabus objective a question belongs to, what a topic requires, to be quizzed, or what to revise. Never guess what is examinable.
---

# Syllabuddy: answer from the syllabus, not from memory

Syllabuddy is an MCP server (Streamable HTTP, default `http://127.0.0.1:8765/mcp`)
holding 2,883 learning objectives parsed from official syllabus documents: the
digital SAT and PSAT (College Board assessment framework), the ACT (College and
Career Readiness Standards, grouped by score range), 24 AP courses (Course
and Exam Descriptions), Alberta Diploma Physics 30 and Chemistry 30, and the
Singapore-Cambridge A-Level (H1/H2 sciences, maths, computing, humanities). Its tools return facts, not opinions: when it says a topic is
excluded, that is the syllabus's own wording.

## Which tool to use

| The student says | Call |
|---|---|
| "Is X in the syllabus / on my exam / examinable?", "Do I need to know X?" | `check_examinable(topic, subject?)` |
| "Explain X", "What does the syllabus want for X?" | `find_objective(question, subject?)` first, then explain within `syllabus_requires` |
| "Quiz me (on H2 Physics)" | `start_quiz(subject?)`, ask one question, then `record_quiz_result` |
| "I'm taking AP Calc BC and the SAT", "My exam is May 11" | `set_my_courses(courses, exam_date?)` (YYYY-MM-DD) |
| "What should I revise?", "How am I doing?" | `my_revision_list()` (mention `days_to_exam` when present) |
| "What subjects / topics do you know?" | `list_subjects()`, `list_topics(subject)` |
| A specific objective id like 9758.3.3, CALCBC-10.8 or SATM-4.3 | `get_objective(objective_id)` |
| "Delete my history" | `clear_my_history()` → ask the student to confirm → `clear_my_history(confirm=true)` in the next turn (the server enforces the two steps) |

## Rules

1. **Pass the topic as specifically as the student said it.** "Skew lines" are
   examinable in H2 Maths; "the shortest distance between skew lines" is
   explicitly excluded. Shortening the topic changes the answer.
2. **Pass the subject as the student said it** ("SAT math", "PSAT 8/9", "AP Calc AB",
   "APUSH", "Physics 30", "H2 Maths", or a code like "9758" or "CALCBC"). Leave it
   out when the student has saved courses: the server then searches those.
   The PSAT 8/9 has its own math syllabus with less content than the SAT.
3. **Report verdicts exactly:**
   - `excluded`: say it is not examinable and quote `excluded_item` briefly.
   - `examinable`: say which objective covers it.
   - `unclear`: say it may be assumed prior knowledge rather than an examinable objective.
   - `not_in_syllabus`: say it isn't covered. Do not answer as if it were.
4. **Always cite the objective id** (for example "objective 9758.3.3", or for AP and SAT "topic 10.8 of AP Calculus BC" for CALCBC-10.8) so the
   student can check it in the syllabus document (`source` gives the PDF page).
5. **Explanations stay inside `syllabus_requires`.** Offer more depth rather than
   teaching beyond the syllabus by default.
6. **Quizzes are one question at a time**, answerable in a sentence or two, and
   judged against `syllabus_requires`. Always record the result so the revision
   list learns.

## Example

> Student: "Is the shortest distance between two skew lines on the H2 Maths exam?"
>
> Call `check_examinable(topic="shortest distance between two skew lines", subject="H2 Maths")`
> → `verdict: excluded`, objective `9758.3.3`, excluded_item "shortest distance between two skew lines"
>
> Reply: "No, that's not examinable. Objective 9758.3.3 lists the shortest distance between two skew
> lines under Excluded, though the distance from a point to a line or plane is still tested."

## Resources and prompts

MCP clients that browse resources can read `syllabus://subjects`,
`syllabus://subject/{subject_id}` and `syllabus://objective/{objective_id}`.
Two prompts are offered: `revision_plan(subject, days)` and
`is_it_on_my_exam(topic, subject?)`.

## Connecting

Run the server from the repo root with `python -m mcp_server`, then add it to
your agent's MCP configuration as a Streamable HTTP server at
`http://127.0.0.1:8765/mcp`. Send an `X-Syllabuddy-Student` header to keep
per-student revision history separate.
