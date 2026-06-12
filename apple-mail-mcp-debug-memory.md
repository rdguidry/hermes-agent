# Memory: apple-mail MCP not visible to the Hermes agent (debugging session 2026-06-12)

User: rdgstudio (macOS, RDGStudio). Hermes install: `/Users/rdgstudio/hermes-agent`
(venv), config/profile at `~/.hermes`. Problem as reported: "the agent is not
seeing iapple mail mcp" — the running Hermes agent has no `apple-mail` MCP tools.

## Current diagnosis (high confidence, awaiting final confirmation)

The `apple-mail` MCP server **dies shortly after spawn when launched by the
detached gateway**, but runs fine when spawned from the user's terminal.
Signature of a macOS TCC/Automation (Apple Events → Mail.app) denial: the
detached gateway (`hermes gateway run --replace`, no TTY) has a different TCC
identity than Terminal.app, cannot display a permission prompt, gets denied,
and `apple-mail-mcp` exits on the startup error. Gateway keeps retrying
(spawn headers at 17:01, 17:06, 19:02 on 2026-06-11) and the process is never
alive afterwards.

## Everything already verified (do NOT re-check these)

- Config entry is correct: `mcp_servers.apple-mail` at `~/.hermes/config.yaml:723`
  — absolute command `/Users/rdgstudio/.local/bin/apple-mail-mcp serve`,
  `APPLE_MAIL_READ_ONLY=true`, `enabled: true`.
- `hermes mcp test apple-mail` connects in ~600ms and lists 8 tools
  (server "Apple Mail, 3.4.0"): list_accounts, list_mailboxes, get_emails,
  get_email, get_email_links, get_email_attachment, get_attachment (deprecated),
  search.
- The 7-name `tools.include` list matches live tool names exactly — filter is fine.
- `hermes mcp test apple-mail-drafts` also works (1 tool: create_draft);
  that server is a custom python script and **stays alive** under the gateway.
- `platform_toolsets` (cli + telegram) lists no MCP server names and no
  `no_mcp` → no allowlist gating; all 10 MCP servers should be exposed.
- Process-list evidence (the smoking gun): gateway (pid 81147) + dashboard
  (pid 81185) each keep live children for apple-calendar, apple-mail-drafts,
  host-ops — but **no `apple-mail-mcp` process exists**, despite spawn
  headers for it in `~/.hermes/logs/mcp-stderr.log` at every gateway start.
- Earlier "terminal hangs" report resolved: user had typed the literal
  placeholder `hermes mcp test <server-name>` (zsh parse error) and/or the
  silent ≤40s connect window of `hermes mcp test`. Not a real hang.
- User already runs `log stream --predicate processImagePath contains
  "apple-mail-mcp" ...` since Monday — its output around a gateway start
  should show AppleEvents `-1743 not authorized` style denials.

## RESOLUTION (2026-06-12): Docker terminal backend was the root cause

The user's Hermes agent itself reported it: the Hermes terminal backend was set
to **docker**, and per the user's `apple-macos-integration` skill, Apple
ecosystem MCPs (Mail, Calendar, Notes, Messages) only work on a **local**
macOS backend — no JXA / `~/Library/Mail/V10` inside a Linux container. This
matches the observed evidence (apple-mail-mcp spawned and died on every
gateway start; survived when run from the user's terminal).

User chose: **switch backend back to local.** Steps given (run on Mac Studio):

1. `hermes setup terminal` → pick "Local" (or set `terminal.backend: "local"`
   in `~/.hermes/config.yaml`, block around line 181).
2. Restart gateway: `hermes gateway run --replace` — first restart in the
   FOREGROUND from Terminal so the macOS Automation prompt
   ("…wants to control Mail") can appear; approve it.
3. Verify: `pgrep -fl apple-mail-mcp` stays alive after ~1 min, and
   `grep "starting MCP server" ~/.hermes/logs/mcp-stderr.log | tail -8`.
   Then have the agent call `list_accounts`.

If it still dies on local backend: crash output is in mcp-stderr.log right
after the newest spawn header; next suspect is the Automation/Full Disk Access
grant in System Settings → Privacy & Security.

## Useful codebase facts learned (this repo)

- MCP discovery: `tools/mcp_tool.py` — `discover_mcp_tools()` is called by
  every entry point (CLI, TUI, gateway `gateway/run.py:16087`, cron). Connect
  failures are **logger.warning only**, invisible in chat.
- Stdio servers get a filtered env (`_build_safe_env`, `tools/mcp_tool.py:296`):
  PATH/HOME/XDG_* + per-server `env:` only.
- Stdio stderr goes to `~/.hermes/logs/mcp-stderr.log` with
  `===== [ts] starting MCP server '<name>' =====` headers (shared, interleaved).
- Per-platform MCP gating: `hermes_cli/tools_config.py:1499` — MCP servers are
  on for all platforms by default; listing any MCP server name in a platform's
  `platform_toolsets` entry flips it to an allowlist; `no_mcp` disables all.
- A server whose `tools.include` matches nothing registers zero tools and gets
  no toolset (docs: website/docs/user-guide/features/mcp.md "Tools not appearing").
- `hermes mcp test <name>`: silent up to ~40s (30s connect + 10s grace),
  bounded, exits cleanly (reproduced in sandbox). Bare `hermes mcp` opens an
  interactive curses picker (q/ESC to quit) — can look like a hang.
