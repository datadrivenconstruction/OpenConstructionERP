# Connecting an AI client over MCP

OpenConstructionERP serves a Model Context Protocol (MCP) endpoint so that an external AI client, such as a desktop assistant or an IDE, can work with your projects. The client acts as you: it sees exactly the projects and records your role and project membership let you see, and it never changes anything on its own. Every change it suggests becomes a proposal that waits for you to apply it in the app.

## What the client can do

Read tools:

| Tool | What it returns |
|---|---|
| `list_projects` | Projects you own or are a team member of |
| `get_project_summary` | Status, phase, dates, budget and contract value of one project |
| `get_boq` | Positions and totals of a bill of quantities (money as decimal strings, in the project currency) |
| `search_cost_database` | Cost items matching a text query, optionally within a region |
| `get_schedule` | Schedule activities and the critical path as of the last CPM calculation |
| `get_validation_results` | The latest validation reports of a project |
| `get_site_issues_summary` | Counts by status and the oldest open RFIs, submittals and punch items |
| `list_documents` | Document metadata (no file contents); folder permissions apply |
| `get_risk_register` | Risks with probability, impact, score and mitigation |

Proposal tools are the same `propose_*` actions the in-app assistant uses (add or update a BOQ position, create a task, RFI, risk or punch item, update schedule progress). Each call must carry a `confidence` between 0 and 1 and a one-line `rationale`. The call stores a proposal and nothing else; it appears in the assistant's Changes view marked "via external AI client", where you apply, edit or reject it. Applying runs the same permission and project checks as doing the change by hand.

A tool only shows up when your role holds the module's read permission and the module is enabled on the server. Proposal tools only show up for a token created with "May propose changes".

## Set it up

1. Open Settings, Integrations, "AI clients (MCP)" (or go to `/settings?tab=mcp`).
2. Tick "Allow AI clients to connect". Optionally change the number of tool calls allowed per minute (1 to 600, default 60).
3. Create a token: give it a name, pick an expiry, and decide whether it may propose changes. The token and a ready-made client configuration are shown once. Copy them now.
4. Paste the configuration into the MCP server list of your client and restart the client.

The configuration has this shape:

```json
{
  "mcpServers": {
    "openconstructionerp": {
      "type": "http",
      "url": "https://your-server.example.com/api/v1/mcp",
      "headers": { "Authorization": "Bearer oe_..." }
    }
  }
}
```

Clients that cannot set an `Authorization` header may send the token as `X-API-Key` instead.

## Check the connection

```bash
curl -s -X POST https://your-server.example.com/api/v1/mcp \
  -H "Authorization: Bearer $OCE_MCP_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"check","version":"1"}}}'
```

A working setup answers with `serverInfo.name` set to `openconstructionerp`. Then try `{"jsonrpc":"2.0","id":2,"method":"tools/list"}`.

## Transport details

- Streamable HTTP, `POST /api/v1/mcp` (with or without a trailing slash). Every request is answered with a single `application/json` body; notifications get `202 Accepted`. `GET` answers `405`: the server never pushes messages.
- Supported protocol versions: `2025-06-18`, `2025-03-26`, `2024-11-05`. An unsupported `MCP-Protocol-Version` header is refused with `400`.
- Stateless: no `Mcp-Session-Id` is issued. Batches of JSON-RPC messages are accepted.
- Methods: `initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call`.
- Browser requests from an origin other than the server's own or the configured `ALLOWED_ORIGINS` are refused.

## Tokens, limits and audit

- An MCP token is a personal API key that carries the `mcp.access` scope (and `mcp.propose` when it may propose). A general API key cannot use the MCP endpoint, and an MCP token cannot call the REST routes that accept API keys.
- A token stops working at once when you revoke it, when it expires, or when you untick "Allow AI clients to connect".
- Calls over the per-minute budget are refused with HTTP `429` and JSON-RPC error `-32001`.
- Every tool call is written to the audit log (`module = mcp`): tool, outcome, duration, token prefix and project, never the argument values. The settings card lists your recent calls, and the checks there warn about tokens without expiry, tokens nobody uses, too many tokens, and a burst of refused calls.
