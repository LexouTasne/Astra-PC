from astra_pc.core.permissions import PermissionLayer


def test_safe_action():
    d = PermissionLayer().evaluate("status")
    assert d.allowed
    assert not d.needs_confirmation


def test_confirmed_class():
    d = PermissionLayer().evaluate("git_commit")
    assert d.allowed
    assert d.needs_confirmation


def test_blocked_action():
    d = PermissionLayer().evaluate("delete_file")
    assert not d.allowed
