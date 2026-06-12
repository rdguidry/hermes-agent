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

## Next steps (where the session left off)

1. User to paste the crash output from the stderr log — 40 lines after the
   gateway's 19:02:00 spawn of apple-mail:
   ```bash
   n=$(grep -n "starting MCP server 'apple-mail'" ~/.hermes/logs/mcp-stderr.log | sed -n '3p' | cut -d: -f1); sed -n "${n},$((n+40))p" ~/.hermes/logs/mcp-stderr.log
   ```
2. Determine how the gateway is launched (LaunchAgent? login item? nohup from
   a terminal?) — that decides which app needs the TCC grant.
3. Likely fix: grant Automation → Mail (and possibly Full Disk Access) to the
   process responsible for the gateway in System Settings → Privacy &
   Security → Automation; or launch the gateway once from Terminal so the
   prompt can appear and be approved.

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
