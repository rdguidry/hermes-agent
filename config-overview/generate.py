#!/usr/bin/env python3
"""Hermes Overview data generator.

Reads your real Hermes telemetry and emits the JSON that powers the showcase
page (``index.html``) and the spend tables in ``hermes-overview.md``.

Two data sources, joined into one ``hermes-overview-data.json``:

1. ``~/.hermes/state.db`` (SQLite, ``sessions`` + ``messages`` tables)
   ----------------------------------------------------------------------
   Authoritative per-session cost/token ledger. Gives us:
     * daily spend by model
     * daily spend by function  (main vs. subagent, split on parent_session_id)
     * spend by platform/source (cli, telegram, discord, ...)
     * tool-call frequency       (parsed from messages.tool_calls / tool_name)

2. NeMo Relay ATOF JSONL export (optional, ``--atof PATH``)
   ----------------------------------------------------------------------
   Per-API-request observer trace. Adds the *fine* function split that the
   session ledger cannot express on its own — the intra-turn auxiliary calls:
     compression, title generation, vision_analyze, transcription, insights.
   Grouped on the observer's ``turn_type`` / ``api_mode`` fields.

Nothing is fabricated: if a source is missing, its section is emitted empty and
the page renders a "no data yet — run the generator" state for it.

Usage
-----
    python generate.py                         # last 30 days, default DB
    python generate.py --days 7                # last 7 days
    python generate.py --db /path/to/state.db  # explicit DB
    python generate.py --atof ~/.hermes/relay  # also fold in observer trace
    python generate.py --inject                # also bake JSON into a
                                               # self-contained hermes-overview.html

The page reads data three ways, in order: an injected ``window.HERMES_DATA``
block (``--inject``), then a sibling ``hermes-overview-data.json`` over http,
then the built-in empty state.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Cost expression shared by every query: prefer provider-confirmed actuals,
# fall back to the estimate, then to zero. Matches Hermes' own /insights logic.
COST = "COALESCE(actual_cost_usd, estimated_cost_usd, 0)"


def default_db_path() -> Path:
    home = os.environ.get("HERMES_HOME")
    base = Path(home) if home else Path.home() / ".hermes"
    return base / "state.db"


def open_db(path: Path) -> sqlite3.Connection:
    if not path.exists():
        sys.exit(
            f"state.db not found at {path}\n"
            "Point at it with --db, or set HERMES_HOME. Run Hermes at least "
            "once so the ledger exists."
        )
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def q(con: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return list(con.execute(sql, params))


def fnum(v) -> float:
    return float(v) if v is not None else 0.0


# --------------------------------------------------------------------------- #
# state.db extraction
# --------------------------------------------------------------------------- #
def from_state_db(con: sqlite3.Connection, since: float) -> dict:
    cols = table_columns(con, "sessions")
    if not cols:
        return {}

    # main vs. subagent is expressible directly: a session with a parent is
    # delegated/subagent work, otherwise it is a top-level (main) turn stream.
    func_expr = (
        "CASE WHEN parent_session_id IS NULL THEN 'main' ELSE 'subagent' END"
        if "parent_session_id" in cols
        else "'main'"
    )
    day_expr = "date(started_at,'unixepoch','localtime')"

    daily_by_model = [
        dict(
            day=r["day"],
            model=r["model"] or "(unset)",
            sessions=r["sessions"],
            input_tokens=r["input_tokens"] or 0,
            output_tokens=r["output_tokens"] or 0,
            cache_read=r["cache_read"] or 0,
            cache_write=r["cache_write"] or 0,
            cost_usd=round(fnum(r["cost_usd"]), 6),
        )
        for r in q(
            con,
            f"""
            SELECT {day_expr} AS day, model,
                   COUNT(*) AS sessions,
                   SUM(input_tokens) AS input_tokens,
                   SUM(output_tokens) AS output_tokens,
                   SUM(cache_read_tokens) AS cache_read,
                   SUM(cache_write_tokens) AS cache_write,
                   SUM({COST}) AS cost_usd
            FROM sessions
            WHERE started_at >= ? AND archived = 0
            GROUP BY day, model
            ORDER BY day DESC, cost_usd DESC
            """,
            (since,),
        )
    ]

    daily_by_function = [
        dict(
            day=r["day"],
            function=r["function"],
            model=r["model"] or "(unset)",
            cost_usd=round(fnum(r["cost_usd"]), 6),
            input_tokens=r["input_tokens"] or 0,
            output_tokens=r["output_tokens"] or 0,
        )
        for r in q(
            con,
            f"""
            SELECT {day_expr} AS day, {func_expr} AS function, model,
                   SUM({COST}) AS cost_usd,
                   SUM(input_tokens) AS input_tokens,
                   SUM(output_tokens) AS output_tokens
            FROM sessions
            WHERE started_at >= ? AND archived = 0
            GROUP BY day, function, model
            ORDER BY day DESC, cost_usd DESC
            """,
            (since,),
        )
    ]

    by_model = [
        dict(
            model=r["model"] or "(unset)",
            sessions=r["sessions"],
            input_tokens=r["input_tokens"] or 0,
            output_tokens=r["output_tokens"] or 0,
            cache_read=r["cache_read"] or 0,
            cache_write=r["cache_write"] or 0,
            tool_calls=r["tool_calls"] or 0,
            cost_usd=round(fnum(r["cost_usd"]), 6),
            cost_status=r["cost_status"],
        )
        for r in q(
            con,
            f"""
            SELECT model,
                   COUNT(*) AS sessions,
                   SUM(input_tokens) AS input_tokens,
                   SUM(output_tokens) AS output_tokens,
                   SUM(cache_read_tokens) AS cache_read,
                   SUM(cache_write_tokens) AS cache_write,
                   SUM(tool_call_count) AS tool_calls,
                   SUM({COST}) AS cost_usd,
                   MAX(cost_status) AS cost_status
            FROM sessions
            WHERE started_at >= ? AND archived = 0
            GROUP BY model
            ORDER BY cost_usd DESC
            """,
            (since,),
        )
    ]

    by_platform = [
        dict(
            source=r["source"],
            sessions=r["sessions"],
            messages=r["messages"] or 0,
            tool_calls=r["tool_calls"] or 0,
            cost_usd=round(fnum(r["cost_usd"]), 6),
        )
        for r in q(
            con,
            f"""
            SELECT source,
                   COUNT(*) AS sessions,
                   SUM(message_count) AS messages,
                   SUM(tool_call_count) AS tool_calls,
                   SUM({COST}) AS cost_usd
            FROM sessions
            WHERE started_at >= ? AND archived = 0
            GROUP BY source
            ORDER BY cost_usd DESC
            """,
            (since,),
        )
    ]

    overview_row = q(
        con,
        f"""
        SELECT COUNT(*) AS sessions,
               SUM(input_tokens) AS input_tokens,
               SUM(output_tokens) AS output_tokens,
               SUM(cache_read_tokens) AS cache_read,
               SUM(cache_write_tokens) AS cache_write,
               SUM(tool_call_count) AS tool_calls,
               SUM(api_call_count) AS api_calls,
               SUM({COST}) AS cost_usd,
               MIN(started_at) AS first_ts,
               MAX(started_at) AS last_ts
        FROM sessions
        WHERE started_at >= ? AND archived = 0
        """,
        (since,),
    )[0]
    overview = dict(
        sessions=overview_row["sessions"] or 0,
        input_tokens=overview_row["input_tokens"] or 0,
        output_tokens=overview_row["output_tokens"] or 0,
        cache_read=overview_row["cache_read"] or 0,
        cache_write=overview_row["cache_write"] or 0,
        tool_calls=overview_row["tool_calls"] or 0,
        api_calls=overview_row["api_calls"] or 0,
        cost_usd=round(fnum(overview_row["cost_usd"]), 4),
        first_ts=overview_row["first_ts"],
        last_ts=overview_row["last_ts"],
    )

    tool_usage = _tool_usage(con, since)

    return dict(
        overview=overview,
        daily_by_model=daily_by_model,
        daily_by_function=daily_by_function,
        by_model=by_model,
        by_platform=by_platform,
        tool_usage=tool_usage,
    )


def _tool_usage(con: sqlite3.Connection, since: float) -> list[dict]:
    """Tool-call frequency from the messages table.

    Schema has varied across Hermes versions: prefer a ``tool_name`` column,
    fall back to parsing the ``tool_calls`` JSON blob.
    """
    mcols = table_columns(con, "messages")
    counts: dict[str, int] = defaultdict(int)

    join = (
        "JOIN sessions s ON s.id = m.session_id "
        "WHERE s.started_at >= ? AND s.archived = 0"
        if "session_id" in mcols
        else "WHERE 1=1"
    )
    params = (since,) if "session_id" in mcols else ()

    if "tool_name" in mcols:
        for r in q(
            con,
            f"SELECT m.tool_name AS t, COUNT(*) AS c FROM messages m {join} "
            "AND m.tool_name IS NOT NULL GROUP BY m.tool_name",
            params,
        ):
            counts[r["t"]] += r["c"]
    elif "tool_calls" in mcols:
        for r in q(con, f"SELECT m.tool_calls AS tc FROM messages m {join} "
                        "AND m.tool_calls IS NOT NULL", params):
            try:
                for call in json.loads(r["tc"]) or []:
                    name = (call.get("function") or {}).get("name") or call.get("name")
                    if name:
                        counts[name] += 1
            except (json.JSONDecodeError, AttributeError, TypeError):
                continue

    return [
        dict(tool=t, count=c)
        for t, c in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    ]


# --------------------------------------------------------------------------- #
# NeMo Relay ATOF (observer) extraction — fine function split
# --------------------------------------------------------------------------- #
# Map observer turn_type / api_mode onto human function labels.
TURN_TYPE_TO_FUNCTION = {
    "user": "main",
    "main": "main",
    "subagent": "subagent",
    "delegate": "subagent",
    "compression": "compression",
    "compress": "compression",
    "summary": "compression",
    "title": "title-gen",
    "title_gen": "title-gen",
    "vision": "vision",
    "vision_analyze": "vision",
    "transcription": "transcription",
    "stt": "transcription",
    "insights": "insights",
    "session_search": "insights",
}


def _atof_files(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(path.rglob("*.jsonl"))
    return [path] if path.exists() else []


def from_atof(path: Path, since: float) -> list[dict]:
    """Daily spend by fine-grained function from observer trace lines."""
    agg: dict[tuple, dict] = defaultdict(
        lambda: {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "calls": 0}
    )
    for fp in _atof_files(path):
        with fp.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = rec.get("timestamp") or rec.get("ts") or rec.get("time")
                if isinstance(ts, str):
                    try:
                        ts = time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
                    except ValueError:
                        ts = None
                if ts and ts < since:
                    continue
                day = (
                    time.strftime("%Y-%m-%d", time.localtime(ts))
                    if ts
                    else "(undated)"
                )
                turn = (rec.get("turn_type") or rec.get("api_mode") or "main").lower()
                function = TURN_TYPE_TO_FUNCTION.get(turn, turn)
                model = rec.get("model") or "(unset)"
                usage = rec.get("usage") or {}
                cost = rec.get("cost") or rec.get("cost_usd") or {}
                cost_usd = (
                    cost.get("total")
                    if isinstance(cost, dict)
                    else (cost if isinstance(cost, (int, float)) else 0.0)
                ) or 0.0
                key = (day, function, model)
                row = agg[key]
                row["cost_usd"] += float(cost_usd)
                row["input_tokens"] += int(usage.get("input", 0) or 0)
                row["output_tokens"] += int(usage.get("output", 0) or 0)
                row["calls"] += 1

    return [
        dict(day=d, function=f, model=m, cost_usd=round(v["cost_usd"], 6),
             input_tokens=v["input_tokens"], output_tokens=v["output_tokens"],
             calls=v["calls"])
        for (d, f, m), v in sorted(agg.items(), reverse=True)
    ]


# --------------------------------------------------------------------------- #
# Inject into a self-contained HTML
# --------------------------------------------------------------------------- #
def inject_html(data: dict) -> Path | None:
    src = HERE / "index.html"
    if not src.exists():
        print(f"  (skip --inject: {src} not found)")
        return None
    html = src.read_text(encoding="utf-8")
    marker = "window.HERMES_DATA = null; /*HERMES_DATA_INJECT*/"
    if marker not in html:
        print("  (skip --inject: injection marker not found in index.html)")
        return None
    payload = json.dumps(data, separators=(",", ":"))
    html = html.replace(marker, f"window.HERMES_DATA = {payload};")
    out = HERE / "hermes-overview.html"
    out.write_text(html, encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=default_db_path(),
                    help="Path to state.db (default: ~/.hermes/state.db)")
    ap.add_argument("--days", type=int, default=30,
                    help="Look-back window in days (default: 30)")
    ap.add_argument("--atof", type=Path, default=None,
                    help="NeMo Relay ATOF .jsonl file or directory (optional)")
    ap.add_argument("--out", type=Path, default=HERE / "hermes-overview-data.json",
                    help="Output JSON path")
    ap.add_argument("--inject", action="store_true",
                    help="Also write a self-contained hermes-overview.html")
    args = ap.parse_args()

    since = time.time() - args.days * 86400
    con = open_db(args.db)
    state = from_state_db(con, since)
    con.close()

    data = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "window_days": args.days,
        "sources": {"state_db": str(args.db), "atof": str(args.atof) if args.atof else None},
        **state,
        "fine_by_function": from_atof(args.atof, since) if args.atof else [],
    }

    args.out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    ov = data.get("overview", {})
    print(f"Wrote {args.out}")
    print(f"  window: last {args.days} days")
    print(f"  sessions: {ov.get('sessions', 0)}   spend: ${ov.get('cost_usd', 0):.2f}")
    print(f"  models: {len(data.get('by_model', []))}   "
          f"platforms: {len(data.get('by_platform', []))}   "
          f"tools: {len(data.get('tool_usage', []))}")
    if data["fine_by_function"]:
        print(f"  observer fine-function rows: {len(data['fine_by_function'])}")

    if args.inject:
        out = inject_html(data)
        if out:
            print(f"Wrote {out} (self-contained, open it directly)")


if __name__ == "__main__":
    main()
