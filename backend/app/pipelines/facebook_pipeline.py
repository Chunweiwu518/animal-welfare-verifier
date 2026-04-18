from __future__ import annotations

from app.pipelines.base import BasePipeline, PipelineResult
from app.pipelines.registry import register
from app.services.scrapers.apify_scraper import (
    crawl_facebook_comments,
    crawl_facebook_posts,
)


def _parse_page_urls(settings_value: str | None) -> dict[str, list[str]]:
    """Parse facebook_page_ids config into a dict of {entity_name_lower: [urls]}.

    Format: "entity1|url1,url2;entity2|url3" or plain comma-separated URLs.
    """
    if not settings_value:
        return {}
    result: dict[str, list[str]] = {}
    for chunk in settings_value.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "|" in chunk:
            name, urls = chunk.split("|", 1)
            result[name.strip().lower()] = [u.strip() for u in urls.split(",") if u.strip()]
        else:
            # Generic fallback — stored as common pool
            result.setdefault("_default", []).extend(u.strip() for u in chunk.split(",") if u.strip())
    return result


def _get_entity_fb_pages(settings, entity_name: str, aliases: list[str]) -> list[str]:
    mapping = _parse_page_urls(settings.facebook_page_ids)
    candidates = [entity_name.lower(), *[a.lower() for a in aliases]]
    for name in candidates:
        if name in mapping:
            return mapping[name]
    return mapping.get("_default", [])


@register
class FacebookPostsPipeline(BasePipeline):
    platform = "facebook_posts"

    def is_available(self) -> bool:
        return bool(self.settings.apify_api_token)

    async def crawl_entity(
        self, entity_name: str, aliases: list[str], max_results: int = 10,
    ) -> PipelineResult:
        page_urls = _get_entity_fb_pages(self.settings, entity_name, aliases)
        if not page_urls:
            return PipelineResult(platform=self.platform, entity_name=entity_name)
        try:
            reviews = await crawl_facebook_posts(
                entity_name,
                apify_token=self.settings.apify_api_token,
                page_urls=page_urls,
                max_results=max_results,
            )
            return PipelineResult(platform=self.platform, entity_name=entity_name, reviews=reviews)
        except Exception as exc:
            return PipelineResult(platform=self.platform, entity_name=entity_name, errors=[str(exc)])


@register
class FacebookCommentsPipeline(BasePipeline):
    platform = "facebook_comments"

    def is_available(self) -> bool:
        return bool(self.settings.apify_api_token)

    async def crawl_entity(
        self, entity_name: str, aliases: list[str], max_results: int = 50,
    ) -> PipelineResult:
        # Need post URLs — first fetch posts, then fetch comments on each
        page_urls = _get_entity_fb_pages(self.settings, entity_name, aliases)
        if not page_urls:
            return PipelineResult(platform=self.platform, entity_name=entity_name)
        try:
            posts = await crawl_facebook_posts(
                entity_name,
                apify_token=self.settings.apify_api_token,
                page_urls=page_urls,
                max_results=5,
            )
            post_urls = [p["source_url"] for p in posts if p.get("source_url")]
            if not post_urls:
                return PipelineResult(platform=self.platform, entity_name=entity_name)
            reviews = await crawl_facebook_comments(
                entity_name,
                apify_token=self.settings.apify_api_token,
                post_urls=post_urls,
                max_results=max_results,
            )
            return PipelineResult(platform=self.platform, entity_name=entity_name, reviews=reviews)
        except Exception as exc:
            return PipelineResult(platform=self.platform, entity_name=entity_name, errors=[str(exc)])
