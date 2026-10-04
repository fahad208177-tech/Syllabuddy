# Friction log (draft)

Real friction hit while building Syllabuddy, 4 October 2026, on Windows 11 in Singapore.
Edit these into your own words before submitting.

## 1. Alexa AI CLI install command returns 404

| | |
|---|---|
| **Task** | Install the Alexa AI CLI to scaffold an MCP add-on |
| **Steps** | Installed Node.js 24 LTS, ran `npm install -g @alexa-ai/cli` as shown in "Set Up Your Development Environment" |
| **Expected** | The CLI installs from npm |
| **Actual** | `npm error 404`. The package lives in a private AWS CodeArtifact registry (`--domain alexa-ai`, owner account 372468808636). Reaching it needs an IAM user that can assume `AddOn3PDeveloperToolsRead`, from an AWS account "provided to the Alexa Solutions Architect". This only becomes clear in Step 1 of the setup page, and the MCP Toolkit quickstart doesn't mention it. |
| **Severity** | High: it blocks deploying to Alexa+ at all |
| **Workaround** | Built the simulated Alexa+ experience the hackathon allows, against the same MCP server |
| **Suggestion** | Put "requires an allow-listed AWS account" at the very top of the quickstart, explain how hackathon entrants get allow-listed, or publish the CLI to public npm |

## 2. Windows isn't a supported OS for the CLI

| | |
|---|---|
| **Task** | Set up the Alexa+ add-on toolchain on a Windows laptop |
| **Expected** | Windows support, or WSL instructions |
| **Actual** | Prerequisites list only "macOS Sierra or higher or Ubuntu" |
| **Severity** | Medium: many students only have Windows |
| **Workaround** | None needed after #1; WSL would be the fallback |
| **Suggestion** | Support Windows, or document a tested WSL path |

## 3. Alexa+ isn't available in my country

| | |
|---|---|
| **Task** | Try my add-on on Alexa+ as a customer would |
| **Expected** | Some way to test from Singapore (simulator, developer override) |
| **Actual** | Alexa+ consumer availability is US, Canada, UK, Mexico, Germany, Austria, Italy, Spain and France. The docs say an account's "preferred marketplace" must be an Alexa+ marketplace, but not whether developers elsewhere can use the web simulator. |
| **Severity** | Medium: a global hackathon, but a regional product |
| **Workaround** | Simulated Alexa+ web app |
| **Suggestion** | State clearly whether developers outside Alexa+ marketplaces can use the web simulator |

## 4. Web simulator: no URL, and only after deploying

| | |
|---|---|
| **Task** | Find the Alexa+ web simulator to test early |
| **Actual** | "Test Your MCP Add-ons" says you must deploy first, and links on without giving a console URL |
| **Severity** | Low |
| **Suggestion** | Link the simulator directly, and allow testing an MCP server URL before a full deploy |

## 5. MCP Python SDK v2 renamed FastMCP

| | |
|---|---|
| **Task** | Write the MCP server in Python |
| **Actual** | `pip install mcp` installed 2.3.0, where `mcp.server.fastmcp.FastMCP` is now `mcp.server.mcpserver.MCPServer`. Most examples online (and in AI assistants' training data) use the v1 API. The SDK does raise a helpful error pointing at the migration guide. |
| **Severity** | Low |
| **Suggestion** | Amazon's MCP Toolkit samples could pin an SDK version or show v2 code |
