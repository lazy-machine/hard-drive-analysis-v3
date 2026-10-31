"""Neural engines: logistic-hazard networks in PyTorch, on the ROCm GPU when there is one.

The discrete-time hazard of the reference model (Gensheimer & Narasimhan 2018, Kvamme &
Borgan 2021): one output per bin, trained on the snapshots with a mask of the bins each
one is at risk in, which gives the same likelihood as the person-period rows of
survival.expand without building them. Data, weights, early-stopping drives, calibration
and metadata are shared with the tree engines through engines.run.

params.torch.arch.type:
- "linear": one coefficient vector shared by every bin plus a per-bin intercept, the
  classic proportional-odds discrete-time model;
- "mlp": embeddings for the categorical features and an MLP over everything;
- "gru": the MLP plus a GRU over each snapshot's last days of daily SMART readings
  (PanelWindows), joined before the output layer.
arch.encoding = "ple" replaces each numerical input by its piecewise-linear encoding over
`bins` quantile bins of the train values (Gorishniy, Rubachev & Babenko 2022, "On
Embeddings for Numerical Features in Tabular Deep Learning"): an MLP sees thresholds the
way a tree does.

Mixed precision: bf16 autocast for training (fp32 matrix products are slow on RDNA3);
the GRU runs in fp32.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from common import val_roles
from engines import CHUNK, _threads, dense_targets, run

SEQ_CHUNK = 16_384      # rows per inference pass of a sequence model (GPU workspace)


def train(ctx):
    """A torch engine step."""
    if ctx.params["engine"] != "torch":
        raise ValueError("neural:train fits the torch engine only")
    return run(ctx, _fit_torch)


def _device(want: str):
    import torch

    if want == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(want)


class Prep:
    """Feature scaling fitted on train: signed log1p of every numerical feature (SMART
    counters span 0 to 1e13), standardized, missing set to 0 with an indicator column for
    each feature that has missing values in train; categorical codes stay integers."""

    def __init__(self, numeric, categorical, cards, mean, std, missing, edges=None):
        self.numeric, self.categorical, self.cards = numeric, categorical, cards
        self.mean, self.std, self.missing = mean, std, missing
        self.edges = edges      # (numerical features, bins + 1) quantiles, scaled space

    @classmethod
    def fit(cls, X, features, categorical, schema, bins: int = 0):
        numeric = [j for j, f in enumerate(features) if f not in categorical]
        cat = [features.index(f) for f in categorical]
        cards = [len(schema["categorical"][f]) for f in categorical]
        v = _signed_log(X[:, numeric])
        mean = np.nan_to_num(np.nanmean(v, axis=0))
        std = np.nan_to_num(np.nanstd(v, axis=0))
        std[std < 1e-6] = 1.0
        missing = [i for i in range(len(numeric)) if np.isnan(X[:, numeric[i]]).any()]
        edges = None
        if bins:
            z = (v - mean) / std
            q = np.linspace(0, 1, bins + 1)
            edges = np.stack([np.nanquantile(z[:, i], q) if (~np.isnan(z[:, i])).any()
                              else np.zeros(bins + 1) for i in range(z.shape[1])])
            edges = np.nan_to_num(edges).astype(np.float32)
        return cls(numeric, cat, cards, mean.astype(np.float32), std.astype(np.float32),
                   missing, edges)

    def transform(self, X) -> tuple[np.ndarray, np.ndarray]:
        v = (_signed_log(X[:, self.numeric]) - self.mean) / self.std
        isnan = np.isnan(v)
        flags = isnan[:, self.missing].astype(np.float32)
        v[isnan] = 0.0
        num = np.hstack([v, flags]).astype(np.float32)
        cat = X[:, self.categorical].astype(np.int64) if self.categorical else \
            np.zeros((X.shape[0], 0), np.int64)
        return num, cat

    @property
    def n_num(self) -> int:
        return len(self.numeric) + len(self.missing)

    def state(self) -> dict:
        import torch

        out = {"numeric": self.numeric, "categorical": self.categorical, "cards": self.cards,
               "mean": torch.from_numpy(self.mean), "std": torch.from_numpy(self.std),
               "missing": self.missing}
        if self.edges is not None:
            out["edges"] = torch.from_numpy(self.edges)
        return out

    @classmethod
    def from_state(cls, s):
        return cls(list(s["numeric"]), list(s["categorical"]), list(s["cards"]),
                   s["mean"].numpy(), s["std"].numpy(), list(s["missing"]),
                   s["edges"].numpy() if "edges" in s else None)


def _signed_log(v):
    return np.sign(v) * np.log1p(np.abs(v))


def _hazard_net(prep: Prep, K: int, arch: dict, n_channels: int = 0):
    """The network: embeddings + an MLP (or one shared linear score) over the snapshot
    features; with `n_channels`, a GRU over the daily window joins the MLP's output."""
    import torch
    from torch import nn

    n_num, cards = prep.n_num, prep.cards
    ple = arch.get("encoding") == "ple"
    if ple and prep.edges is None:
        raise ValueError("a piecewise-linear encoding needs Prep fitted with bins")

    class HazardNet(nn.Module):
        def __init__(self):
            super().__init__()
            kind = arch["type"]
            emb = [1 if kind == "linear" else min(16, (c + 1) // 2) for c in cards]
            self.emb = nn.ModuleList(nn.Embedding(c, d) for c, d in zip(cards, emb, strict=True))
            width = n_num + sum(emb)
            self.ple = ple
            if ple:
                e = torch.from_numpy(prep.edges)
                self.register_buffer("left", e[:, :-1].clone())
                self.register_buffer("width", (e[:, 1:] - e[:, :-1]).clamp(min=1e-6))
                self.n_values = e.shape[0]
                width += self.n_values * (e.shape[1] - 2)    # one value -> `bins` values
            if kind == "linear":
                self.body = nn.Identity()
                self.shared = nn.Linear(width, 1, bias=False)
                self.bias = nn.Parameter(torch.zeros(K))
            elif kind in ("mlp", "gru"):
                layers, d = [], width
                for h in arch["hidden"]:
                    layers += [nn.Linear(d, h), nn.LayerNorm(h), nn.SiLU(),
                               nn.Dropout(arch.get("dropout", 0.0))]
                    d = h
                self.body = nn.Sequential(*layers)
                if kind == "gru":
                    self.rnn = nn.GRU(n_channels, arch["rnn_hidden"], batch_first=True)
                    d += arch["rnn_hidden"]
                self.head = nn.Linear(d, K)
            else:
                raise ValueError(f"unknown torch arch '{kind}' (linear, mlp, gru)")
            self.kind = kind

        def forward(self, num, cat, seq=None):
            if self.ple:
                v = num[:, :self.n_values]
                enc = ((v[:, :, None] - self.left) / self.width).clamp(0.0, 1.0)
                num = torch.cat([enc.flatten(1), num[:, self.n_values:]], dim=1)
            x = torch.cat([num] + [e(cat[:, j]) for j, e in enumerate(self.emb)], dim=1)
            if self.kind == "linear":
                return self.shared(x) + self.bias
            x = self.body(x)
            if self.kind == "gru":
                with torch.autocast(seq.device.type, enabled=False):
                    _, h = self.rnn(seq.float())
                x = torch.cat([x, h[-1].to(x.dtype)], dim=1)
            return self.head(x)

    return HazardNet()


def _weighted_bce(z, Y, W):
    import torch.nn.functional as F

    return (F.binary_cross_entropy_with_logits(z.float(), Y, reduction="none") * W).sum()


def _train_net(net, forward, targets, cfg, dev, seed, log):
    """Mini-batch AdamW on the masked, weighted hazard likelihood with early stopping on
    the early-stopping drives. forward(part, rows) gives the logits of those rows;
    targets[part] = (Y, W) on the device. The learning rate halves after every epoch that
    does not improve, and training stops after `patience` such epochs."""
    import torch

    (Y_tr, W_tr), (Y_va, W_va) = targets["train"], targets["early"]
    n = Y_tr.shape[0]
    norm = float(W_tr.sum()) / n             # loss per snapshot, on the scale of a mean weight
    opt = torch.optim.AdamW(net.parameters(), lr=cfg["lr"], weight_decay=cfg["weight_decay"])
    amp = dev.type == "cuda"
    gen = torch.Generator(device=dev).manual_seed(seed)

    def val_loss():
        net.eval()
        total = 0.0
        with torch.no_grad(), torch.autocast(dev.type, dtype=torch.bfloat16, enabled=amp):
            for lo in range(0, Y_va.shape[0], 1 << 16):
                rows = torch.arange(lo, min(lo + (1 << 16), Y_va.shape[0]), device=dev)
                total += float(_weighted_bce(forward("early", rows), Y_va[rows], W_va[rows]))
        net.train()
        return total / float(W_va.sum())

    best, best_state, best_epoch, bad, lr = math.inf, None, 0, 0, cfg["lr"]
    bs = cfg["batch_size"]
    for epoch in range(cfg["max_epochs"]):
        perm = torch.randperm(n, device=dev, generator=gen)
        for lo in range(0, n, bs):
            b = perm[lo:lo + bs]
            with torch.autocast(dev.type, dtype=torch.bfloat16, enabled=amp):
                z = forward("train", b)
            loss = _weighted_bce(z, Y_tr[b], W_tr[b]) / (norm * b.numel())
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
        v = val_loss()
        log(f"epoch {epoch + 1}: val logloss {v:.6g} (lr {lr:.2g})")
        if v < best - 1e-7:
            best, bad, best_epoch = v, 0, epoch + 1
            best_state = {k: t.detach().clone() for k, t in net.state_dict().items()}
        else:
            bad += 1
            lr *= 0.5
            for g in opt.param_groups:
                g["lr"] = lr
            if bad >= cfg["patience"]:
                break
    net.load_state_dict(best_state)
    log(f"best epoch {best_epoch}, val logloss {best:.6g}")
    return best_epoch, best


def _fit_torch(ctx, p, study, schema, features, categorical, parts, log):
    import torch

    edges = study["label"]["bin_edges"]
    K = len(edges) - 1
    cfg = p["torch"]
    torch.manual_seed(p["seed"])
    dev = _device(p.get("device", "auto"))
    meta_tr, X_tr = parts["train"]
    bins = cfg["arch"].get("bins", 32) if cfg["arch"].get("encoding") == "ple" else 0
    prep = Prep.fit(X_tr, features, categorical, schema, bins)
    inputs, targets = {}, {}
    for part in ("train", "early"):
        meta, X = parts[part]
        num, cat = prep.transform(X)
        Y, W = dense_targets(meta, edges, p.get("weight_power", 1.0))
        inputs[part] = [torch.from_numpy(a).to(dev) for a in (num, cat)]
        targets[part] = [torch.from_numpy(a).to(dev) for a in (Y, W)]
    windows = None
    if cfg["arch"]["type"] == "gru":
        scaling = channel_scaling(ctx, study, prep, features)
        windows = PanelWindows.build(ctx.inputs["panel_dir"], ctx.inputs["snapshots"],
                                     ["train", "val"], study, scaling, dev, log)
        # load_snapshots orders by split, so train rows come first, then val
        n_tr = len(meta_tr)
        early = ~val_roles(_val_serials(ctx), study["split"]["calibration_share"])
        rows = {"train": torch.arange(n_tr, device=dev),
                "early": torch.from_numpy(np.flatnonzero(early) + n_tr).to(dev)}
    net = _hazard_net(prep, K, cfg["arch"], windows.channels if windows else 0).to(dev)
    log(f"device {dev}, {prep.n_num} numerical inputs ({len(prep.missing)} missing flags), "
        f"{len(prep.cards)} embeddings, {sum(x.numel() for x in net.parameters())} parameters"
        + (f", {windows.length}-day windows of {windows.channels} channels" if windows else ""))

    def forward(part, b):
        num, cat = inputs[part]
        if windows is None:
            return net(num[b], cat[b])
        return net(num[b], cat[b], windows.batch(rows[part][b]))

    best_epoch, best = _train_net(net, forward, targets, cfg, dev, p["seed"], log)
    model = TorchHazard(net.cpu(), prep, cfg["arch"], K, dev)
    if windows is not None:
        model.windows = windows.restricted(_calib_rows(ctx, study, len(meta_tr)))
        model.scaling = scaling
    return model, {
        "best_iter": best_epoch, "val_loss": best, "val_metric": "logloss",
        "train_rows": int(len(meta_tr)), "train_events": int(meta_tr["event"].sum()),
        "val_rows": int(len(parts["early"][0])),
        "val_events": int(parts["early"][0]["event"].sum()),
        **({"window_days": windows.length, "needs_panel": True} if windows else {}),
    }


def _val_serials(ctx):
    import duckdb

    from common import q
    con = duckdb.connect()
    return con.sql(f"SELECT serial_number FROM read_parquet({q(ctx.inputs['snapshots'])}) "
                   "WHERE split = 'val' ORDER BY split, serial_number, date").df()["serial_number"]


def _calib_rows(ctx, study, n_train):
    """Rows of the calibration snapshots in the train + val window index."""
    calib = val_roles(_val_serials(ctx), study["split"]["calibration_share"])
    return np.flatnonzero(calib) + n_train


class PanelWindows:
    """Each snapshot's last `length` days of daily SMART readings, gathered on the device.

    The panel rows of the snapshots' drives sit in one fp16 matrix (drive by drive, day by
    day, scaled like the snapshot features: signed log1p, standardized, missing = 0). A
    snapshot is the row of its own day, `pos`, and the first row of its drive, `start`.
    Its window is rows pos - length + 1 .. pos, cut at the drive's first row; each step adds
    two channels, the days before the snapshot (/ length) and a 1 for a real row. Only past
    rows are used, and extract already cut train and validation drives at train_end."""

    def __init__(self, values, days, pos, start, length):
        self.values, self.days, self.pos, self.start, self.length = values, days, pos, start, length

    @property
    def channels(self) -> int:
        return self.values.shape[1] + 2

    @classmethod
    def build(cls, panel_dir, snapshots, splits, study, scaling, dev, log):
        """`scaling` = (mean, std) per panel column after the signed log."""
        import duckdb
        import torch

        from common import q, smart_columns
        length = max(study["features"]["trend_windows"])
        cols = smart_columns(study)
        mean, std = scaling
        con = duckdb.connect(config={"threads": _threads()})
        where = "split IN (" + ", ".join(q(s) for s in splits) + ")"
        con.sql(f"""CREATE TABLE keys AS SELECT row_number() OVER (ORDER BY split, serial_number,
                    date) - 1 AS i, serial_number, date FROM read_parquet({q(snapshots)})
                    WHERE {where}""")
        n = con.sql("SELECT count(*) FROM keys").fetchall()[0][0]
        pos = np.full(n, -1, np.int64)
        start = np.full(n, -1, np.int64)
        values, days, offset = [], [], 0
        for batch in sorted(Path(panel_dir).glob("batch=*")):
            src = f"read_parquet({q(str(batch) + '/*.parquet')})"
            con.sql(f"""CREATE OR REPLACE TABLE p AS SELECT row_number() OVER (ORDER BY
                        serial_number, date) - 1 AS r, serial_number, date,
                        date_diff('day', DATE '1970-01-01', date) AS epoch_day, {", ".join(cols)}
                        FROM {src} WHERE serial_number IN (SELECT serial_number FROM keys)""")
            t = con.sql("SELECT * FROM p ORDER BY r").fetch_arrow_table()
            block = np.empty((t.num_rows, len(cols)), np.float32)
            for j, c in enumerate(cols):
                block[:, j] = t.column(c).to_numpy(zero_copy_only=False)
            block = (_signed_log(block) - mean) / std
            values.append(np.nan_to_num(block, nan=0.0).astype(np.float16))
            days.append(t.column("epoch_day").to_numpy(zero_copy_only=False).astype(np.int32))
            hit = con.sql("""SELECT k.i, p.r, min(p.r) OVER (PARTITION BY p.serial_number) AS s
                             FROM p LEFT JOIN keys k USING (serial_number, date)""").df()
            hit = hit[hit["i"].notna()]
            pos[hit["i"].to_numpy(np.int64)] = hit["r"].to_numpy(np.int64) + offset
            start[hit["i"].to_numpy(np.int64)] = hit["s"].to_numpy(np.int64) + offset
            offset += t.num_rows
            del t, block
        if (pos < 0).any():
            raise ValueError(f"{int((pos < 0).sum())} snapshots have no panel row on their day")
        log(f"panel windows: {offset} daily rows of {len(cols)} channels for {n} snapshots")
        to = (lambda a: torch.from_numpy(a).to(dev)) if dev is not None else torch.from_numpy
        return cls(to(np.concatenate(values)), to(np.concatenate(days)), to(pos), to(start),
                   length)

    def batch(self, rows):
        """(rows, length, channels) windows, oldest day first, as float32."""
        import torch

        p, s = self.pos[rows], self.start[rows]
        back = torch.arange(self.length - 1, -1, -1, device=p.device)
        idx = p[:, None] - back[None, :]
        real = idx >= s[:, None]
        idx = torch.where(real, idx, p[:, None])
        x = self.values[idx].float() * real[..., None]
        age = (self.days[p][:, None] - self.days[idx]).float() / self.length * real
        return torch.cat([x, age[..., None], real[..., None].float()], dim=2)

    def restricted(self, rows):
        """The same panel, indexed by the given snapshot rows only."""
        import torch

        r = torch.as_tensor(rows, device=self.pos.device)
        return PanelWindows(self.values, self.days, self.pos[r], self.start[r], self.length)


def channel_scaling(ctx, study, prep: Prep, features):
    """Scaling of each panel column after the signed log: the snapshot feature's, which Prep
    fitted on train; for a column the model does not take as a feature, the mean and
    standard deviation over the train drives' daily rows."""
    import duckdb

    from common import q, smart_columns
    cols = smart_columns(study)
    by_name = {features[j]: i for i, j in enumerate(prep.numeric)}
    mean = np.zeros(len(cols), np.float32)
    std = np.ones(len(cols), np.float32)
    rest = []
    for k, c in enumerate(cols):
        if c in by_name:
            mean[k], std[k] = prep.mean[by_name[c]], prep.std[by_name[c]]
        else:
            rest.append(k)
    if rest:
        con = duckdb.connect(config={"threads": _threads()})
        panel = q(str(ctx.inputs["panel_dir"]) + "/*/*.parquet")
        train = (f"SELECT DISTINCT serial_number FROM read_parquet({q(ctx.inputs['snapshots'])}) "
                 "WHERE split = 'train'")
        exprs = ", ".join(f"avg(sign({c}) * ln(1 + abs({c}))), "
                          f"stddev_pop(sign({c}) * ln(1 + abs({c})))" for c in
                          (cols[k] for k in rest))
        row = con.sql(f"SELECT {exprs} FROM read_parquet({panel}, hive_partitioning = true) "
                      f"WHERE serial_number IN ({train})").fetchall()[0]
        for n, k in enumerate(rest):
            m, sd = row[2 * n], row[2 * n + 1]
            mean[k] = m if m is not None else 0.0
            std[k] = sd if sd and sd > 1e-6 else 1.0
    return mean, std


class TorchHazard:
    """A trained network. A sequence model also needs `windows` (PanelWindows) whose rows
    line up with the X passed to hazard_logits; predict and train attach them."""

    windows = None
    scaling = None      # (mean, std) per panel column, for a sequence model

    def __init__(self, net, prep: Prep, arch: dict, K: int, device):
        self.net, self.prep, self.arch, self.K, self.device = net, prep, arch, K, device

    def save(self, path: Path):
        import torch

        state = {"state_dict": self.net.state_dict(), "prep": self.prep.state(),
                 "arch": self.arch, "K": self.K,
                 "channels": self.windows.channels if self.windows else 0}
        if self.scaling is not None:
            state["scaling"] = [torch.from_numpy(np.asarray(a)) for a in self.scaling]
        torch.save(state, path)

    @classmethod
    def load(cls, path: Path, info: dict):
        import torch

        s = torch.load(path, map_location="cpu", weights_only=True)
        prep = Prep.from_state(s["prep"])
        net = _hazard_net(prep, s["K"], s["arch"], s.get("channels", 0))
        net.load_state_dict(s["state_dict"])
        dev = _device(info.get("params", {}).get("device", "auto"))
        model = cls(net, prep, s["arch"], s["K"], dev)
        if "scaling" in s:
            model.scaling = tuple(t.numpy() for t in s["scaling"])
        return model

    def hazard_logits(self, X: np.ndarray) -> np.ndarray:
        import torch

        if self.arch["type"] == "gru" and self.windows is None:
            raise ValueError("a sequence model needs its panel windows attached")
        net = self.net.to(self.device).eval()
        out = np.empty((X.shape[0], self.K))
        step = CHUNK if self.windows is None else SEQ_CHUNK
        with torch.no_grad():
            for lo in range(0, X.shape[0], step):
                num, cat = self.prep.transform(X[lo:lo + step])
                args = [torch.from_numpy(num).to(self.device),
                        torch.from_numpy(cat).to(self.device)]
                if self.windows is not None:
                    rows = torch.arange(lo, min(lo + step, X.shape[0]), device=self.device)
                    args.append(self.windows.batch(rows))
                out[lo:lo + step] = net(*args).float().cpu().numpy()
        return out
