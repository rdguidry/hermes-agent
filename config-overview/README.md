# Hermes Overview — showcase pack

A polished, shareable overview of this Hermes configuration. Three files:

| File | What it is |
|---|---|
| [`index.html`](./index.html) | Self-contained interactive page — architecture diagram, system cards, model/provider tables, **rendered spend table + observer charts**. No build step, no CDN, opens straight in a browser. |
| [`hermes-overview.md`](./hermes-overview.md) | Markdown companion (renders on GitHub) with a Mermaid architecture diagram and the same tables. |
| [`generate.py`](./generate.py) | Pulls your **real** telemetry into the page. Reads `~/.hermes/state.db` and (optionally) the NeMo Relay observer export. |

## Populate it with your real numbers

The page ships *wired but empty* — no figures are invented. Fill it in:

```bash
cd config-overview

# basic: last 30 days from the cost ledger, baked into a self-contained file
python generate.py --inject
open hermes-overview.html        # macOS  (xdg-open / start on Linux / Windows)

# add the fine function split (compression / title-gen / vision / transcription)
python generate.py --days 30 --atof ~/.hermes/relay --inject
```

`--inject` writes `hermes-overview.html` with the data baked in (best for
sharing a single file). Without it you get `hermes-overview-data.json`, which
`index.html` will fetch when served over http:

```bash
python generate.py            # writes hermes-overview-data.json
python -m http.server         # then open http://localhost:8000/index.html
```

## Data sources

- **`~/.hermes/state.db`** (`sessions` + `messages` tables) — authoritative
  per-session cost/token ledger. Gives daily spend by model, the main-vs-subagent
  function split, spend by platform, and tool-call frequency.
- **NeMo Relay ATOF JSONL** (optional, `--atof`) — per-request observer trace.
  Adds the fine intra-turn function split (compression, titles, vision,
  transcription, insights) keyed on the observer's `turn_type` / `api_mode`.

If a source is missing, its section renders an empty "run the generator" state.

## Options

```
python generate.py --help

  --db PATH      state.db location (default: ~/.hermes/state.db, or $HERMES_HOME)
  --days N       look-back window (default: 30)
  --atof PATH    NeMo Relay ATOF .jsonl file or directory (optional)
  --out PATH     output JSON path
  --inject       also write a self-contained hermes-overview.html
```

The same numbers are available live inside Hermes via `/usage` and
`/insights --days 30`.
