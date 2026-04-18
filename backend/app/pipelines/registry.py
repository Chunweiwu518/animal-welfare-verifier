from __future__ import annotations

from typing import Type

from app.config import Settings
from app.pipelines.base import BasePipeline

_REGISTRY: dict[str, Type[BasePipeline]] = {}


def register(cls: Type[BasePipeline]) -> Type[BasePipeline]:
    _REGISTRY[cls.platform] = cls
    return cls


def get_pipeline(platform: str, settings: Settings) -> BasePipeline | None:
    cls = _REGISTRY.get(platform)
    if cls is None:
        return None
    instance = cls(settings)
    return instance if instance.is_available() else None


def list_available(settings: Settings) -> list[str]:
    return [
        name for name, cls in _REGISTRY.items()
        if cls(settings).is_available()
    ]


def list_all() -> list[str]:
    return list(_REGISTRY.keys())
