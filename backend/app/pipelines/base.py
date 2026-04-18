from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.config import Settings


@dataclass
class PipelineResult:
    platform: str
    entity_name: str
    reviews: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class BasePipeline(ABC):
    platform: str

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    async def crawl_entity(
        self,
        entity_name: str,
        aliases: list[str],
        max_results: int = 50,
    ) -> PipelineResult:
        ...

    def is_available(self) -> bool:
        return True
