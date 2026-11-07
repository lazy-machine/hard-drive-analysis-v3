"""Rank scored runs: python arena/leaderboard.py [--horizon 30] [--stage dev]. Prints
markdown and writes results/arena/<stage>-leaderboard.md, best run of each block first."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon", type=int, default=30)
    parser.add_argument("--stage", default="dev")
    args = parser.parse_args()
    record = ROOT / "results" / "arena" / f"{args.stage}-runs.jsonl"
    rows = [json.loads(line) for line in record.read_text().splitlines()]
    h = str(args.horizon)
    scored = [r for r in rows if r["state"] == "scored" and h in r.get("metrics", {})]
    best: dict[str, dict] = {}
    for r in scored:
        if r["block"] not in best or r["metrics"][h]["ap"] > best[r["block"]]["metrics"][h]["ap"]:
            best[r["block"]] = r
    lines = [f"# Arena leaderboard: {args.horizon}-day PR-AUC, {args.stage} split", "",
             "Best run per block. Gain is paired against baseline_lgbm; an interval that holds "
             "zero is a tie.", "",
             "| # | block | PR-AUC | 95% CI | gain | gain CI | ROC-AUC | recall @1% | O/E | "
             "Brier skill | fit min | RAM GiB | VRAM GiB | GPU % | run |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    ranked = sorted(best.values(), key=lambda r: -r["metrics"][h]["ap"])
    for i, r in enumerate(ranked, 1):
        m = r["metrics"][h]
        ci = "[{:.4f}, {:.4f}]".format(*m["ap_ci"])
        gain = f"{m['ap_gain']:+.4f}" if "ap_gain" in m else "-"
        gain_ci = "[{:+.4f}, {:+.4f}]".format(*m["ap_gain_ci"]) if "ap_gain_ci" in m else "-"
        lines.append(
            f"| {i} | {r['block']} | {m['ap']:.4f} | {ci} | {gain} | {gain_ci} | {m['auc']:.4f} | "
            f"{m['recall_at_1pct']:.3f} | {m['observed_over_expected']:.2f} | "
            f"{m['brier_skill']:.4f} | {r['fit_seconds'] / 60:.1f} | "
            f"{r.get('fit_peak_rss_gib', 0):.1f} | {r.get('vram_peak_gib', 0):.1f} | "
            f"{r.get('gpu_busy_mean', 0):.0f} | {Path(r['run_dir']).name} |")
    failed = [r for r in rows if r["state"] != "scored"]
    if failed:
        lines += ["", "## Failed runs", ""] + [
            f"- {Path(r['run_dir']).name}: {r['state']}" for r in failed]
    text = "\n".join(lines) + "\n"
    (ROOT / "results" / "arena" / f"{args.stage}-leaderboard.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
