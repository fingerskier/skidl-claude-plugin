"""Tests for CircuitManager and circuit lifecycle."""

import pytest

from skidl_mcp.circuit_manager import CircuitManager


@pytest.fixture
def mgr():
    """Fresh CircuitManager for each test."""
    m = CircuitManager()
    return m


def test_create_circuit(mgr):
    entry = mgr.create("test1", "A test circuit")
    assert entry.name == "test1"
    assert entry.description == "A test circuit"
    assert mgr.active_name == "test1"


def test_create_duplicate_raises(mgr):
    mgr.create("test1")
    with pytest.raises(ValueError, match="already exists"):
        mgr.create("test1")


def test_get_active(mgr):
    mgr.create("c1")
    entry = mgr.get_active()
    assert entry.name == "c1"


def test_get_active_raises_when_none(mgr):
    with pytest.raises(RuntimeError, match="No active circuit"):
        mgr.get_active()


def test_switch_circuit(mgr):
    mgr.create("c1")
    mgr.create("c2")
    assert mgr.active_name == "c2"
    mgr.switch("c1")
    assert mgr.active_name == "c1"


def test_switch_nonexistent_raises(mgr):
    with pytest.raises(KeyError, match="not found"):
        mgr.switch("nope")


def test_delete_circuit(mgr):
    mgr.create("c1")
    mgr.create("c2")
    mgr.delete("c2")
    assert mgr.active_name == "c1"
    assert len(mgr.list_all()) == 1


def test_delete_active_switches(mgr):
    mgr.create("c1")
    mgr.create("c2")
    mgr.switch("c1")
    mgr.delete("c1")
    # Should switch to remaining circuit
    assert mgr.active_name == "c2"


def test_delete_last_circuit(mgr):
    mgr.create("only")
    mgr.delete("only")
    assert mgr.active_name is None


def test_list_all(mgr):
    mgr.create("a", "first")
    mgr.create("b", "second")
    items = mgr.list_all()
    assert len(items) == 2
    names = {i["name"] for i in items}
    assert names == {"a", "b"}
    # Only the last created should be active
    active = [i for i in items if i["is_active"]]
    assert len(active) == 1
    assert active[0]["name"] == "b"


def test_reset(mgr):
    mgr.create("c1")
    mgr.create("c2")
    mgr.reset()
    assert mgr.active_name is None
    assert mgr.list_all() == []


def test_find_part_not_found(mgr):
    mgr.create("c1")
    with pytest.raises(KeyError, match="not found"):
        mgr.find_part("R1")


def test_find_net_not_found(mgr):
    mgr.create("c1")
    with pytest.raises(KeyError, match="not found"):
        mgr.find_net("VCC")
