from __future__ import annotations

from abc import ABC, abstractmethod


class InputBackend(ABC):
    @abstractmethod
    def screen_size(self) -> tuple[int, int]: ...

    @abstractmethod
    def move(self, x: int, y: int) -> None: ...

    def move_relative(self, dx: int, dy: int) -> None:
        """Optional relative pointer motion for Air Touch."""
        raise NotImplementedError

    @abstractmethod
    def left_button(self, down: bool) -> None: ...

    @abstractmethod
    def left_click(self) -> None: ...

    @abstractmethod
    def right_click(self) -> None: ...

    def failsafe_release(self) -> None:
        self.left_button(False)

    @abstractmethod
    def scroll(self, amount: int) -> None: ...

    @abstractmethod
    def hotkey(self, keys: list[str]) -> None: ...

    @abstractmethod
    def type_text(self, text: str) -> None: ...
