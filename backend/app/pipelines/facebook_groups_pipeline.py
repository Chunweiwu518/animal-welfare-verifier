"""Facebook Groups pipeline.

Strategy:
1. Load the curated public-group URL list from data/fb_animal_welfare_groups.json
2. Once per run, scrape recent posts from all those groups into a shared corpus
   (cached on the pipeline instance)
3. For each entity, filter the corpus by entity name + aliases match and return
   matched posts as that entity's reviews

This avoids scraping the same groups N times when running for many entities.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.pipelines.base import BasePipeline, PipelineResult
from app.pipelines.registry import register
from app.services.scrapers.apify_scraper import crawl_facebook_groups

logger = logging.getLogger(__name__)

DATA_FILE = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "fb_animal_welfare_groups.json"
)

# Module-level corpus cache so a single `run_pipeline --pipeline all` crawl
# doesn't re-scrape the groups once per entity. Key: apify token.
_CORPUS_CACHE: dict[str, list[dict]] = {}


def _load_group_urls() -> list[str]:
    if not DATA_FILE.exists():
        return []
    try:
        payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    groups = payload.get("groups") or []
    return [
        str(g["url"])
        for g in groups
        if isinstance(g, dict) and g.get("url")
    ]


def _matches_entity(content: str, entity_name: str, aliases: list[str]) -> bool:
    if not content:
        return False
    needles = [entity_name, *aliases]
    for n in needles:
        if n and n in content:
            return True
    return False


@register
class FacebookGroupsPipeline(BasePipeline):
    platform = "facebook_groups"

    def is_available(self) -> bool:
        return bool(self.settings.apify_api_token) and bool(_load_group_urls())

    async def _ensure_corpus(self) -> list[dict]:
        token = str(self.settings.apify_api_token or "")
        if token in _CORPUS_CACHE:
            return _CORPUS_CACHE[token]
        group_urls = _load_group_urls()
        if not group_urls:
            _CORPUS_CACHE[token] = []
            return _CORPUS_CACHE[token]
        corpus = await crawl_facebook_groups(
            group_urls,
            token,
            max_posts_per_group=50,
        )
        _CORPUS_CACHE[token] = corpus
        return corpus

    async def crawl_entity(
        self,
        entity_name: str,
        aliases: list[str],
        max_results: int = 30,
    ) -> PipelineResult:
        try:
            corpus = await self._ensure_corpus()
        except Exception as exc:
            return PipelineResult(
                platform=self.platform,
                entity_name=entity_name,
                errors=[str(exc)],
            )

        matches: list[dict] = []
        for post in corpus:
            if not _matches_entity(post.get("content") or "", entity_name, aliases):
                continue
            matches.append({
                "content": post.get("content") or "",
                "author": post.get("author") or "",
                "source_url": post.get("source_url") or "",
                "parent_title": f"[FB 社團] {post.get('group_name','')}".strip()[:120],
                "likes": post.get("likes") or 0,
                "published_at": post.get("published_at"),
                "fetched_at": post.get("fetched_at"),
            })
            if len(matches) >= max_results:
                break

        logger.info(
            "FB groups entity=%s matched=%d / corpus=%d",
            entity_name, len(matches), len(corpus),
        )
        return PipelineResult(
            platform=self.platform,
            entity_name=entity_name,
            reviews=matches,
        )
