"""Phase C tests: declarative design patches (apply_design_patch + schema)."""

import pytest
from skidl import SKIDL, Part, Pin

from skidl_mcp.circuit_manager import manager
from skidl_mcp.tools import circuit, nets, project_io
from skidl_mcp.tools.design_patch import (
    DesignPatch,
    NetPatch,
    PartPatch,
    PatchError,
    apply_design_patch,
    validate_patch,
)


@pytest.fixture(autouse=True)
def clean_manager():
    manager.reset()
    yield
    manager.reset()


class TestSchema:
    def test_from_dict_builds_typed_patch(self):
        p = DesignPatch.from_obj({
            "parts": [{"ref": "R1", "lib": "Device", "name": "R", "value": "10k",
                       "role": "pullup", "fields": {"Tol": "1%"}}],
            "nets": [{"name": "SDA", "role": "i2c_data", "pins": ["U1.SDA", "R1.1"],
                      "pins_mode": "set"}],
            "interfaces": [{"name": "i2c0", "type": "i2c", "nets": {"sda": "SDA"}}],
            "remove_parts": ["R9"],
            "remove_nets": ["OLD"],
            "disconnect": ["R2.2"],
        })
        assert isinstance(p.parts[0], PartPatch)
        assert p.parts[0].ref == "R1" and p.parts[0].value == "10k"
        assert p.parts[0].fields == {"Tol": "1%"}
        assert isinstance(p.nets[0], NetPatch)
        assert p.nets[0].pins == ["U1.SDA", "R1.1"] and p.nets[0].pins_mode == "set"
        assert p.interfaces[0].nets == {"sda": "SDA"}
        assert p.remove_parts == ["R9"] and p.disconnect == ["R2.2"]

    def test_from_yaml_string(self):
        p = DesignPatch.from_obj(
            "parts:\n  - ref: R1\n    lib: Device\n    name: R\n"
            "nets:\n  - name: GND\n    pins: [R1.2]\n"
        )
        assert p.parts[0].ref == "R1"
        assert p.nets[0].name == "GND" and p.nets[0].pins == ["R1.2"]

    def test_empty_patch_is_valid_and_empty(self):
        p = DesignPatch.from_obj({})
        assert p.parts == [] and p.nets == [] and p.remove_parts == []
        p2 = DesignPatch.from_obj(None)
        assert p2.parts == []

    def test_defaults_applied(self):
        p = DesignPatch.from_obj({"nets": [{"name": "N1"}]})
        assert p.nets[0].pins == [] and p.nets[0].pins_mode == "add" and p.nets[0].role == ""

    def test_non_mapping_raises_patch_error(self):
        with pytest.raises(PatchError):
            DesignPatch.from_obj([1, 2, 3])

    def test_bad_yaml_raises_patch_error(self):
        with pytest.raises(PatchError):
            DesignPatch.from_obj("parts: [unclosed")

    def test_part_without_ref_raises(self):
        with pytest.raises(PatchError):
            DesignPatch.from_obj({"parts": [{"lib": "Device", "name": "R"}]})

    def test_bad_pins_mode_raises(self):
        with pytest.raises(PatchError):
            DesignPatch.from_obj({"nets": [{"name": "N", "pins_mode": "wipe"}]})


def _two_resistors():
    """Active circuit with bare R1, R2 (pins 1 & 2). Offline-safe."""
    circuit.create_circuit("c")
    entry = manager.get_active()
    for ref in ("R1", "R2"):
        p = Part(name="R", tool=SKIDL,
                 pins=[Pin(num=1, name="p1"), Pin(num=2, name="p2")],
                 circuit=entry.circuit, ref=ref)
        entry.parts[ref] = p
    return entry


class TestValidate:
    def test_valid_patch_has_no_errors(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({"nets": [{"name": "N", "pins": ["R1.1", "R2.1"]}]})
        assert validate_patch(entry, patch) == []

    def test_bad_pin_token_reports_error(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({"nets": [{"name": "N", "pins": ["R1.99"]}]})
        errors = validate_patch(entry, patch)
        assert errors and "R1.99" in errors[0]

    def test_unknown_part_ref_in_net_reports_error(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({"nets": [{"name": "N", "pins": ["R7.1"]}]})
        errors = validate_patch(entry, patch)
        assert errors and "R7" in errors[0]

    def test_net_may_reference_pin_on_part_created_by_same_patch(self):
        entry = _two_resistors()
        # U1 is being created in this patch; its pins can't be checked offline, so
        # the token is accepted at validation time (checked at apply).
        patch = DesignPatch.from_obj({
            "parts": [{"ref": "U1", "lib": "Device", "name": "R"}],
            "nets": [{"name": "N", "pins": ["U1.1"]}],
        })
        assert validate_patch(entry, patch) == []

    def test_new_part_without_lib_or_name_reports_error(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({"parts": [{"ref": "U1", "lib": "Device"}]})
        errors = validate_patch(entry, patch)
        assert errors and "U1" in errors[0]

    def test_remove_missing_part_reports_error(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({"remove_parts": ["R9"]})
        errors = validate_patch(entry, patch)
        assert errors and "R9" in errors[0]

    def test_disconnect_unknown_ref_reports_error(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({"disconnect": ["R9.1"]})
        errors = validate_patch(entry, patch)
        assert errors and "R9" in errors[0]

    def test_interface_referencing_unknown_net_reports_error(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj(
            {"interfaces": [{"name": "i2c0", "nets": {"sda": "NOPE"}}]})
        errors = validate_patch(entry, patch)
        assert errors and "NOPE" in errors[0]


class TestApplyMerge:
    def test_low_level_and_patch_produce_identical_structure(self):
        # Circuit A: wire with low-level tools.
        circuit.create_circuit("a")
        a = manager.get_active()
        for ref in ("R1", "R2"):
            p = Part(name="R", tool=SKIDL,
                     pins=[Pin(num=1, name="p1"), Pin(num=2, name="p2")],
                     circuit=a.circuit, ref=ref)
            a.parts[ref] = p
        nets.create_net("SDA")
        nets.connect("SDA", "R1", "1")
        nets.connect("SDA", "R2", "1")
        a.parts["R1"].value = "10k"
        data_a = project_io.serialize_entry(a)

        # Circuit B: identical bare parts, one patch does the rest.
        manager.reset()
        circuit.create_circuit("b")
        b = manager.get_active()
        for ref in ("R1", "R2"):
            p = Part(name="R", tool=SKIDL,
                     pins=[Pin(num=1, name="p1"), Pin(num=2, name="p2")],
                     circuit=b.circuit, ref=ref)
            b.parts[ref] = p
        res = apply_design_patch({
            "parts": [{"ref": "R1", "value": "10k"}],
            "nets": [{"name": "SDA", "pins": ["R1.1", "R2.1"]}],
        })
        assert res["status"] == "ok"
        data_b = project_io.serialize_entry(b)
        # Structure identical apart from the circuit name.
        data_a["name"] = data_b["name"] = "x"
        assert data_a == data_b

    def test_diff_reports_what_changed(self):
        _two_resistors()
        res = apply_design_patch({
            "parts": [{"ref": "R1", "value": "1k", "role": "sense"}],
            "nets": [{"name": "N", "role": "signal", "pins": ["R1.1", "R2.1"]}],
            "interfaces": [{"name": "if0", "type": "sig", "nets": {"a": "N"}}],
        })
        assert res["status"] == "ok"
        ap = res["applied"]
        assert ap["nets_created"] == ["N"]
        assert ap["connections_added"] == 2
        assert "R1" in ap["parts_updated"]
        assert "part:R1" in ap["roles_set"] and "net:N" in ap["roles_set"]
        assert ap["interfaces_set"] == ["if0"]

    def test_roles_and_interfaces_stored_on_entry(self):
        entry = _two_resistors()
        apply_design_patch({
            "nets": [{"name": "N", "role": "signal", "pins": ["R1.1"]}],
            "parts": [{"ref": "R1", "role": "sense"}],
            "interfaces": [{"name": "if0", "type": "sig", "nets": {"a": "N"}}],
        })
        assert entry.roles["part:R1"] == "sense"
        assert entry.roles["net:N"] == "signal"
        assert entry.interfaces["if0"] == {"type": "sig", "nets": {"a": "N"}}

    def test_idempotent_reapply_is_empty_diff(self):
        _two_resistors()
        patch = {"parts": [{"ref": "R1", "value": "1k"}],
                 "nets": [{"name": "N", "pins": ["R1.1", "R2.1"]}]}
        first = apply_design_patch(patch)
        assert first["applied"]["connections_added"] == 2
        second = apply_design_patch(patch)
        assert second["status"] == "ok"
        ap = second["applied"]
        assert ap["parts_updated"] == [] and ap["nets_created"] == []
        assert ap["connections_added"] == 0 and ap["roles_set"] == []

    def test_validation_error_mutates_nothing(self):
        entry = _two_resistors()
        before = project_io.serialize_entry(entry)
        res = apply_design_patch({"nets": [{"name": "N", "pins": ["R1.99"]}]})
        assert res["status"] == "error" and res["errors"]
        after = project_io.serialize_entry(entry)
        assert before == after  # atomic: nothing changed

    def test_dry_run_reports_diff_without_mutating(self):
        entry = _two_resistors()
        before = project_io.serialize_entry(entry)
        res = apply_design_patch(
            {"nets": [{"name": "N", "pins": ["R1.1", "R2.1"]}]}, dry_run=True)
        assert res["status"] == "ok" and res.get("dry_run") is True
        assert res["applied"]["connections_added"] == 2
        after = project_io.serialize_entry(entry)
        assert before == after  # nothing actually changed

    def test_mid_apply_throw_rolls_back(self, monkeypatch):
        entry = _two_resistors()
        entry.parts["R1"].value = "10k"
        before = project_io.serialize_entry(entry)
        import skidl_mcp.tools.design_patch as dp

        # Force the connect step to explode after validation passes.
        def boom(*a, **k):
            raise RuntimeError("injected failure")
        monkeypatch.setattr(dp, "_connect_net_pins", boom)

        res = apply_design_patch({"nets": [{"name": "N", "pins": ["R1.1"]}]})
        assert res["status"] == "error" and res.get("rolled_back") is True
        after = project_io.serialize_entry(entry)
        assert before == after  # snapshot restored


class TestRemovals:
    def _wired(self):
        """R1.1-R2.1 on net N; R1.2 on net GND. Returns entry."""
        _two_resistors()
        apply_design_patch({
            "nets": [
                {"name": "N", "pins": ["R1.1", "R2.1"]},
                {"name": "GND", "pins": ["R1.2"]},
            ],
        })
        return manager.get_active()

    def test_remove_parts_detaches_and_deletes(self):
        entry = self._wired()
        res = apply_design_patch({"remove_parts": ["R2"]})
        assert res["status"] == "ok"
        assert res["applied"]["parts_removed"] == ["R2"]
        assert "R2" not in entry.parts
        # R1 untouched.
        assert "R1" in entry.parts

    def test_remove_nets_drops_net_and_disconnects_members(self):
        entry = self._wired()
        res = apply_design_patch({"remove_nets": ["N"]})
        assert res["status"] == "ok"
        assert res["applied"]["nets_removed"] == ["N"]
        assert "N" not in entry.nets
        # R1 pin 1 no longer connected; R1 pin 2 (GND) still is.
        assert not entry.parts["R1"].pins[0].is_connected()
        assert entry.parts["R1"].pins[1].is_connected()

    def test_disconnect_already_unconnected_pin_is_noop(self):
        entry = self._wired()  # R2.2 is not on any net
        res = apply_design_patch({"disconnect": ["R2.2"]})
        assert res["status"] == "ok"
        # the is_connected() guard means an already-free pin removes nothing
        assert res["applied"]["connections_removed"] == 0

    def test_disconnect_specific_pin_only(self):
        entry = self._wired()
        res = apply_design_patch({"disconnect": ["R1.1"]})
        assert res["status"] == "ok"
        assert res["applied"]["connections_removed"] == 1
        assert not entry.parts["R1"].pins[0].is_connected()
        # R2.1 (same net) is untouched.
        assert entry.parts["R2"].pins[0].is_connected()

    def test_pins_mode_set_prunes_unlisted_pins(self):
        entry = self._wired()  # N has R1.1 and R2.1
        res = apply_design_patch(
            {"nets": [{"name": "N", "pins": ["R1.1"], "pins_mode": "set"}]})
        assert res["status"] == "ok"
        assert res["applied"]["connections_removed"] == 1
        assert entry.parts["R1"].pins[0].is_connected()      # kept
        assert not entry.parts["R2"].pins[0].is_connected()  # pruned

    def test_pins_mode_add_keeps_existing(self):
        entry = self._wired()
        res = apply_design_patch(
            {"nets": [{"name": "N", "pins": ["R1.2"], "pins_mode": "add"}]})
        assert res["status"] == "ok"
        # add mode never prunes; R2.1 stays.
        assert res["applied"]["connections_removed"] == 0
        assert res["applied"]["connections_added"] == 1  # R1.2 joined N
        assert entry.parts["R2"].pins[0].is_connected()

    def test_remove_nets_purges_net_from_circuit_graph(self):
        # B1: removal must drop the net from the SKiDL circuit graph, not only
        # from the entry index — a zombie net collides when a later net reuses
        # the name (SKiDL renames the new one 'N1'), desyncing index vs. generators.
        entry = self._wired()
        apply_design_patch({"remove_nets": ["N"]})
        assert "N" not in [x.name for x in entry.circuit.nets]

    def test_remove_then_recreate_same_net_name_keeps_name(self):
        # B1 end-to-end: remove 'N', then re-add a net named 'N'. Without
        # rmv_nets the zombie 'N' survives and the new one becomes 'N1'.
        entry = self._wired()
        apply_design_patch({"remove_nets": ["N"]})
        res = apply_design_patch({"nets": [{"name": "N", "pins": ["R2.1"]}]})
        assert res["status"] == "ok"
        assert entry.nets["N"].name == "N"
        assert "N1" not in [x.name for x in entry.circuit.nets]


class TestRemovalPurgesAnnotations:
    """Removal must keep the roles/interfaces annotation layer in sync with the
    part/net layer — the same desync class as B1 (graph vs. index), one layer up.
    A removed entity must not leave a dangling role or interface net-mapping, and
    a later part reusing the removed ref must NOT inherit the deleted role."""

    def test_remove_part_purges_its_role(self):
        entry = _two_resistors()
        apply_design_patch({"parts": [{"ref": "R1", "role": "sense"}]})
        assert entry.roles.get("part:R1") == "sense"
        apply_design_patch({"remove_parts": ["R1"]})
        assert "part:R1" not in entry.roles

    def test_recreated_part_ref_does_not_inherit_stale_role(self):
        entry = _two_resistors()
        apply_design_patch({"parts": [{"ref": "R1", "role": "sense"}]})
        apply_design_patch({"remove_parts": ["R1"]})
        # A fresh part reusing ref R1 (bare rebuild — offline-safe).
        p = Part(name="R", tool=SKIDL,
                 pins=[Pin(num=1, name="p1"), Pin(num=2, name="p2")],
                 circuit=entry.circuit, ref="R1")
        entry.parts["R1"] = p
        assert entry.roles.get("part:R1") is None  # not the deleted part's "sense"

    def test_remove_net_purges_its_role(self):
        _two_resistors()
        apply_design_patch({"nets": [{"name": "N", "role": "sig", "pins": ["R1.1"]}]})
        entry = manager.get_active()
        assert entry.roles.get("net:N") == "sig"
        apply_design_patch({"remove_nets": ["N"]})
        assert "net:N" not in entry.roles

    def test_remove_net_purges_dangling_interface_mapping(self):
        _two_resistors()
        apply_design_patch({
            "nets": [{"name": "N", "pins": ["R1.1"]}, {"name": "M", "pins": ["R1.2"]}],
            "interfaces": [{"name": "if0", "type": "sig", "nets": {"a": "N", "b": "M"}}],
        })
        entry = manager.get_active()
        apply_design_patch({"remove_nets": ["N"]})
        # if0 must no longer claim to use the removed net N; 'b'->M is untouched.
        assert entry.interfaces["if0"]["nets"] == {"b": "M"}


class TestDuplicateRemovalRefs:
    """B2: duplicate/absent removal refs must be idempotent no-ops, and the
    dry_run path must catch a mid-apply throw the same way the live path does."""

    def test_duplicate_remove_parts_is_idempotent(self):
        entry = _two_resistors()
        res = apply_design_patch({"remove_parts": ["R2", "R2"]})
        assert res["status"] == "ok"
        assert res["applied"]["parts_removed"] == ["R2"]
        assert "R2" not in entry.parts

    def test_duplicate_remove_nets_is_idempotent(self):
        _two_resistors()
        apply_design_patch({"nets": [{"name": "N", "pins": ["R1.1"]}]})
        entry = manager.get_active()
        res = apply_design_patch({"remove_nets": ["N", "N"]})
        assert res["status"] == "ok"
        assert res["applied"]["nets_removed"] == ["N"]
        assert "N" not in entry.nets

    def test_dry_run_duplicate_remove_does_not_crash(self):
        _two_resistors()
        res = apply_design_patch({"remove_parts": ["R2", "R2"]}, dry_run=True)
        assert res["status"] == "ok"
        assert res["applied"]["parts_removed"] == ["R2"]

    def test_dry_run_catches_unexpected_throw(self, monkeypatch):
        _two_resistors()
        import skidl_mcp.tools.design_patch as dp

        def boom(*a, **k):
            raise RuntimeError("injected failure")
        monkeypatch.setattr(dp, "_connect_net_pins", boom)

        res = apply_design_patch(
            {"nets": [{"name": "N", "pins": ["R1.1"]}]}, dry_run=True)
        assert res["status"] == "error"
        assert any("injected failure" in e for e in res["errors"])


def _graph_fingerprint(entry):
    """Net→pins fingerprint read from entry.circuit (the generators' source of
    truth), independent of the entry.nets index. Nets with no pins (e.g. SKiDL's
    '__NOCONNECT') are dropped. This is what a netlist encodes, computed offline."""
    fp = {}
    for net in entry.circuit.nets:
        pins = sorted((p.part.ref, str(p.num)) for p in net.pins)
        if pins:
            fp[net.name] = pins
    return fp


class TestArtifactEquivalence:
    """Spec §10.1 / §11: a patch-built circuit must produce the SAME artifact as
    the equivalent low-level construction. Compares the circuit graph (what the
    netlist/SVG generators read) — not just the serialize_entry index — so a
    graph/index desync (e.g. a lingering removed net) cannot pass unseen."""

    def test_circuit_graph_equivalence_low_level_vs_patch(self):
        # Circuit A: I2C-style pull-ups wired with low-level tools.
        circuit.create_circuit("a")
        a = manager.get_active()
        for ref in ("R1", "R2"):
            p = Part(name="R", tool=SKIDL,
                     pins=[Pin(num=1, name="p1"), Pin(num=2, name="p2")],
                     circuit=a.circuit, ref=ref)
            a.parts[ref] = p
        nets.create_net("SDA")
        nets.connect("SDA", "R1", "1")
        nets.connect("SDA", "R2", "1")
        fp_a = _graph_fingerprint(a)

        # Circuit B: same bare parts, one patch does the wiring.
        manager.reset()
        circuit.create_circuit("b")
        b = manager.get_active()
        for ref in ("R1", "R2"):
            p = Part(name="R", tool=SKIDL,
                     pins=[Pin(num=1, name="p1"), Pin(num=2, name="p2")],
                     circuit=b.circuit, ref=ref)
            b.parts[ref] = p
        res = apply_design_patch({"nets": [{"name": "SDA", "pins": ["R1.1", "R2.1"]}]})
        assert res["status"] == "ok"
        assert _graph_fingerprint(b) == fp_a

    def test_graph_matches_index_after_remove_and_recreate(self):
        # A remove-then-recreate sequence must leave the circuit graph and the
        # entry.nets index describing the SAME nets (regression guard for B1).
        _two_resistors()
        apply_design_patch({"nets": [{"name": "N", "pins": ["R1.1", "R2.1"]}]})
        apply_design_patch({"remove_nets": ["N"]})
        entry = manager.get_active()
        apply_design_patch({"nets": [{"name": "N", "pins": ["R1.2"]}]})
        graph_names = {n.name for n in entry.circuit.nets if n.pins}
        index_names = {net.name for net in entry.nets.values()}
        assert graph_names == index_names == {"N"}


class TestUpdatePartBranches:
    """Spec §4: _update_part sets value, footprint, and custom fields."""

    def test_update_footprint_and_fields(self):
        entry = _two_resistors()
        res = apply_design_patch({"parts": [{
            "ref": "R1",
            "footprint": "Resistor_SMD:R_0805_2012Metric",
            "fields": {"Tolerance": "1%", "MPN": "RC0805"},
        }]})
        assert res["status"] == "ok"
        assert res["applied"]["parts_updated"] == ["R1"]
        assert str(entry.parts["R1"].footprint) == "Resistor_SMD:R_0805_2012Metric"
        assert entry.parts["R1"].fields["Tolerance"] == "1%"
        assert entry.parts["R1"].fields["MPN"] == "RC0805"

    def test_update_is_idempotent_for_footprint_and_fields(self):
        _two_resistors()
        patch = {"parts": [{"ref": "R1", "footprint": "F:R_0805",
                            "fields": {"Tolerance": "1%"}}]}
        apply_design_patch(patch)
        second = apply_design_patch(patch)
        assert second["applied"]["parts_updated"] == []  # nothing re-changed


class TestMultiMatchAndNoCircuit:
    def test_multi_match_pin_name_warns_and_connects_all(self):
        # Spec §4.1: a pin *name* shared by several pins connects all, with a warning.
        circuit.create_circuit("c")
        entry = manager.get_active()
        p = Part(name="R", tool=SKIDL,
                 pins=[Pin(num=1, name="io"), Pin(num=2, name="io")],
                 circuit=entry.circuit, ref="R1")
        entry.parts["R1"] = p
        res = apply_design_patch({"nets": [{"name": "N", "pins": ["R1.io"]}]})
        assert res["status"] == "ok"
        assert res["applied"]["connections_added"] == 2
        assert any("matched 2 pins" in w for w in res["warnings"])

    def test_apply_with_no_active_circuit_errors(self):
        # Spec §7: no active circuit -> error dict, no crash.
        res = apply_design_patch({"nets": [{"name": "N"}]})
        assert res["status"] == "error"
        assert res["errors"]

    def test_malformed_patch_via_apply_returns_error_dict(self):
        _two_resistors()
        res = apply_design_patch("parts: [unclosed")  # bad YAML -> PatchError caught
        assert res["status"] == "error"
        assert res["errors"]


class TestPerEntityValidationErrors:
    def test_multiple_bad_entities_each_reported(self):
        # Spec §11: actionable per-entity errors — one message per defect.
        entry = _two_resistors()
        res = apply_design_patch({
            "nets": [{"name": "N", "pins": ["R1.99"]}],   # bad pin
            "remove_parts": ["R9"],                        # missing part
            "disconnect": ["R8.1"],                        # unknown ref
        })
        assert res["status"] == "error"
        assert len(res["errors"]) >= 3
        assert any("R1.99" in e for e in res["errors"])
        assert any("R9" in e for e in res["errors"])
        assert any("R8" in e for e in res["errors"])


class TestCrossFieldValidation:
    def test_disconnect_of_removed_part_is_rejected(self):
        entry = _two_resistors()
        before = project_io.serialize_entry(entry)
        res = apply_design_patch({"remove_parts": ["R2"], "disconnect": ["R2.1"]})
        assert res["status"] == "error"
        assert any("R2" in e and "remove_parts" in e for e in res["errors"])
        assert project_io.serialize_entry(entry) == before  # nothing mutated

    def test_net_pin_on_removed_part_is_rejected(self):
        entry = _two_resistors()
        res = apply_design_patch({
            "remove_parts": ["R2"],
            "nets": [{"name": "N", "pins": ["R2.1"]}],
        })
        assert res["status"] == "error"
        assert any("R2" in e for e in res["errors"])

    def test_net_pin_on_removed_but_recreated_part_is_allowed_at_validation(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({
            "remove_parts": ["R2"],
            "parts": [{"ref": "R2", "lib": "Device", "name": "R"}],
            "nets": [{"name": "N", "pins": ["R2.1"]}],
        })
        # R2 is re-created, so cross-field validation must NOT flag it; pin
        # resolution on the to-be-created R2 is deferred. No validation errors.
        assert validate_patch(entry, patch) == []

    def test_interface_to_removed_net_is_rejected(self):
        entry = _two_resistors()
        apply_design_patch({"nets": [{"name": "N", "pins": ["R1.1"]}]})
        res = apply_design_patch({
            "remove_nets": ["N"],
            "interfaces": [{"name": "if0", "nets": {"a": "N"}}],
        })
        assert res["status"] == "error"
        assert any("N" in e for e in res["errors"])


def _kicad_available() -> bool:
    try:
        from skidl import Part as _P
        _P("Device", "R", tool=__import__("skidl").KICAD, dest=__import__("skidl").TEMPLATE)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _kicad_available(), reason="needs KiCad symbol libraries")
class TestApplyCreatesPartsFromLibrary:
    def test_patch_creates_library_part(self):
        circuit.create_circuit("c")
        entry = manager.get_active()
        res = apply_design_patch({
            "parts": [{"ref": "R1", "lib": "Device", "name": "R", "value": "10k"}],
        })
        assert res["status"] == "ok"
        assert res["applied"]["parts_added"] == ["R1"]
        assert "R1" in entry.parts
        assert str(entry.parts["R1"].value) == "10k"
