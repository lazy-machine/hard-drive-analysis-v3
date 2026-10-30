"""The training memory guard: trips above 90% of available memory, passes below."""

import pytest

import model

GiB = 2**30


@pytest.fixture(autouse=True)
def no_process_memory(monkeypatch):
    """The guard adds the process's own memory to what is available; pin it to 0."""
    monkeypatch.setattr(model, "process_memory", lambda: 0)


def test_memory_guard_trips(monkeypatch):
    monkeypatch.setattr(model, "available_memory", lambda: 4 * GiB)
    # 2 GiB of matrices + 50M rows x 21 x 2 bytes (~2 GiB) is far above 0.9 x 4 GiB
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


def test_memory_guard_counts_own_memory_as_available(monkeypatch):
    # the 2026-10-28 full run: 9.6 GiB estimate, 10.2 GiB free after loading ~3 GiB of
    # snapshots that the estimate already includes. It must pass.
    monkeypatch.setattr(model, "available_memory", lambda: int(10.2 * GiB))
    monkeypatch.setattr(model, "process_memory", lambda: 3 * GiB)
    model._check_memory(57_000_000, 65, int(2.1 * GiB), lambda *a: None)


def test_memory_guard_passes_full_scale_on_15gb_machine(monkeypatch):
    # the full scale measured on 2026-10-28: 57M counted rows, 65 features, 2.1 GiB of
    # snapshot matrices, 8.78 GiB peak. It must pass with ~13.9 GiB available.
    monkeypatch.setattr(model, "available_memory", lambda: int(13.9 * GiB))
    model._check_memory(57_000_000, 65, int(2.1 * GiB), lambda *a: None)
