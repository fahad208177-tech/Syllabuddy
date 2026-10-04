# Product feedback (draft: rewrite in your own words before submitting)

## Alexa+ MCP Toolkit (docs) and Alexa AI CLI
- **Used for:** planning how Syllabuddy would ship as a real Alexa+ add-on (Streamable HTTP, OAuth 2.1 + PKCE, `addon.json`, the 500 ms latency budget).
- **Worked well:** building on the open MCP standard means the same server works with Alexa+, Claude, and any MCP client. The latency budget and transport requirements are stated clearly.
- **Needs work:** the CLI isn't installable without an allow-listed AWS account (see friction log #1); Windows isn't supported (#2); it's unclear whether developers outside Alexa+ marketplaces can test (#3).
- **Onboarding:** reading the docs was quick, but setup stopped at the CLI.
- **Would I build with it again?** Yes, once access is open. MCP makes it low-risk because nothing is Alexa-specific until deployment.

## Model Context Protocol (Streamable HTTP, Python SDK 2.3)
- **Used for:** the Syllabuddy server (8 tools) and the agent's client.
- **Worked well:** per-request headers on the context made per-student history easy; tool schemas are generated from type hints and docstrings.
- **Needs work:** the v1 to v2 rename (FastMCP to MCPServer) breaks most online examples.

## Agent Skills
- **Used for:** `skills/syllabuddy/SKILL.md`, which teaches agents when to call each tool and how to report verdicts.
- **Worked well:** a plain Markdown file, so writing it took minutes.

## Amazon Bedrock (Converse API): AWS Builder
- **Used for:** the "brain" of the simulated Alexa+ (`assistant/agent.py`, `BedrockBrain`), which takes the MCP tool list as Converse `toolConfig` and handles `toolUse` / `toolResult` blocks.
- **Status:** [fill in after running with real credentials: model used, latency, cost for the demo]
- **Worked well:** Converse handles tool use natively, so the same agent loop serves every model.
- **Needs work:** [fill in]

## Feature requests
1. **Critical:** public access to the Alexa AI CLI, or a hackathon allow-listing route.
2. **Important:** a hosted "MCP inspector" in the developer console that connects to a server URL and shows how Alexa+ would choose tools, before any deploy.
3. **Nice to have:** a way to test Alexa+ add-ons from non-Alexa+ countries.
