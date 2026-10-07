# Product feedback

Syllabuddy is an Alexa+ add-on built as an MCP server (Streamable HTTP), with OAuth 2.1 account linking, an Agent Skill and a simulated Alexa+ web app. Feedback per tool, in the order I used them.

---

## 1. Alexa+ MCP Toolkit documentation

- **What I used it for:** deciding the architecture: an MCP server over Streamable HTTP, the `addon.json` manifest (store listing, example phrases, privacy and terms URLs, icons at six sizes) and the 500 ms tool latency budget.
- **What worked well:** the requirements are concrete. "Streamable HTTP", "respond within 500 ms" and the icon sizes are all stated plainly, so I could design for them before writing code. Building on open MCP meant nothing in the server is Alexa-specific until deployment, so the same server also works in Claude and other clients.
- **What needs work:**
  - **Account linking for MCP add-ons isn't documented.** I couldn't find whether Alexa+ uses dynamic client registration or a pre-registered client, which redirect URIs to allow, or how `addon.json` declares it. I built to the MCP authorization spec, but I can't confirm it matches Alexa+ (friction log #6).
  - The "Test Your MCP Add-ons" page says to deploy first and doesn't link the simulator (friction log #4).
- **Onboarding (zero to hello world):** reading the docs and designing against them was fast. Hello world on a real Alexa+ device never happened, because the CLI wasn't installable (below).
- **Would I build with it again?** Yes. The MCP-first design is the right call: a developer's server stays portable, and Amazon gets add-ons that already work elsewhere.

## 2. Alexa AI CLI (`alexa-ai`)

- **What I used it for:** I planned to scaffold and deploy with `alexa-ai new mcp` and `alexa-ai deploy`.
- **What worked well:** the documented workflow (scaffold, then deploy, then test) is short and clear on paper.
- **What needs work:**
  - **The install command returns 404** without an allow-listed AWS account (friction log #1). For a public hackathon this was the single biggest blocker.
  - **Windows isn't supported** (#2), and many student developers are on Windows.
  - Alexa+ isn't available in my country (Singapore), so I couldn't test on a device either (#3).
- **Onboarding:** stopped at install. I fell back to the simulated Alexa+ path that the track allows.
- **Would I build with it again?** Yes, once it's publicly installable. A hackathon allow-listing route, or a public preview, would make Alexa+ the obvious choice for student builders.

## 3. Model Context Protocol Python SDK (`mcp` 2.3.0)

- **What I used it for:** the whole server: 10 tools, 3 resources (`syllabus://…`), 2 prompts, Streamable HTTP, and the OAuth 2.1 authorization server for account linking (metadata, dynamic client registration, PKCE, token rotation). The simulated Alexa+ agent uses the SDK's client to call the server exactly as an outside client would.
- **What worked well:**
  - Tool schemas come from type hints and docstrings, so the descriptions the model reads live next to the code. Rewording one docstring ("pass the topic as specifically as the student said it") fixed a real wrong-answer bug.
  - `ctx.headers` and `get_access_token()` made per-student history straightforward.
  - **The built-in authorization server is excellent.** I supplied storage and one sign-in page, and the SDK handled every OAuth endpoint and check. Account linking took about a day, including an end-to-end test with a second device.
  - Tool annotations (`readOnlyHint`, `destructiveHint`) let me mark "clear my history" as destructive.
- **What needs work:**
  - The v1-to-v2 rename (`FastMCP` to `MCPServer`) breaks most examples online and in AI assistants' training data (friction log #5).
  - Leaving `validate_token_resource` unset logs a deprecation warning that the quick-start examples don't cover (#7).
  - Mounting the MCP app inside another web app means running `session_manager.run()` yourself, because a mounted app's lifespan doesn't run. That's worth a sentence in the docs.
- **Onboarding:** quick. The first tool answered a real client over Streamable HTTP in the first session, once I found the v2 names.
- **Would I build with it again?** Yes, without hesitation. It's the most complete part of the stack.

## 4. Agent Skills (`SKILL.md`)

- **What I used it for:** `skills/syllabuddy/SKILL.md`, which tells any agent when to call each tool, how to pass topics and subjects, and how to report each verdict honestly.
- **What worked well:** it's plain Markdown with a short front-matter header, so the first version took minutes. It doubles as human documentation.
- **What needs work:** I couldn't test how Alexa+ itself loads or ranks a skill alongside an add-on's tool descriptions, so I don't know which one wins when they disagree. A note on that interplay would help.
- **Onboarding:** minutes.
- **Would I build with it again?** Yes. It's the cheapest way to make tool use more reliable.

## 5. Amazon Bedrock (Converse API)

- **What I used it for:** an optional "brain" for the simulated Alexa+: the agent can run on Bedrock's Converse API with tool use.
- **What worked well:** the Converse tool-use message shapes are well documented, so I implemented and tested them against a stubbed client, including several tool results in one turn.
- **What needs work:** I haven't run it live. My hackathon AWS credits arrived late in the submission window, and activating an AWS account still needs a payment card on file. As a student, I wasn't comfortable putting a card on a cloud account, so the demo uses Groq instead. **A card-free sandbox for hackathon entrants** (credits that work without a payment method, or a capped Bedrock quota) would let more students use Amazon's own models.
- **Onboarding:** reading the docs and implementing against them was quick; the live hello world was blocked by the account and payment setup.
- **Would I build with it again?** Yes. The code is written and tested; it only needs an account I'm comfortable activating.

## Other tools (not Amazon)

- **Groq API (OpenAI-compatible):** the demo's language model. It's fast, but the free tier's tokens-per-minute limit means about two voice turns a minute, so the agent falls back to answering straight from the syllabus when rate-limited.
- **fastembed (ONNX embeddings):** in-process embeddings with no server, which is right for a small add-on. The first model download hung on a fresh machine, so I replaced it with a direct HTTPS download.
- **PyMuPDF:** parsing the official SAT, ACT, AP, Alberta and A-Level PDFs. It's precise and fast, but table columns that share a baseline merge into one line, so I worked from text spans and indentation.

## Feature requests

1. **Critical:** public access to the Alexa AI CLI, or an allow-listing route for hackathon entrants.
2. **Critical:** documentation for Alexa+ account linking with MCP add-ons (client registration, redirect URIs, manifest fields), ideally with a sample authorization server.
3. **Important:** a hosted MCP inspector in the developer console: point it at a server URL and see which tools Alexa+ would choose for an utterance, before any deploy.
4. **Nice to have:** a way to test add-ons from countries where Alexa+ isn't sold, and Windows support for the CLI.
