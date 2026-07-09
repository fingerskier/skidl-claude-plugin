"""Test the checked-in end-to-end example (examples/voltage_divider/build_divider.py).

Runs the example's ``build()`` against a temp artifacts dir and asserts each
generator wrote a real file and returned a compact (no-``content``) response.
This keeps the documented example honest: if the file-based workflow breaks, this
test breaks.
"""

import importlib.util
from pathlib import Path

import pytest

from skidl_mcp.circuit_manager import manager

EXAMPLE = (
    Path(__file__).resolve().parent.parent
    / "examples" / "voltage_divider" / "build_divider.py"
)


def _load_example():
    spec = importlib.util.spec_from_file_location("build_divider", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def clean_manager():
    manager.reset()
    yield
    manager.reset()


def test_example_file_exists():
    assert EXAMPLE.is_file(), f"example script missing: {EXAMPLE}"


def test_example_writes_artifacts(tmp_path, monkeypatch):
    module = _load_example()
    # Redirect the example's ARTIFACTS dir into tmp so we don't litter the repo.
    monkeypatch.setattr(module, "ARTIFACTS", tmp_path / "artifacts")

    results = module.build()

    assert set(results) == {"netlist", "bom", "python"}
    for name, resp in results.items():
        assert resp["status"] == "ok", f"{name} failed: {resp.get('message')}"
        # Compact response: content lives on disk, not in the payload.
        assert "content" not in resp, f"{name} leaked inline content"
        path = Path(resp["path"])
        assert path.is_file() and path.stat().st_size > 0

    assert results["netlist"]["summary"]["parts"] == 2
    assert results["bom"]["summary"]["total_parts"] == 2
    bom = (tmp_path / "artifacts" / "voltage_divider_bom.csv").read_text(encoding="utf-8")
    assert "8.2k" in bom
    # Refs must be R1/R2 (resistor designators), matching the code comment —
    # not the default 'U' prefix bare SKiDL parts would otherwise get.
    assert "R1" in bom and "R2" in bom
    assert "U1" not in bom and "U2" not in bom
    assert "from skidl import" in (tmp_path / "artifacts" / "voltage_divider.py").read_text(
        encoding="utf-8"
    )
