#!/usr/bin/env python3
"""Build the friends blind listening test.

Reads the three arms' 3x3 emokit renders from the pipeline-dispatcher checkout,
loudness-normalises and transcodes each to AAC m4a, names every clip by a hash
of its bytes so nothing in the public site identifies an engine, and writes:

  clips/<id>.m4a   27 anonymised clips (folder is rebuilt from scratch)
  trials.json      public manifest: cells, texts, emotion, 3 clip ids each
  key.json         LOCAL ONLY (gitignored): clip id -> arm / char / emo

Usage: python3 build.py [--repo PATH] [--whatsapp 91XXXXXXXXXX] [--bitrate 96k]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_REPO = Path("/Users/srikanth/Audora/pipeline-dispatcher")

# arm key -> (label shown in tally output, source dir relative to repo)
ARMS: dict[str, tuple[str, str]] = {
    "indextts": ("IndexTTS-2.5", "output/tts_eval/emokit/indextts_spkref_emotext"),
    "qwen_instruct": ("Qwen clone + instruct", "output/tts_eval/emokit/qwen_clone_instruct_full"),
    "production": ("Production (today)", "trial/qwen_voicedesign/out/emokit"),
}

# Same order and texts as trial/vc_shootout/qwen_clone_instruct/cells.py on
# branch trial/qwen-clone-vs-elevenlabs-r8-r10. Copied so this kit stands alone.
CELLS: list[tuple[str, str, str]] = [
    ("narrator", "sad",
     "He never came home last night. I keep looking at the door, waiting for it to open, "
     "and it never does. I don't think he's coming back this time."),
    ("narrator", "happy",
     "The letter came on a Tuesday, of all days. I read it twice standing in the doorway, "
     "then once more sitting down, because my knees had stopped being reliable. Good news "
     "still does that to me."),
    ("narrator", "angry",
     "They had every chance to tell the truth, and they chose the lie, every single time. "
     "I am done making excuses for them. Whatever happens next, they brought it on themselves."),
    ("armitage", "angry",
     "You knew. You knew the whole time, and you let me stand there like a fool. Don't you "
     "dare tell me it was for my own good."),
    ("armitage", "sad",
     "I used to think there would be time to make it right. There isn't. There never was. "
     "I just kept telling myself a story so I could sleep."),
    ("armitage", "happy",
     "It worked. After everything they said, after every door they closed, it actually "
     "worked. Pour yourself a drink, Case. Tonight we celebrate."),
    ("molly", "happy",
     "They said yes! After all these months of waiting, they finally said yes! I can hardly "
     "hold this letter still long enough to read it again."),
    ("molly", "sad",
     "I waited at the station until the last train left. He wasn't on it. I knew he wouldn't "
     "be, and I waited anyway. That's the part I can't forgive."),
    ("molly", "angry",
     "Say that again. Go on, say it to my face this time instead of behind my back. I've had "
     "it with you, and I've had it with your excuses."),
]

CHAR_LABELS = {"narrator": "The Narrator", "armitage": "Armitage", "molly": "Molly"}

# What the public done screen calls each arm (user chose to show model names).
PUBLIC_LABELS = {arm: label for arm, (label, _) in ARMS.items()}


def transcode(src: Path, dst: Path, bitrate: str) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
        "-af", "loudnorm=I=-18:TP=-1.5:LRA=11",
        "-ac", "1", "-c:a", "aac", "-b:a", bitrate, "-movflags", "+faststart", str(dst),
    ]
    subprocess.run(cmd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    ap.add_argument("--whatsapp", default="", help="number with country code, no plus, e.g. 91XXXXXXXXXX")
    ap.add_argument("--bitrate", default="96k")
    ap.add_argument("--seed", type=int, default=20261008, help="fixed shuffle seed for clip order in trials.json")
    args = ap.parse_args()

    if shutil.which("ffmpeg") is None:
        print("ffmpeg not found on PATH", file=sys.stderr)
        return 2

    # 1. check every source exists before touching anything
    missing = []
    sources: dict[tuple[str, str, str], Path] = {}
    for arm, (_, rel) in ARMS.items():
        for char, emo, _ in CELLS:
            p = args.repo / rel / f"{char}_{emo}.wav"
            if not p.is_file():
                missing.append(str(p))
            sources[(arm, char, emo)] = p
    if missing:
        print("missing source clips:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 1

    # 2. transcode + hash into a fresh clips/ folder
    clips_dir = HERE / "clips"
    if clips_dir.exists():
        shutil.rmtree(clips_dir)
    clips_dir.mkdir()
    tmp = HERE / ".build_tmp.m4a"

    key: dict[str, dict] = {}
    by_cell: dict[tuple[str, str], dict[str, str]] = {}
    for (arm, char, emo), src in sources.items():
        transcode(src, tmp, args.bitrate)
        data = tmp.read_bytes()
        cid = hashlib.sha256(data).hexdigest()[:8]
        if cid in key:
            print(f"hash collision on {cid}; rerun", file=sys.stderr)
            return 1
        (clips_dir / f"{cid}.m4a").write_bytes(data)
        key[cid] = {"arm": arm, "char": char, "emo": emo}
        by_cell.setdefault((char, emo), {})[arm] = cid
        print(f"{arm:14s} {char:9s} {emo:6s} -> {cid}.m4a {len(data)//1024} KB")
    tmp.unlink(missing_ok=True)

    # 3. shortest unique prefix (the result code uses it)
    plen = 4
    while len({c[:plen] for c in key}) < len(key):
        plen += 1
    if plen > 5:
        print(f"warning: needed {plen}-char prefixes", file=sys.stderr)

    # 4. public manifest, clip order shuffled with a fixed seed
    rng = random.Random(args.seed)
    cells_out = []
    for char, emo, text in CELLS:
        ids = list(by_cell[(char, emo)].values())
        rng.shuffle(ids)
        cells_out.append({
            "id": f"{char}_{emo}", "char": char, "char_label": CHAR_LABELS[char],
            "emo": emo, "text": text, "clips": ids,
        })
    manifest = {"version": 1, "prefix_len": plen, "whatsapp": args.whatsapp, "cells": cells_out}
    (HERE / "trials.json").write_text(json.dumps(manifest, indent=1) + "\n")

    key_out = {
        "prefix_len": plen,
        "arm_labels": {k: v[0] for k, v in ARMS.items()},
        "clips": key,
    }
    (HERE / "key.json").write_text(json.dumps(key_out, indent=1) + "\n")
    reveal = {cid: PUBLIC_LABELS[meta["arm"]] for cid, meta in key.items()}
    (HERE / "reveal.json").write_text(json.dumps(reveal, indent=1) + "\n")

    total_kb = sum(p.stat().st_size for p in clips_dir.iterdir()) // 1024
    print(f"\n{len(key)} clips, {total_kb} KB total, prefix length {plen}")
    print("wrote trials.json + reveal.json (public) and key.json (LOCAL ONLY, gitignored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
