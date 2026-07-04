"""Regression tests: the plugin must never litter the working directory.

SKiDL creates ``<script>.log`` and ``<script>.erc`` in the CWD the moment
``skidl`` is imported, and writes a backup parts library
(``<script>_lib_sklib.py``) when generating a netlist.  The MCP server runs
with its CWD inside whatever project the user has open, so any such file is
litter in a stranger's repo.  These tests run in a subprocess because the
import-time behavior only happens once per process.
"""

import os
import subprocess
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent / "src")


def _run_in(tmp_path: Path, code: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=SRC)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _files_in(tmp_path: Path) -> list[str]:
    return sorted(p.name for p in tmp_path.iterdir())


def test_import_leaves_no_files(tmp_path):
    """Importing the package (as the MCP server does at startup) writes nothing."""
    result = _run_in(tmp_path, "import skidl_mcp.tools.circuit")
    assert result.returncode == 0, result.stderr
    assert _files_in(tmp_path) == []


def test_direct_skidl_importers_leave_no_files(tmp_path):
    """Each module that imports skidl directly cleans up the log/erc files."""
    for module in ("skidl_mcp.circuit_manager", "skidl_mcp.tools.nets", "skidl_mcp.tools.parts"):
        result = _run_in(tmp_path, f"import {module}")
        assert result.returncode == 0, result.stderr
        assert _files_in(tmp_path) == [], f"{module} left files behind"


def test_full_design_session_leaves_no_files(tmp_path):
    """Building, validating, and exporting a circuit writes nothing to CWD."""
    code = """
from skidl import SKIDL, Part, Pin
from skidl_mcp.circuit_manager import manager
from skidl_mcp.tools import circuit, nets, generate, validate

circuit.create_circuit("divider", "artifact regression")
entry = manager.get_active()
refs = []
for _ in range(2):
    p = Part(name="R", tool=SKIDL,
             pins=[Pin(num=1, name="p1"), Pin(num=2, name="p2")],
             circuit=entry.circuit)
    entry.parts[p.ref] = p
    refs.append(p.ref)

nets.create_net("VIN")
nets.connect("VIN", refs[0], "1")
nets.connect_pins(refs[0], "2", refs[1], "1", net_name="VOUT")
nets.create_net("GND")
nets.connect("GND", refs[1], "2")

assert generate.generate_netlist()["status"] == "ok"
assert generate.generate_bom("csv")["status"] == "ok"
assert generate.export_python()["status"] == "ok"
assert validate.run_erc()["status"] == "ok"
assert validate.check_connections()["status"] == "ok"
"""
    result = _run_in(tmp_path, code)
    assert result.returncode == 0, result.stderr
    assert _files_in(tmp_path) == []
