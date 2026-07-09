"""Phase A tests: file-based artifact output and compact tool responses.

Every generator accepts an ``output_path``. When given, the artifact is written
to that file and the response is compact — ``{path, summary, warnings}`` with no
``content`` field — so large netlists/schematics never flood the model context.
When omitted, the full content is returned inline (truncated past a size limit).
"""

import os

import pytest
from skidl import SKIDL, Part, Pin

from skidl_mcp.circuit_manager import manager
from skidl_mcp.tools import artifact_io, circuit, generate, nets


@pytest.fixture(autouse=True)
def clean_manager():
    manager.reset()
    yield
    manager.reset()


def _divider():
    """Build a tiny two-resistor divider that works without KiCad libraries."""
    circuit.create_circuit("divider", "12V -> 3.3V")
    entry = manager.get_active()
    refs = []
    for _ in range(2):
        p = Part(name="R", tool=SKIDL,
                 pins=[Pin(num=1, name="p1"), Pin(num=2, name="p2")],
                 circuit=entry.circuit)
        p.footprint = "Resistor_SMD:R_0805_2012Metric"
        entry.parts[p.ref] = p
        refs.append(p.ref)
    nets.create_net("VIN")
    nets.connect("VIN", refs[0], "1")
    nets.connect_pins(refs[0], "2", refs[1], "1", net_name="VOUT")
    nets.create_net("GND")
    nets.connect("GND", refs[1], "2")
    return entry, refs


# ---------------------------------------------------------------------------
# artifact_io helper — the shared write/compact/truncate logic
# ---------------------------------------------------------------------------


class TestArtifactIoHelper:
    def test_inline_small_returns_full_content(self):
        resp = artifact_io.finalize_artifact(
            "hello", None, fmt="txt", summary={"n": 1}, message="ok.")
        assert resp["status"] == "ok"
        assert resp["content"] == "hello"
        assert "path" not in resp
        assert resp.get("truncated") is not True

    def test_inline_large_is_truncated_with_warning(self):
        big = "x" * (artifact_io.INLINE_CONTENT_LIMIT + 500)
        resp = artifact_io.finalize_artifact(
            big, None, fmt="txt", summary={}, message="ok.")
        assert resp["truncated"] is True
        assert len(resp["content"]) == artifact_io.INLINE_CONTENT_LIMIT
        assert resp["bytes"] == len(big.encode("utf-8"))
        assert any("output_path" in w for w in resp["warnings"])

    def test_output_path_writes_file_and_omits_content(self, tmp_path):
        target = tmp_path / "sub" / "out.txt"
        resp = artifact_io.finalize_artifact(
            "payload", str(target), fmt="txt", summary={"n": 2}, message="done.")
        assert resp["status"] == "ok"
        assert "content" not in resp
        assert resp["path"] == str(target.resolve())
        assert resp["summary"] == {"n": 2}
        assert target.read_text(encoding="utf-8") == "payload"
        # parent directory is created on demand
        assert target.parent.is_dir()

    def test_output_path_writes_only_the_requested_file(self, tmp_path):
        target = tmp_path / "only.svg"
        artifact_io.finalize_artifact(
            "<svg/>", str(target), fmt="svg", summary={}, message="done.")
        assert sorted(p.name for p in tmp_path.iterdir()) == ["only.svg"]

    def test_output_path_directory_returns_error(self, tmp_path):
        resp = artifact_io.finalize_artifact(
            "payload", str(tmp_path), fmt="txt", summary={}, message="done.")
        assert resp["status"] == "error"
        assert "directory" in resp["message"].lower()

    def test_inline_extra_keys_preserved(self):
        resp = artifact_io.finalize_artifact(
            "c", None, fmt="json", summary={}, message="ok.",
            inline_extra={"total_parts": 3, "unique_parts": 2})
        assert resp["total_parts"] == 3
        assert resp["unique_parts"] == 2

    def test_reported_bytes_match_on_disk_size(self, tmp_path):
        """`bytes` must equal the real file size, even for multi-line content
        (no CRLF translation inflating the file past the reported count)."""
        target = tmp_path / "multiline.net"
        content = "line1\nline2\nline3\n"
        resp = artifact_io.finalize_artifact(
            content, str(target), fmt="txt", summary={}, message="ok.")
        assert resp["status"] == "ok"
        assert resp["bytes"] == target.stat().st_size
        # Content is written verbatim (LF preserved), byte-identical to input.
        assert target.read_bytes() == content.encode("utf-8")

    def test_whitespace_output_path_errors_not_silent_inline(self):
        """A whitespace-only path is a botched write request, not 'no path'."""
        resp = artifact_io.finalize_artifact(
            "payload", "   ", fmt="txt", summary={}, message="ok.")
        assert resp["status"] == "error"
        assert "content" not in resp
        assert "empty" in resp["message"].lower()

    def test_empty_string_output_path_is_inline(self):
        """An empty string still means 'no path given' -> inline content."""
        resp = artifact_io.finalize_artifact(
            "payload", "", fmt="txt", summary={}, message="ok.")
        assert resp["status"] == "ok"
        assert resp["content"] == "payload"
        assert "path" not in resp

    def test_inline_large_unencodable_content_does_not_raise(self):
        """A lone surrogate in oversized inline content must not crash the tool."""
        big = "x" * (artifact_io.INLINE_CONTENT_LIMIT + 10) + "\ud800"
        resp = artifact_io.finalize_artifact(
            big, None, fmt="txt", summary={}, message="ok.")
        assert resp["status"] == "ok"
        assert resp["truncated"] is True
        assert isinstance(resp["bytes"], int)


# ---------------------------------------------------------------------------
# Generators that work offline (no KiCad): netlist, bom, export_python
# ---------------------------------------------------------------------------


class TestGeneratorFileOutput:
    def test_netlist_to_file(self, tmp_path):
        _divider()
        out = tmp_path / "board.net"
        resp = generate.generate_netlist(output_path=str(out))
        assert resp["status"] == "ok"
        assert "content" not in resp
        assert out.is_file() and out.stat().st_size > 0
        assert resp["summary"]["parts"] == 2
        assert resp["path"] == str(out.resolve())

    def test_bom_csv_to_file(self, tmp_path):
        _divider()
        out = tmp_path / "bom.csv"
        resp = generate.generate_bom(output_format="csv", output_path=str(out))
        assert resp["status"] == "ok"
        assert "content" not in resp
        assert "Qty" in out.read_text(encoding="utf-8")
        assert resp["summary"]["total_parts"] == 2

    def test_export_python_to_file(self, tmp_path):
        _divider()
        out = tmp_path / "circuit.py"
        resp = generate.export_python(output_path=str(out))
        assert resp["status"] == "ok"
        assert "content" not in resp
        assert "from skidl import" in out.read_text(encoding="utf-8")

    def test_no_output_path_keeps_inline_content(self, tmp_path):
        """Back-compat: without output_path the full content is still returned."""
        _divider()
        resp = generate.generate_netlist()
        assert resp["status"] == "ok"
        assert "content" in resp
        assert "path" not in resp

    def test_file_output_leaves_no_stray_artifacts(self, tmp_path, monkeypatch):
        """Writing to output_path must not drop skidl .net/_sklib.py litter in CWD."""
        monkeypatch.chdir(tmp_path)
        _divider()
        out = tmp_path / "artifacts" / "board.net"
        resp = generate.generate_netlist(output_path=str(out))
        assert resp["status"] == "ok"
        # Only the artifacts/ dir (holding board.net) should appear in CWD.
        stray = [p.name for p in tmp_path.iterdir()
                 if p.name != "artifacts" and p.suffix in (".net", ".log", ".erc")
                 or p.name.endswith("_sklib.py")]
        assert stray == [], f"stray artifacts: {stray}"


# ---------------------------------------------------------------------------
# Experimental generators: output_path must not make them raise
# ---------------------------------------------------------------------------


class TestExperimentalGeneratorsWithOutputPath:
    def test_svg_with_output_path_never_raises(self, tmp_path):
        _divider()
        resp = generate.generate_svg(output_path=str(tmp_path / "s.svg"))
        assert resp["status"] in ("ok", "error")
        assert "message" in resp

    def test_kicad_schematic_with_output_path_never_raises(self, tmp_path):
        _divider()
        resp = generate.generate_kicad_schematic(output_path=str(tmp_path / "s.kicad_sch"))
        assert resp["status"] in ("ok", "error")
        assert "message" in resp
