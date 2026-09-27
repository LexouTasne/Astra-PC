from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


class ComfyUIError(RuntimeError):
    pass


class ComfyUIClient:
    """Generic local ComfyUI workflow runner; no API key required."""

    def __init__(self, host: str = "http://127.0.0.1:8188", timeout: int = 300):
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.client_id = str(uuid.uuid4())

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(self.host + "/system_stats", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def run_workflow(
        self,
        workflow_path: str | Path,
        *,
        replacements: dict[str, str],
        output_dir: str | Path,
    ) -> list[Path]:
        workflow_path = Path(workflow_path)
        text = workflow_path.read_text(encoding="utf-8")
        for key, value in replacements.items():
            text = text.replace("{{" + key + "}}", value)
        workflow = json.loads(text)

        payload = json.dumps(
            {"prompt": workflow, "client_id": self.client_id}
        ).encode("utf-8")
        req = urllib.request.Request(
            self.host + "/prompt",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            queued = json.loads(r.read().decode("utf-8"))

        prompt_id = queued["prompt_id"]
        history = self._wait_history(prompt_id)
        outputs = history[prompt_id].get("outputs", {})

        target = Path(output_dir)
        target.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []

        for node in outputs.values():
            for kind in ("images", "gifs"):
                for item in node.get(kind, []):
                    filename = item["filename"]
                    query = urllib.parse.urlencode({
                        "filename": filename,
                        "subfolder": item.get("subfolder", ""),
                        "type": item.get("type", "output"),
                    })
                    with urllib.request.urlopen(self.host + "/view?" + query, timeout=60) as r:
                        data = r.read()
                    out = target / Path(filename).name
                    out.write_bytes(data)
                    saved.append(out)

        if not saved:
            raise ComfyUIError("Workflow finished but returned no downloadable media.")
        return saved

    def _wait_history(self, prompt_id: str) -> dict:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            with urllib.request.urlopen(
                self.host + "/history/" + prompt_id,
                timeout=10,
            ) as r:
                history = json.loads(r.read().decode("utf-8"))
            if prompt_id in history:
                return history
            time.sleep(1.0)
        raise ComfyUIError("ComfyUI generation timed out.")
