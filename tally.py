#!/usr/bin/env python3
"""Tally result codes friends sent back from the blind test.

Paste the WhatsApp messages (any surrounding chat text is fine) into codes.txt,
then run:  python3 tally.py            (reads codes.txt)
           python3 tally.py --json     (also writes results.json)
           pbpaste | python3 tally.py - (read codes from stdin)

Needs key.json from build.py (local only). Prints a plain table and writes
results.md with the same content.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE_RE = re.compile(r"AUDORA1\s+(.*?)\s*\|((?:\s*[nam][sha]\s+(?:[0-9a-f]+|x)/[0-9a-f]+\s*\|?)+)", re.I)
PART_RE = re.compile(r"([nam])([sha])\s+([0-9a-f]+|x)/([0-9a-f]+)", re.I)
CHAR = {"n": "narrator", "a": "armitage", "m": "molly"}
EMO = {"s": "sad", "h": "happy", "a": "angry"}


def load_key() -> tuple[int, dict[str, str], dict[str, dict]]:
    p = HERE / "key.json"
    if not p.is_file():
        sys.exit("key.json not found next to tally.py; run build.py first (it is local only, never committed)")
    k = json.loads(p.read_text())
    return int(k.get("prefix_len", 4)), k["arm_labels"], k["clips"]


def parse(text: str) -> list[tuple[str, list[tuple[str, str, str, str]]]]:
    """-> [(name, [(char, emo, q1_prefix|'x', q2_prefix), ...]), ...], deduplicated."""
    out, seen = [], set()
    for m in CODE_RE.finditer(text):
        name, body = m.group(1).strip(), m.group(2)
        parts = [(CHAR[c.lower()], EMO[e.lower()], q1.lower(), q2.lower()) for c, e, q1, q2 in PART_RE.findall(body)]
        if not parts:
            continue
        sig = (name.lower(), tuple(parts))
        if sig in seen:
            continue
        seen.add(sig)
        out.append((name, parts))
    return out


def pct(n: int, d: int) -> str:
    return f"{(100 * n / d):3.0f}%" if d else "  -"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", default="codes.txt", help="file with pasted messages, or - for stdin")
    ap.add_argument("--json", action="store_true", help="also write results.json")
    args = ap.parse_args()

    text = sys.stdin.read() if args.source == "-" else Path(args.source).read_text()
    plen, labels, clips = load_key()
    resolve = {cid[:plen]: meta for cid, meta in clips.items()}

    sessions = parse(text)
    if not sessions:
        print("no AUDORA1 codes found")
        return 1

    arms = list(labels)                      # stable order from build.py
    emo_hits = Counter()                     # arm -> picked as most <emotion>
    pref_hits = Counter()                    # arm -> rather listen to
    by_char = defaultdict(lambda: {"emo": Counter(), "pref": Counter(), "n": 0})
    by_emo = defaultdict(lambda: {"emo": Counter(), "n": 0})
    lines = cant_tell = bad = 0

    for _name, parts in sessions:
        for char, emo, q1, q2 in parts:
            a2 = resolve.get(q2)
            a1 = None if q1 == "x" else resolve.get(q1)
            if a2 is None or (q1 != "x" and a1 is None):
                bad += 1
                continue
            lines += 1
            by_char[char]["n"] += 1
            by_emo[emo]["n"] += 1
            pref_hits[a2["arm"]] += 1
            by_char[char]["pref"][a2["arm"]] += 1
            if a1 is None:
                cant_tell += 1
            else:
                emo_hits[a1["arm"]] += 1
                by_char[char]["emo"][a1["arm"]] += 1
                by_emo[emo]["emo"][a1["arm"]] += 1

    w = max(len(v) for v in labels.values()) + 2
    cant = "Can't tell"
    rows = [
        f"Friends who answered: {len(sessions)}     Lines judged: {lines}" + (f"     (unreadable: {bad})" if bad else ""),
        "",
        f"{'Voice':<{w}} {'Picked as most emotional':>26}   {'Would rather listen to':>24}",
    ]
    for arm in arms:
        rows.append(f"{labels[arm]:<{w}} {pct(emo_hits[arm], lines):>8}  ({emo_hits[arm]}/{lines})        {pct(pref_hits[arm], lines):>8}  ({pref_hits[arm]}/{lines})")
    rows.append(f"{cant:<{w}} {pct(cant_tell, lines):>8}  ({cant_tell}/{lines})        {'-':>8}")
    rows += ["", "Chance level is 33%. Each friend heard 3 lines, one per character, 3 voices per line, order shuffled."]

    rows += ["", "By character (most emotional / rather listen):"]
    for char in ("narrator", "armitage", "molly"):
        d = by_char[char]
        if not d["n"]:
            continue
        cells = "   ".join(f"{labels[a].split()[0]} {d['emo'][a]}/{d['n']} {d['pref'][a]}/{d['n']}" for a in arms)
        rows.append(f"  {char:<9} {cells}")
    rows += ["", "By emotion (picked as most that emotion):"]
    for emo in ("sad", "happy", "angry"):
        d = by_emo[emo]
        if not d["n"]:
            continue
        cells = "   ".join(f"{labels[a].split()[0]} {d['emo'][a]}/{d['n']}" for a in arms)
        rows.append(f"  {emo:<9} {cells}")

    def leader(c: Counter) -> str:
        if not lines:
            return "no data yet"
        ranked = c.most_common()
        if not ranked:
            return "no clear winner"
        top, n = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0
        if n / lines < 0.45 or n - second < 2:
            return f"no clear winner (leader {labels[top]} at {n} of {lines})"
        return f"{labels[top]} on {n} of {lines} lines"

    rows += ["", f"Verdict: most emotional = {leader(emo_hits)}; rather listen to = {leader(pref_hits)}."]

    report = "\n".join(rows)
    print(report)
    (HERE / "results.md").write_text("```\n" + report + "\n```\n")
    if args.json:
        (HERE / "results.json").write_text(json.dumps({
            "friends": len(sessions), "lines": lines, "cant_tell": cant_tell, "unreadable": bad,
            "most_emotional": dict(emo_hits), "rather_listen": dict(pref_hits),
            "by_character": {c: {"n": d["n"], "emo": dict(d["emo"]), "pref": dict(d["pref"])} for c, d in by_char.items()},
            "by_emotion": {e: {"n": d["n"], "emo": dict(d["emo"])} for e, d in by_emo.items()},
            "names": [n for n, _ in sessions],
        }, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
