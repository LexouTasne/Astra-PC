from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PermissionDecision:
    allowed: bool
    needs_confirmation: bool
    reason: str = ""


class PermissionLayer:
    """Central policy for tool/skill execution."""

    SAFE = {
        "open_app", "open_url", "volume", "media", "window_layout",
        "status", "search_files", "read_file", "read_context", "hotkey",
        "git_status", "git_diff", "git_branch",
    }
    CONFIRM = {
        "write_file", "rename_file", "move_file", "install_package",
        "shutdown", "reboot", "send_message", "git_commit",
    }
    BLOCKED_AUTONOMOUS = {
        "delete_file", "format_disk", "change_password", "purchase",
        "disable_security",
    }

    def evaluate(self, action: str) -> PermissionDecision:
        if action in self.SAFE:
            return PermissionDecision(True, False)
        if action in self.CONFIRM:
            return PermissionDecision(True, True, "confirmation required")
        if action in self.BLOCKED_AUTONOMOUS:
            return PermissionDecision(False, True, "manual action required")
        return PermissionDecision(False, True, "unknown capability")
