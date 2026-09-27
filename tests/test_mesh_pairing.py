from astra_pc.mesh.pairing import PairingManager


def test_pairing_code_is_one_time(tmp_path):
    pairing = PairingManager(tmp_path / "pairing.json")
    created = pairing.create(ttl_seconds=60)
    code = created["code"]
    assert len(code) == 6
    assert pairing.verify(code)
    assert not pairing.verify(code)


def test_wrong_pairing_code_does_not_consume(tmp_path):
    pairing = PairingManager(tmp_path / "pairing.json")
    created = pairing.create(ttl_seconds=60)
    assert not pairing.verify("000000") or created["code"] == "000000"
    if created["code"] != "000000":
        assert pairing.verify(created["code"])
