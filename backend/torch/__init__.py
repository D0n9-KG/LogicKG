from __future__ import annotations

from contextlib import contextmanager


class Tensor:
    def cpu(self) -> "Tensor":
        return self


@contextmanager
def no_grad():
    yield
