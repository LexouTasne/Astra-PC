from astra_pc.mesh.registry import DeviceRegistry


def test_mesh_token_auth_and_revoke(tmp_path):
    registry = DeviceRegistry(tmp_path / "devices.json")
    token, public = registry.pair("phone-1", "Pixel", "android")
    assert "token_hash" not in public

    device = registry.authenticate(token)
    assert device is not None
    assert device["device_id"] == "phone-1"
    assert registry.has_scope(device, "assistant.ask")
    assert not registry.has_scope(device, "terminal_run")

    assert registry.revoke("phone-1")
    assert registry.authenticate(token) is None
