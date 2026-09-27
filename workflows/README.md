# Astra local media workflows

Astra can run local ComfyUI API workflows with no API keys.

Export a workflow in **API format** from ComfyUI and save it here.

Supported template placeholders:

- `{{PROMPT}}`
- `{{NEGATIVE}}`
- `{{WIDTH}}`
- `{{HEIGHT}}`
- `{{SEED}}`

Astra does not bundle giant diffusion/video checkpoints. This keeps the core lightweight
and lets the user choose any free local ComfyUI model that fits their hardware.

Example:

```bash
python -m astra_pc generate workflows/my-image.json "a futuristic computer interface"
```
