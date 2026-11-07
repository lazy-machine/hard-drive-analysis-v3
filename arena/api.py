"""What a block gets. A block imports nothing from the harness except, if it wants, this."""

from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path

import numpy as np
import pandas as pd


class Part:
    """One set of rows: X (n, features) float32, hist (n, lags, columns) float16, both
    memory-mapped, and meta with serial_number, date, duration_days, event, weight."""

    def __init__(self, root: Path, name: str):
        self.root, self.name = root, name

    @cached_property
    def X(self) -> np.ndarray:
        return np.load(self.root / f"{self.name}.X.npy", mmap_mode="r")

    @cached_property
    def hist(self) -> np.ndarray:
        return np.load(self.root / f"{self.name}.hist.npy", mmap_mode="r")

    @cached_property
    def meta(self) -> pd.DataFrame:
        return pd.read_parquet(self.root / f"{self.name}.meta.parquet")


class FitData:
    """train: rows to learn from. stop: other drives, for early stopping and model choice.
    Both end at split.train_end, and labels are censored there."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.manifest = json.loads((self.root / "manifest.json").read_text())
        self.features: list[str] = self.manifest["features"]
        self.categorical: dict[str, list] = self.manifest["categorical"]
        self.groups: dict[str, list[str]] = self.manifest["groups"]
        self.bin_edges: list[int] = self.manifest["bin_edges"]
        self.lags: list[int] = self.manifest["lags"]
        self.hist_columns: list[str] = self.manifest["hist_columns"]
        self.train = Part(self.root, "train")
        self.stop = Part(self.root, "stop")
