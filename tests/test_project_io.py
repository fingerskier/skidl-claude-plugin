"""Phase B tests: a project directory is the source of truth for a design.

Covers deterministic serialization (natural-sorted, git-diffable, no timestamps),
the save→load→save byte-identical fixpoint, netlist round-trip after a reset,
index rebuilding, design.yaml metadata (with unknown-key preservation), bus
survival, and the security guarantee that loading never executes ``circuit.py``.
"""

import json
import re

import pytest
import yaml
from skidl import SKIDL, Part, Pin

from skidl_mcp.circuit_manager import manager
from skidl_mcp.tools import circuit, generate, nets, project_io


@pytest.fixture(autouse=True)
def clean_manager():
    manager.reset()
    yield
    manager.reset()


# ---------------------------------------------------------------------------
# Builders / helpers
# ---------------------------------------------------------------------------


def _divider():
    """A two-resistor 12V->3.3V divider built from bare parts (works offline)."""
    circuit.create_circuit("divider", "12V -> 3.3V")
    entry = manager.get_active()
    refs = []
    for i, value in enumerate(("8.2k", "3.3k"), start=1):
        p = Part(name="R", tool=SKIDL,
                 pins=[Pin(num=1, name="p1"), Pin(num=2, name="p2")],
                 circuit=entry.circuit, ref=f"R{i}")
        p.value = value
        p.footprint = "Resistor_SMD:R_0805_2012Metric"
        entry.parts[p.ref] = p
        refs.append(p.ref)
    nets.create_net("VIN")
    nets.connect("VIN", refs[0], "1")
    nets.connect_pins(refs[0], "2", refs[1], "1", net_name="VOUT")
    nets.create_net("GND")
    nets.connect("GND", refs[1], "2")
    return entry, refs


# Netlist fields SKiDL regenerates non-deterministically (random tags, source
# line numbers, per-part UUIDs, run date). Strip them so a round-trip compares
# only the meaningful structure: components, values, footprints, connectivity.
_VOLATILE = re.compile(
    r'^\((date|source|tool|tstamps) '
    r'|"SKiDL Tag"'
    r'|"SKiDL Line"'
)


def _normalize_netlist(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines()
        if not _VOLATILE.search(line.strip())
    )


# ---------------------------------------------------------------------------
# Deterministic serialization
# ---------------------------------------------------------------------------


class TestSerialize:
    def test_parts_natural_sorted_not_lexicographic(self):
        circuit.create_circuit("c")
        entry = manager.get_active()
        # Insert refs out of order and spanning the R2/R10 boundary.
        for ref in ("R10", "R2", "R1"):
            p = Part(name="R", tool=SKIDL, pins=[Pin(num=1, name="~")],
                     circuit=entry.circuit, ref=ref)
            entry.parts[ref] = p
        data = project_io.serialize_entry(entry)
        assert [p["ref"] for p in data["parts"]] == ["R1", "R2", "R10"]

    def test_nets_and_pins_sorted(self):
        entry, _ = _divider()
        data = project_io.serialize_entry(entry)
        assert [n["name"] for n in data["nets"]] == ["GND", "VIN", "VOUT"]
        vout = next(n for n in data["nets"] if n["name"] == "VOUT")
        assert vout["pins"] == ["R1.2", "R2.1"]

    def test_json_text_has_trailing_newline_and_no_timestamps(self):
        entry, _ = _divider()
        text = project_io.circuit_json_text(project_io.serialize_entry(entry))
        assert text.endswith("\n")
        # circuit.json is timestamp/tag free — none of the volatile netlist noise.
        for needle in ("date", "tstamp", "SKiDL Tag", "SKiDL Line", "created_at"):
            assert needle not in text
        parsed = json.loads(text)
        assert parsed["schema_version"] == project_io.SCHEMA_VERSION
        assert parsed["roles"] == {} and parsed["interfaces"] == {}

    def test_pin_func_preserved(self):
        circuit.create_circuit("c")
        entry = manager.get_active()
        p = Part(name="D", tool=SKIDL,
                 pins=[Pin(num=1, name="A", func=Pin.types.PASSIVE),
                       Pin(num=2, name="K", func=Pin.types.OUTPUT)],
                 circuit=entry.circuit, ref="D1")
        entry.parts["D1"] = p
        data = project_io.serialize_entry(entry)
        funcs = {pin["num"]: pin["func"] for pin in data["parts"][0]["pins"]}
        assert funcs == {"1": "PASSIVE", "2": "OUTPUT"}
        restored = project_io.restore_entry(data)
        rfuncs = {str(pin.num): pin.func.name for pin in restored.parts["D1"].pins}
        assert rfuncs == {"1": "PASSIVE", "2": "OUTPUT"}


# ---------------------------------------------------------------------------
# Fixpoint: save -> load -> save is byte-identical
# ---------------------------------------------------------------------------


class TestFixpoint:
    def test_in_memory_fixpoint(self):
        entry, _ = _divider()
        t1 = project_io.circuit_json_text(project_io.serialize_entry(entry))
        restored = project_io.restore_entry(json.loads(t1))
        t2 = project_io.circuit_json_text(project_io.serialize_entry(restored))
        assert t1 == t2

    def test_custom_fields_round_trip(self):
        # A part's user-set fields (e.g. MPN/tolerance) survive save→load and the
        # result is still a byte-identical fixpoint.
        circuit.create_circuit("c")
        entry = manager.get_active()
        p = Part(name="R", tool=SKIDL, pins=[Pin(num=1, name="~")],
                 circuit=entry.circuit, ref="R1")
        p.fields["MPN"] = "RC0805FR-07"
        p.fields["Tol"] = "1%"
        entry.parts["R1"] = p
        t1 = project_io.circuit_json_text(project_io.serialize_entry(entry))
        restored = project_io.restore_entry(json.loads(t1))
        assert restored.parts["R1"].fields["MPN"] == "RC0805FR-07"
        assert restored.parts["R1"].fields["Tol"] == "1%"
        t2 = project_io.circuit_json_text(project_io.serialize_entry(restored))
        assert t1 == t2

    def test_on_disk_fixpoint(self, tmp_path):
        entry, _ = _divider()
        proj = tmp_path / "proj"
        project_io.save_project(entry, proj)
        b1 = (proj / "circuit.json").read_bytes()

        restored = project_io.load_project(proj)
        project_io.save_project(restored, proj)
        b2 = (proj / "circuit.json").read_bytes()
        assert b1 == b2


# ---------------------------------------------------------------------------
# Round-trip through a full reset (survives an agent "restart")
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_netlist_matches_after_reset_and_load(self, tmp_path):
        _divider()
        n1 = generate.generate_netlist()["content"]

        proj = tmp_path / "proj"
        assert project_io.save_circuit(str(proj))["status"] == "ok"

        manager.reset()  # simulate a fresh session with nothing in memory
        with pytest.raises(RuntimeError):
            manager.get_active()

        assert project_io.load_circuit(str(proj))["status"] == "ok"
        n2 = generate.generate_netlist()["content"]

        assert _normalize_netlist(n1) == _normalize_netlist(n2)

    def test_restore_rebuilds_indexes(self, tmp_path):
        _divider()
        proj = tmp_path / "proj"
        project_io.save_circuit(str(proj))
        manager.reset()
        project_io.load_circuit(str(proj))

        entry = manager.get_active()
        assert set(entry.parts) == {"R1", "R2"}
        assert set(entry.nets) == {"VIN", "VOUT", "GND"}
        # The rebuilt indexes drive the tools: find_part + a connection works.
        assert manager.find_part("R1", entry).ref == "R1"
        resp = nets.list_nets()
        vout = next(n for n in resp["nets"] if n["name"] == "VOUT")
        assert vout["connection_count"] == 2


# ---------------------------------------------------------------------------
# Project lifecycle tools
# ---------------------------------------------------------------------------


class TestProjectLifecycle:
    def test_open_empty_creates_skeleton(self, tmp_path):
        proj = tmp_path / "fresh"
        resp = project_io.open_project(str(proj))
        assert resp["status"] == "ok"
        assert resp["loaded"] is False
        assert (proj / "artifacts").is_dir()
        assert (proj / "worlds").is_dir()
        assert manager.project_root == str(proj.resolve())

    def test_open_build_save_reopen(self, tmp_path):
        proj = tmp_path / "proj"
        project_io.open_project(str(proj))
        _divider()
        # save_circuit with no path uses the opened project directory
        save = project_io.save_circuit()
        assert save["status"] == "ok"
        assert (proj / "circuit.json").is_file()
        assert (proj / "circuit.py").is_file()
        assert (proj / "design.yaml").is_file()

        manager.reset()
        reopen = project_io.open_project(str(proj))
        assert reopen["loaded"] is True
        assert reopen["summary"]["parts"] == 2
        assert manager.get_active().name == "divider"

    def test_save_without_project_errors(self, tmp_path):
        _divider()
        resp = project_io.save_circuit()
        assert resp["status"] == "error"
        assert "project path" in resp["message"].lower()

    def test_load_missing_circuit_json_errors(self, tmp_path):
        resp = project_io.load_circuit(str(tmp_path / "nope"))
        assert resp["status"] == "error"

    def test_open_project_empty_path_errors(self):
        assert project_io.open_project("")["status"] == "error"


# ---------------------------------------------------------------------------
# design.yaml metadata layer
# ---------------------------------------------------------------------------


class TestDesignYaml:
    def test_metadata_written(self, tmp_path):
        entry, _ = _divider()
        proj = tmp_path / "proj"
        project_io.save_project(entry, proj)
        doc = yaml.safe_load((proj / "design.yaml").read_text(encoding="utf-8"))
        assert doc["name"] == "divider"
        assert doc["description"] == "12V -> 3.3V"
        assert "created_at" in doc

    def test_unknown_keys_and_requirements_survive_round_trip(self, tmp_path):
        entry, _ = _divider()
        proj = tmp_path / "proj"
        project_io.save_project(entry, proj)

        # A human hand-edits design.yaml: fills requirements + adds a custom key.
        doc = yaml.safe_load((proj / "design.yaml").read_text(encoding="utf-8"))
        doc["requirements"] = "12V in, 3.3V out, <1mA"
        doc["owner"] = "fingerskier"
        (proj / "design.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")

        loaded = project_io.load_project(proj)
        assert loaded.requirements == "12V in, 3.3V out, <1mA"
        assert loaded.metadata.get("owner") == "fingerskier"

        # Re-saving preserves both.
        project_io.save_project(loaded, proj)
        doc2 = yaml.safe_load((proj / "design.yaml").read_text(encoding="utf-8"))
        assert doc2["requirements"] == "12V in, 3.3V out, <1mA"
        assert doc2["owner"] == "fingerskier"


# ---------------------------------------------------------------------------
# Buses survive a round-trip
# ---------------------------------------------------------------------------


class TestBuses:
    def test_bus_round_trips(self, tmp_path):
        circuit.create_circuit("mcu")
        nets.create_bus("DATA", 4)
        entry = manager.get_active()
        data = project_io.serialize_entry(entry)
        assert data["buses"][0]["name"] == "DATA"
        assert data["buses"][0]["width"] == 4

        proj = tmp_path / "proj"
        project_io.save_project(entry, proj)
        manager.reset()
        project_io.load_circuit(str(proj))
        restored = manager.get_active()
        assert "DATA" in restored.buses
        assert len(restored.buses["DATA"]) == 4


# ---------------------------------------------------------------------------
# Security: loading a project never executes project code
# ---------------------------------------------------------------------------


class TestRobustness:
    def test_non_object_circuit_json_errors_cleanly(self, tmp_path):
        # A circuit.json that is not a JSON object must fail with a clean error,
        # not an unhandled AttributeError from poking at a list/str.
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "circuit.json").write_text("[]", encoding="utf-8")
        resp = project_io.load_circuit(str(proj))
        assert resp["status"] == "error"

    def test_wrong_shape_circuit_json_errors_cleanly(self, tmp_path):
        # Valid JSON but the wrong *shape* (a part that is not an object) must be
        # a clean error, not an unhandled AttributeError/TypeError from indexing.
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "circuit.json").write_text('{"parts": ["not-a-dict"]}', encoding="utf-8")
        resp = project_io.load_circuit(str(proj))
        assert resp["status"] == "error"

    def test_open_project_under_a_file_errors_cleanly(self, tmp_path):
        # A path *under* an existing file passes the file-vs-dir guard (it does not
        # exist) but mkdir raises OSError — the tool must report it, not crash.
        blocker = tmp_path / "blocker.txt"
        blocker.write_text("i am a file", encoding="utf-8")
        resp = project_io.open_project(str(blocker / "project"))
        assert resp["status"] == "error"

    def test_dotted_ref_token_splits_on_last_dot(self):
        # A hierarchical ref that embeds a dot must split ref/pin-num on the LAST
        # dot (rpartition), so pin ordering and re-wiring stay correct.
        assert (project_io._pin_token_key("sub.R1.2")
                < project_io._pin_token_key("sub.R1.10"))
        data = {
            "schema_version": project_io.SCHEMA_VERSION,
            "name": "h", "description": "",
            "parts": [{
                "ref": "sub.R1", "library": "", "name": "R",
                "value": "", "footprint": "", "description": "", "fields": {},
                "pins": [{"num": "1", "name": "p1", "func": ""},
                         {"num": "2", "name": "p2", "func": ""}],
            }],
            "nets": [{"name": "N", "pins": ["sub.R1.2"]}],
            "buses": [], "roles": {}, "interfaces": {},
        }
        entry = project_io.restore_entry(data)
        net = entry.nets["N"]
        assert [f"{p.part.ref}.{p.num}" for p in net.pins] == ["sub.R1.2"]


class TestLoadIsSafe:
    def test_load_does_not_import_circuit_py(self, tmp_path):
        _divider()
        proj = tmp_path / "proj"
        project_io.save_circuit(str(proj))
        # Poison circuit.py so importing/executing it would blow up (or worse).
        (proj / "circuit.py").write_text(
            "raise SystemExit('circuit.py must never be executed on load')\n",
            encoding="utf-8",
        )
        manager.reset()
        resp = project_io.load_circuit(str(proj))
        assert resp["status"] == "ok"
        assert resp["summary"]["parts"] == 2
