"""Run one block: fit under a time limit, predict, calibrate, score, record.

  python arena/run.py <block> --smoke            anyone: small data, 2 CPU threads, minutes
  HDA_COORDINATOR=1 python arena/run.py <block>  full data, one run at a time

The block is blocks/<block>/block.py under the current directory. Data, runs and results
always live in the main checkout (ROOT), so this works the same from a worktree.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("HDA_ROOT", "/home/lazy/Projects/hard-drive-analysis-v3"))
sys.path[:0] = [str(Path(__file__).parent), str(Path(__file__).parent.parent / "steps")]

GPU = Path("/sys/class/drm/card1/device")
GRACE = 60        # seconds after the deadline before a fit is killed
PHASE_LIMIT = 3600
FULL = {"cpus": "0-13", "threads": 14, "memory": "26G", "vram": 13.5, "lock": "/tmp/hda-run.lock"}
SMOKE = {"cpus": "14-15", "threads": 2, "memory": "5G", "vram": 1.5, "lock": "/tmp/hda-smoke.lock"}


def read_gpu() -> tuple[float, float]:
    try:
        return (int((GPU / "mem_info_vram_used").read_text()) / 2**30,
                float((GPU / "gpu_busy_percent").read_text()))
    except OSError:
        return 0.0, 0.0


def phase(name: str, block: Path, run: Path, views: Path, budget: float, cfg: dict) -> dict:
    """Run a worker phase, watch its clock and the GPU, and return what happened."""
    env = {**os.environ, "HDA_THREADS": str(cfg["threads"]), "OMP_NUM_THREADS": str(cfg["threads"]),
           "HDA_VRAM_GIB": str(cfg["vram"]), "PYTHONUNBUFFERED": "1"}
    worker = Path(__file__).parent / "worker.py"
    command = ["systemd-run", "--user", "--scope", "-q", "-p", f"MemoryMax={cfg['memory']}",
               "-p", "MemorySwapMax=0", "taskset", "-c", cfg["cpus"], "nice", "-n",
               str(cfg.get("nice", 0)), sys.executable, str(worker), name, str(block), str(run),
               str(views), str(budget)]
    idle_vram = read_gpu()[0]
    vram_peak, busy, killed = 0.0, [], None
    started = time.time()
    with open(run / f"{name}.log", "a") as out:
        child = subprocess.Popen(command, stdout=out, stderr=subprocess.STDOUT, env=env,
                                 start_new_session=True)
        while child.poll() is None:
            time.sleep(2)
            status = run / "status.json"
            info = json.loads(status.read_text()) if status.exists() else {}
            fit_started = info.get("fit_started")
            if name == "fit" and fit_started and "fit_seconds" not in info:
                used, load = read_gpu()
                vram_peak = max(vram_peak, used - idle_vram)
                busy.append(load)
                if time.time() - fit_started > budget + GRACE:
                    killed = "time limit"
            if time.time() - started > PHASE_LIMIT + budget:
                killed = "phase limit"
            if killed:
                os.killpg(child.pid, signal.SIGKILL)
                break
        code = child.wait()
    return {"exit": code, "killed": killed, "vram_peak_gib": round(vram_peak, 2),
            "gpu_busy_mean": round(sum(busy) / len(busy), 1) if busy else 0.0}


def tail(path: Path, lines: int = 25) -> str:
    return "\n".join(path.read_text(errors="replace").splitlines()[-lines:]) if path.exists() else ""


def next_run(runs: Path, block: str) -> Path:
    runs.mkdir(parents=True, exist_ok=True)
    n = 1 + max((int(p.name.rsplit("-", 1)[1]) for p in runs.glob(f"{block}-*")), default=0)
    run = runs / f"{block}-{n:03d}"
    run.mkdir()
    return run


def latest_reference(record: Path, reference: str) -> Path | None:
    if not record.exists():
        return None
    rows = [json.loads(line) for line in record.read_text().splitlines()]
    done = [r for r in rows if r["block"] == reference and r["state"] == "scored"]
    return Path(done[-1]["run_dir"]) if done else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("block")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--budget", type=float, default=None, help="fit seconds")
    parser.add_argument("--note", default="")
    parser.add_argument("--stage", default="dev", help="dev, or final for the real split")
    args = parser.parse_args()
    if not args.smoke and os.environ.get("HDA_COORDINATOR") != "1":
        sys.exit("Full runs belong to the coordinator. Use --smoke.")

    block = Path("blocks") / args.block / "block.py"
    if not block.exists():
        sys.exit(f"{block} not found (run from the checkout that holds your block)")
    block = block.resolve()
    cfg = {**SMOKE, "nice": 19} if args.smoke else FULL
    budget = args.budget or (240 if args.smoke else 1200)
    stage = ROOT / "build" / args.stage
    views = stage / "views" / "smoke" if args.smoke else stage / "views"
    runs = Path("/tmp/hda-smoke-runs") if args.smoke else stage / "runs"
    record = ROOT / "results" / "arena" / f"{args.stage}-runs.jsonl"

    lock = open(cfg["lock"], "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        if args.smoke:
            print("another smoke test is running, waiting for it...", flush=True)
        fcntl.flock(lock, fcntl.LOCK_EX)

    from api import FitData
    from scoring import score_run

    run = next_run(runs, args.block)
    shutil.copy(block, run / "block.py")
    entry = {"block": args.block, "run_dir": str(run), "budget": budget, "note": args.note,
             "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    fit = phase("fit", block, run, views, budget, cfg)
    status = json.loads((run / "status.json").read_text()) if (run / "status.json").exists() else {}
    entry.update(status, **{k: fit[k] for k in ("vram_peak_gib", "gpu_busy_mean")})
    entry.pop("fit_started", None)
    if fit["killed"] or fit["exit"] != 0 or "fit_seconds" not in status:
        entry["state"] = f"fit failed: {fit['killed'] or 'exit ' + str(fit['exit'])}"
    else:
        pred = phase("predict", block, run, views, budget, cfg)
        status = json.loads((run / "status.json").read_text())
        entry["predict_seconds"] = status.get("predict_seconds")
        if pred["killed"] or pred["exit"] != 0:
            entry["state"] = f"predict failed: {pred['killed'] or 'exit ' + str(pred['exit'])}"
        else:
            edges = FitData(views / "fit").bin_edges
            own = args.smoke or args.block == "baseline_lgbm"
            reference = None if own else latest_reference(record, "baseline_lgbm")
            entry["metrics"] = score_run(run, views, edges, reference)
            entry["state"] = "scored"
    if not args.smoke:
        record.parent.mkdir(parents=True, exist_ok=True)
        with open(record, "a") as fh:
            fh.write(json.dumps(entry) + "\n")
    print(json.dumps(entry, indent=1))
    if entry["state"] != "scored":
        print("--- fit.log\n" + tail(run / "fit.log"))
        print("--- predict.log\n" + tail(run / "predict.log"))
        sys.exit(1)


if __name__ == "__main__":
    main()
