"""Staerium Python project package initializer."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from .config_loader import load_config

__all__ = ["main", "settings", "CONFIG"]


CONFIG: dict[str, Any] = load_config()


@dataclass(frozen=True)
class Config(Mapping[str, Any]):
    """Minimal mapping/attribute wrapper for the static configuration."""

    _values: dict[str, Any]

    def __getitem__(self, key: str) -> Any:  # type: ignore[override]
        return self._values[key]

    def __iter__(self) -> Iterator[str]:  # type: ignore[override]
        return iter(self._values)

    def __len__(self) -> int:  # type: ignore[override]
        return len(self._values)

    def __getattr__(self, name: str) -> Any:
        try:
            return self._values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __repr__(self) -> str:
        return f"Config({self._values!r})"


settings = Config(CONFIG.copy())

for _key, _value in settings.items():
    normalized = _key.upper()
    if normalized.isidentifier():
        globals()[normalized] = _value
        if normalized not in __all__:
            __all__.append(normalized)

del _key, _value, normalized
