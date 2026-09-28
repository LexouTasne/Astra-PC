import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("astra_installer", ROOT / "installer.py")
assert SPEC is not None and SPEC.loader is not None
installer = importlib.util.module_from_spec(SPEC)
sys.modules["astra_installer"] = installer
SPEC.loader.exec_module(installer)


def test_parse_droidcam_endpoint_default_port():
    assert installer.parse_droidcam_endpoint("192.168.1.50") == (
        "192.168.1.50",
        4747,
    )


def test_parse_droidcam_endpoint_explicit_port():
    assert installer.parse_droidcam_endpoint("192.168.1.50:4747") == (
        "192.168.1.50",
        4747,
    )


def test_parse_droidcam_endpoint_url():
    assert installer.parse_droidcam_endpoint(
        "http://192.168.1.50:4747/video"
    ) == ("192.168.1.50", 4747)


def test_parse_droidcam_endpoint_invalid():
    assert installer.parse_droidcam_endpoint("") is None
    assert installer.parse_droidcam_endpoint(":99999") is None
