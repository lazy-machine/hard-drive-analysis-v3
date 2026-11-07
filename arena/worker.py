"""One phase of a block run, in its own process: `worker.py fit|predict <block> <run dir>`.

run.py starts this. fit: loads the data, calls block.prepare (not timed), then block.fit
(timed). predict: calls block.predict on shuffled batches of held-out features.
"""

from __future__ import annotations

import importlib.util
import json
import os
import resource
import sys
import time
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).parent), str(Path(__file__).parent.parent / "steps")]
from api import FitData  # noqa: E402

BATCH = 100_000


def load_block(path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("block", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stamp(run: Path, **values) -> None:
    status = run / "status.json"
    current = json.loads(status.read_text()) if status.exists() else {}
    tmp = status.with_suffix(".tmp")
    tmp.write_text(json.dumps({**current, **values}))
    tmp.replace(status)


def peak_rss() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20


def log(*parts) -> None:
    print(f"[{time.strftime('%H:%M:%S')}]", *parts, flush=True)


def fit(block, run: Path, views: Path, budget: float) -> None:
    data = FitData(views / "fit")
    model_dir = run / "model"
    model_dir.mkdir(exist_ok=True)
    t = time.time()
    state = block.prepare(data, model_dir) if hasattr(block, "prepare") else None
    stamp(run, prepare_seconds=time.time() - t, fit_started=time.time())
    t = time.time()
    block.fit(data, model_dir, t + budget, state)
    stamp(run, fit_seconds=time.time() - t, fit_peak_rss_gib=peak_rss())


def predict(block, run: Path, views: Path) -> None:
    held = views / "heldout"
    model = block.load(run / "model")
    t = time.time()
    for name in ("cal", "score"):
        X = np.load(held / f"{name}.X.npy", mmap_mode="r")
        H = np.load(held / f"{name}.hist.npy", mmap_mode="r")
        parts = []
        for lo in range(0, len(X), BATCH):
            z = np.asarray(block.predict(model, np.array(X[lo:lo + BATCH]),
                                         np.array(H[lo:lo + BATCH])), dtype=np.float64)
            if z.shape[0] != min(BATCH, len(X) - lo) or not np.isfinite(z).all():
                raise ValueError(f"predict returned shape {z.shape} or non-finite values")
            parts.append(z)
        np.save(run / f"{name}.logits.npy", np.concatenate(parts))
        log(f"predicted {name}: {len(X)} rows")
    stamp(run, predict_seconds=time.time() - t)


def main() -> None:
    phase, block_path, run, views, budget = sys.argv[1:6]
    run, views = Path(run), Path(views)
    block = load_block(Path(block_path))
    if "torch" in sys.modules:   # keep room for the desktop and for smoke tests
        import torch

        if torch.cuda.is_available():
            total = torch.cuda.get_device_properties(0).total_memory
            torch.cuda.set_per_process_memory_fraction(
                min(1.0, float(os.environ["HDA_VRAM_GIB"]) * 2**30 / total))
    log(f"{phase} start, pid {os.getpid()}")
    if phase == "fit":
        fit(block, run, views, float(budget))
    else:
        predict(block, run, views)
    log(f"{phase} done")


if __name__ == "__main__":
    main()
