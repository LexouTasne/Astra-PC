from __future__ import annotations

from abc import ABC, abstractmethod


class InputBackend(ABC):
    @abstractmethod
    def screen_size(self) -> tuple[int, int]: ...

    @abstractmethod
    def move(self, x: int, y: int) -> None: ...

    @abstractmethod
    def left_button(self, down: bool) -> None: ...

    @abstractmethod
    def right_click(self) -> None: ...

    @abstractmethod
    def scroll(self, amount: int) -> None: ...

    @abstractmethod
    def hotkey(self, keys: list[str]) -> None: ...

    @abstractmethod
    def type_text(self, text: str) -> None: ...
