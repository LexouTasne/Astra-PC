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
        "open_app", "open_url", "close_app", "volume", "media", "window_layout",
        "status", "top_processes", "list_dir", "search_files", "read_file", "count_items",
        "create_dir", "create_text_file", "read_context", "hotkey",
        "git_status", "git_diff", "git_branch",
        "clipboard_read", "clipboard_write", "notify", "project_summary",
        "window_maximize", "window_minimize", "window_snap_left",
        "window_snap_right", "window_move_monitor",
        "mouse_move", "mouse_click", "mouse_right_click", "mouse_scroll",
        "type_text",
        "zoom_in", "zoom_out", "zoom_reset",
        "rotate_left", "rotate_right", "rotation_reset",
    }
    CONFIRM = {
        "write_file", "rename_file", "move_file", "delete_file", "install_package",
        "shutdown", "reboot", "send_message", "git_commit",
        "terminal_run", "run_tests",
    }
    BLOCKED_AUTONOMOUS = {
        "format_disk", "change_password", "purchase",
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
