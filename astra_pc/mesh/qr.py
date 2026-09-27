from __future__ import annotations

from pathlib import Path


def render_terminal_qr(text: str) -> bool:
    try:
        import qrcode
    except ImportError:
        return False
    qr = qrcode.QRCode(border=1)
    qr.add_data(text)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    on = "██"
    off = "  "
    for row in matrix:
        print("".join(on if cell else off for cell in row))
    return True


def save_qr(text: str, output: str | Path) -> Path:
    try:
        import qrcode
    except ImportError as exc:
        raise RuntimeError("Install Astra mesh extras first.") from exc
    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(text).save(path)
    return path
