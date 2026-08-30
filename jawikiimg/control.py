from __future__ import annotations

from dataclasses import dataclass, field
from threading import Condition, Event
from typing import Callable, Any


class StopRequested(RuntimeError):
    pass


@dataclass
class Control:
    _stop: Event = field(default_factory=Event)
    _paused: bool = False
    _condition: Condition = field(default_factory=Condition)

    def checkpoint(self) -> None:
        if self._stop.is_set():
            raise StopRequested("safe stop requested")
        with self._condition:
            while self._paused and not self._stop.is_set():
                self._condition.wait(0.5)
        if self._stop.is_set():
            raise StopRequested("safe stop requested")

    def pause(self) -> None:
        with self._condition:
            self._paused = True

    def resume(self) -> None:
        with self._condition:
            self._paused = False
            self._condition.notify_all()

    def stop(self) -> None:
        self._stop.set()
        self.resume()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    @property
    def paused(self) -> bool:
        return self._paused


ProgressCallback = Callable[[dict[str, Any]], None]


def null_progress(event: dict[str, Any]) -> None:
    del event

