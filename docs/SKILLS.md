# Astra Skill SDK

Astra discovers optional user skills from:

```text
~/.local/share/astra-pc/skills/
```

A skill is a Python file exposing `create_skill()`.

Example:

```python
from astra_pc.skills.base import Skill, SkillResult

class HelloSkill(Skill):
    name = "hello"
    description = "Simple local example."
    safe_actions = {"hello"}

    def execute(self, action, args):
        if action == "hello":
            return SkillResult(True, "Olá!")
        return SkillResult(False, "unknown action")

def create_skill():
    return HelloSkill()
```

Plugin skills are not automatically trusted. A plugin must explicitly declare `safe_actions` or `confirm_actions`, and unknown actions stay blocked.

Built-in skills currently cover apps, system/media status, files, Git, clipboard, notifications, controlled terminal diagnostics, coding checks and native window placement.
