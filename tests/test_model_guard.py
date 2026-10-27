"""The training memory guard: trips above 90% of available memory, passes below."""

import pytest

import model

GiB = 2**30


def test_memory_guard_trips(monkeypatch):
    monkeypatch.setattr(model, "available_memory", lambda: 4 * GiB)
    # 2 GiB of matrices + 50M rows x 21 x 4 bytes (~3.9 GiB) is far above 0.9 x 4 GiB
    with pytest.raises(MemoryError, match="GiB"):
        model._check_memory(50_000_000, 20, 2 * GiB, lambda *a: None)


def test_memory_guard_passes(monkeypatch):
    monkeypatch.setattr(model, "available_memory", lambda: 64 * GiB)
    lines = []
    model._check_memory(1_000_000, 20, 1 * GiB, lambda *a: lines.append(a))
    assert lines and "memory estimate" in lines[0][0]


def test_memory_guard_threshold(monkeypatch):
    # need = X + 2**29 with no rows; it passes at exactly 90% and trips just above
    need = GiB + 2**29
    monkeypatch.setattr(model, "available_memory", lambda: int(need / 0.9) + 1)
    model._check_memory(0, 20, GiB, lambda *a: None)
    monkeypatch.setattr(model, "available_memory", lambda: int(need / 0.9) - 10)
    with pytest.raises(MemoryError):
        model._check_memory(0, 20, GiB, lambda *a: None)
