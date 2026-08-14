"""Renderer interface for display rendering operations."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Renderer(ABC):
    """Interface for display rendering operations."""

    @abstractmethod
    def render_current_image(self) -> bool: ...

    @abstractmethod
    def render_next_image(self) -> bool: ...

    @abstractmethod
    def render_previous_image(self) -> bool: ...

    @abstractmethod
    def cycle_mode_and_render(self) -> bool: ...

    @abstractmethod
    def get_last_rendered_image_path(self) -> str | None: ...

    def get_last_action(self) -> dict[str, str] | None:
        """Return the last physical button action without clearing it."""
        return None

    def pop_last_action(self) -> dict[str, str] | None:
        """Atomically read and clear the last button action."""
        return None

    def is_render_in_progress(self) -> bool:
        """Return True when a display refresh is in progress."""
        return False