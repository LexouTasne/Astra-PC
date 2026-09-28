from __future__ import annotations

import ast
import operator
import re
import subprocess
import sys
import webbrowser
from dataclasses import dataclass


@dataclass(slots=True)
class CommandResult:
    handled: bool
    message: str


class CommandRouter:
    """Fast local intent router. No model or network call is required."""

    def execute(self, text: str) -> CommandResult:
        cmd = " ".join(text.lower().strip().split())

        if not cmd:
            return CommandResult(False, "")

        math_answer = self._math(cmd)
        if math_answer is not None:
            return CommandResult(True, math_answer)

        if re.search(r"\b(abra|abrir|open)\b.*\b(navegador|browser)\b", cmd):
            webbrowser.open("about:blank")
            return CommandResult(True, "Abrindo navegador.")

        if re.search(r"\b(terminal|console)\b", cmd) and re.search(r"\b(abra|abrir|open)\b", cmd):
            self._open_terminal()
            return CommandResult(True, "Abrindo terminal.")

        if re.search(r"\b(pausar|pause|parar controle)\b", cmd):
            return CommandResult(True, "pause_gestures")

        if re.search(r"\b(retomar|resume|continuar controle)\b", cmd):
            return CommandResult(True, "resume_gestures")

        return CommandResult(False, "Comando ainda não mapeado.")

    @staticmethod
    def _math(text: str) -> str | None:
        q = text.lower().strip().rstrip("?.!")
        if not (
            q.startswith("quanto é")
            or q.startswith("quanto e")
            or q.startswith("quanto que é")
            or q.startswith("quanto que e")
            or q.startswith("calcule")
            or q.startswith("calcula")
        ):
            return None

        expr = re.sub(
            r"^(?:quanto(?:\s+que)?\s+[ée]|calcule|calcula)\s*",
            "",
            q,
        ).strip()
        words = {
            "zero": "0", "um": "1", "uma": "1", "dois": "2", "duas": "2",
            "três": "3", "tres": "3", "quatro": "4", "cinco": "5",
            "seis": "6", "sete": "7", "oito": "8", "nove": "9",
            "dez": "10", "onze": "11", "doze": "12", "treze": "13",
            "quatorze": "14", "catorze": "14", "quinze": "15",
            "dezesseis": "16", "dezessete": "17", "dezoito": "18",
            "dezenove": "19", "vinte": "20",
        }
        for word, number in words.items():
            expr = re.sub(rf"\b{word}\b", number, expr)
        expr = re.sub(r"\bdividido\s+por\b", "/", expr)
        expr = re.sub(r"\bvezes\b", "*", expr)
        expr = re.sub(r"\bmais\b", "+", expr)
        expr = re.sub(r"\bmenos\b", "-", expr)
        expr = re.sub(r"\bx\b", "*", expr)
        expr = expr.replace(",", ".")
        if not re.fullmatch(r"[0-9+\-*/().\s]+", expr):
            return None

        ops = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
        }

        def evaluate(node):
            if isinstance(node, ast.Expression):
                return evaluate(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            if isinstance(node, ast.BinOp) and type(node.op) in ops:
                left, right = evaluate(node.left), evaluate(node.right)
                return ops[type(node.op)](left, right)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = evaluate(node.operand)
                return value if isinstance(node.op, ast.UAdd) else -value
            raise ValueError("unsupported expression")

        try:
            value = evaluate(ast.parse(expr, mode="eval"))
        except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
            return None
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return f"É {value}."

    def _open_terminal(self) -> None:
        if sys.platform.startswith("win"):
            subprocess.Popen(["cmd.exe"])
            return
        for terminal in ("kgx", "konsole", "gnome-terminal", "xterm"):
            try:
                subprocess.Popen([terminal])
                return
            except FileNotFoundError:
                continue
