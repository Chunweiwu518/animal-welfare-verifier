"""User ratings + credibility scoring routes.

Core UX model:
- Each crawled review gets 1-5 stars from users (credibility rating).
- Shelter's 公信力 score = weighted aggregate:
      supporting_weight = Σ(avg_rating of each supporting review)
      opposing_weight   = Σ(avg_rating of each opposing review)
      neutral_weight    = Σ(avg_rating of each neutral review) × 0.5
      score = supporting / (supporting + opposing) × 100, clamped to 0-100
- Only reviews with ≥1 user rating count; ratings must come from logged-in users.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import json
import uuid
from pathlib import Path as PathLib

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.config import Settings, get_request_settings
from app.routes.auth import current_user, require_user
from app.services.auth_service import AuthUser

router = APIRouter(prefix="/api", tags=["ratings"])


def _db(settings: Settings) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(settings.database_path))
    conn.row_factory = sqlite3.Row
    return conn


class ReviewRatingRequest(BaseModel):
    score: int = Field(ge=1, le=5)


class ReviewReactionRequest(BaseModel):
    reaction: str = Field(pattern=r"^(irrelevant|helpful|unhelpful)$")


class CommentAttachment(BaseModel):
    url: str
    media_type: str  # 'image' | 'video'


class ReviewCommentRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=1000)
    attachments: list[CommentAttachment] = Field(default_factory=list, max_length=3)
    anonymous: bool = False


ALLOWED_IMAGE_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/heic", "image/heif",
}
ALLOWED_VIDEO_TYPES = {
    "video/mp4", "video/quicktime", "video/webm",
}
EXT_MAP = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "image/gif": ".gif", "image/heic": ".heic", "image/heif": ".heif",
    "video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm",
}
MAX_IMAGE_MB = 10
MAX_VIDEO_MB = 80


@router.post("/review-attachments/upload")
async def upload_review_attachment(
    file: UploadFile = File(...),
    user: AuthUser = Depends(require_user),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    ct = (file.content_type or "").lower()
    if ct not in ALLOWED_IMAGE_TYPES and ct not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支援的檔案類型：{ct}",
        )
    media_type = "image" if ct in ALLOWED_IMAGE_TYPES else "video"
    max_mb = MAX_IMAGE_MB if media_type == "image" else MAX_VIDEO_MB

    upload_dir = PathLib(settings.media_upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    ext = EXT_MAP.get(ct, ".bin")
    filename = f"ua-{user.id}-{uuid.uuid4().hex}{ext}"
    dest = upload_dir / filename

    # Stream to disk with size guard
    size_limit = max_mb * 1024 * 1024
    size = 0
    with dest.open("wb") as fh:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > size_limit:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"檔案過大（上限 {max_mb} MB）",
                )
            fh.write(chunk)

    return {
        "url": f"/api/media/file/{filename}",
        "media_type": media_type,
        "size": size,
    }


@router.get("/reviews/{review_id}/comments")
async def list_review_comments(
    review_id: int,
    limit: int = 50,
    settings: Settings = Depends(get_request_settings),
) -> list[dict]:
    with _db(settings) as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.comment, c.created_at, c.attachments_json, c.is_anonymous,
                   CASE WHEN c.is_anonymous = 1 THEN '匿名用戶'
                        ELSE COALESCE(c.display_name, u.display_name, '') END AS display_name,
                   CASE WHEN c.is_anonymous = 1 THEN '' ELSE COALESCE(u.avatar_url, '') END AS avatar_url,
                   u.id AS user_id
            FROM review_comments c
            LEFT JOIN users u ON u.id = c.user_id
            WHERE c.review_id = ?
            ORDER BY c.id ASC
            LIMIT ?
            """,
            (review_id, min(max(limit, 1), 200)),
        ).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        try:
            d["attachments"] = json.loads(d.pop("attachments_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["attachments"] = []
        d["anonymous"] = bool(d.pop("is_anonymous", 0))
        items.append(d)
    return items


@router.post("/reviews/{review_id}/comments")
async def add_review_comment(
    review_id: int,
    request: ReviewCommentRequest,
    user: AuthUser = Depends(require_user),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    comment = request.comment.strip()
    if not comment:
        raise HTTPException(status_code=400, detail="Comment cannot be empty")
    attachments_json = json.dumps(
        [a.model_dump() for a in request.attachments], ensure_ascii=False
    )
    effective_display_name = "匿名用戶" if request.anonymous else user.display_name
    with _db(settings) as conn:
        exists = conn.execute(
            "SELECT 1 FROM reviews WHERE id = ?", (review_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Review not found")
        cur = conn.execute(
            """
            INSERT INTO review_comments
                (review_id, user_id, display_name, comment, attachments_json, is_anonymous)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                user.id,
                effective_display_name,
                comment,
                attachments_json,
                1 if request.anonymous else 0,
            ),
        )
        row = conn.execute(
            """
            SELECT c.id, c.comment, c.created_at, c.display_name, c.attachments_json, c.is_anonymous,
                   CASE WHEN c.is_anonymous = 1 THEN '' ELSE COALESCE(u.avatar_url, '') END AS avatar_url,
                   u.id AS user_id
            FROM review_comments c LEFT JOIN users u ON u.id = c.user_id
            WHERE c.id = ?
            """,
            (cur.lastrowid,),
        ).fetchone()
        conn.commit()
    result = dict(row)
    try:
        result["attachments"] = json.loads(result.pop("attachments_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        result["attachments"] = []
    result["anonymous"] = bool(result.pop("is_anonymous", 0))
    return result


@router.delete("/reviews/{review_id}/comments/{comment_id}")
async def delete_review_comment(
    review_id: int,
    comment_id: int,
    user: AuthUser = Depends(require_user),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    with _db(settings) as conn:
        row = conn.execute(
            "SELECT user_id FROM review_comments WHERE id = ? AND review_id = ?",
            (comment_id, review_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Comment not found")
        if int(row["user_id"]) != user.id:
            raise HTTPException(status_code=403, detail="Not the owner")
        conn.execute("DELETE FROM review_comments WHERE id = ?", (comment_id,))
        conn.commit()
    return {"ok": True}


@router.post("/reviews/{review_id}/rating")
async def rate_review(
    review_id: int,
    request: ReviewRatingRequest,
    user: AuthUser = Depends(require_user),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    with _db(settings) as conn:
        exists = conn.execute("SELECT 1 FROM reviews WHERE id = ?", (review_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Review not found")
        conn.execute(
            """
            INSERT INTO review_ratings (review_id, user_id, score)
            VALUES (?, ?, ?)
            ON CONFLICT(review_id, user_id) DO UPDATE SET
              score = excluded.score,
              updated_at = CURRENT_TIMESTAMP
            """,
            (review_id, user.id, request.score),
        )
        conn.commit()
    return {"ok": True}


@router.delete("/reviews/{review_id}/rating")
async def remove_rating(
    review_id: int,
    user: AuthUser = Depends(require_user),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    with _db(settings) as conn:
        conn.execute(
            "DELETE FROM review_ratings WHERE review_id = ? AND user_id = ?",
            (review_id, user.id),
        )
        conn.commit()
    return {"ok": True}


@router.get("/reviews/{review_id}/rating-summary")
async def review_rating_summary(
    review_id: int,
    user: AuthUser | None = Depends(current_user),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    with _db(settings) as conn:
        agg = conn.execute(
            "SELECT AVG(score) AS avg_score, COUNT(*) AS cnt FROM review_ratings WHERE review_id = ?",
            (review_id,),
        ).fetchone()
        mine = None
        if user is not None:
            row = conn.execute(
                "SELECT score FROM review_ratings WHERE review_id = ? AND user_id = ?",
                (review_id, user.id),
            ).fetchone()
            if row:
                mine = int(row["score"])
    return {
        "avg_score": float(agg["avg_score"]) if agg and agg["avg_score"] is not None else None,
        "count": int(agg["cnt"]) if agg else 0,
        "mine": mine,
    }


@router.post("/reviews/{review_id}/react")
async def react_review(
    review_id: int,
    request: ReviewReactionRequest,
    user: AuthUser = Depends(require_user),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    with _db(settings) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO review_reactions (review_id, user_id, reaction)
            VALUES (?, ?, ?)
            """,
            (review_id, user.id, request.reaction),
        )
        conn.commit()
    return {"ok": True}


@router.delete("/reviews/{review_id}/react")
async def unreact_review(
    review_id: int,
    reaction: str,
    user: AuthUser = Depends(require_user),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    with _db(settings) as conn:
        conn.execute(
            "DELETE FROM review_reactions WHERE review_id = ? AND user_id = ? AND reaction = ?",
            (review_id, user.id, reaction),
        )
        conn.commit()
    return {"ok": True}


@router.get("/entities/{entity_name}/dimensions")
async def entity_dimensions(
    entity_name: str,
    excerpts_per_dim: int = 5,
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """Aggregate per-dimension stats + representative excerpts for an entity.

    Returns mention counts and stance breakdown per dimension, NOT an aggregate
    score — the platform deliberately does not render an overall shelter rating.
    """
    from app.services.dimension_classifier import DIMENSIONS, DIMENSION_LABELS

    with _db(settings) as conn:
        entity = conn.execute(
            "SELECT id FROM entities WHERE name = ?", (entity_name,)
        ).fetchone()
        if not entity:
            entity = conn.execute(
                """
                SELECT e.id FROM entities e
                JOIN entity_keywords k ON k.entity_id = e.id
                WHERE k.keyword = ? AND k.is_active = 1 LIMIT 1
                """,
                (entity_name,),
            ).fetchone()
            if not entity:
                raise HTTPException(status_code=404, detail="Entity not found")
        entity_id = int(entity["id"])

        rows = conn.execute(
            """
            SELECT r.id, r.platform, r.content, r.parent_title, r.source_url,
                   r.published_at, r.dimension_tags_json, r.relevance_score
            FROM reviews r
            WHERE r.entity_id = ? AND r.relevance_score >= 0.6
              AND r.dimension_tags_json IS NOT NULL
              AND r.dimension_tags_json != '[]'
            """,
            (entity_id,),
        ).fetchall()

    per_dim: dict[str, dict] = {
        d: {"dim": d, "label": DIMENSION_LABELS[d], "mention_count": 0,
            "stance_counts": {"supporting": 0, "opposing": 0, "neutral": 0},
            "excerpts": []} for d in DIMENSIONS
    }

    for row in rows:
        try:
            tags = json.loads(row["dimension_tags_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        for tag in tags:
            if not isinstance(tag, dict):
                continue
            dim = tag.get("dim")
            if dim not in per_dim:
                continue
            stance = tag.get("stance", "neutral")
            if stance not in ("supporting", "opposing", "neutral"):
                stance = "neutral"
            per_dim[dim]["mention_count"] += 1
            per_dim[dim]["stance_counts"][stance] += 1
            per_dim[dim]["excerpts"].append({
                "review_id": int(row["id"]),
                "stance": stance,
                "excerpt": str(tag.get("excerpt") or "")[:200],
                "platform": row["platform"],
                "source_url": row["source_url"],
                "published_at": row["published_at"],
            })

    # Pick top excerpts per dim, balanced between supporting/opposing
    for dim_data in per_dim.values():
        excerpts = dim_data["excerpts"]
        supporting = [e for e in excerpts if e["stance"] == "supporting"]
        opposing = [e for e in excerpts if e["stance"] == "opposing"]
        neutral = [e for e in excerpts if e["stance"] == "neutral"]
        half = max(1, excerpts_per_dim // 2)
        picked = supporting[:half] + opposing[:half]
        remaining_slots = max(0, excerpts_per_dim - len(picked))
        picked += neutral[:remaining_slots]
        if len(picked) < excerpts_per_dim:
            overflow = excerpts_per_dim - len(picked)
            picked += supporting[half : half + overflow] + opposing[half : half + overflow]
        dim_data["excerpts"] = picked[:excerpts_per_dim]

    return {
        "entity_name": entity_name,
        "dimensions": list(per_dim.values()),
    }


@router.get("/entities/{entity_name}/credibility")
async def entity_credibility(
    entity_name: str,
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """Calculate public credibility score from user ratings of reviews.

    Returns 0-100 score plus component breakdown.
    """
    with _db(settings) as conn:
        entity = conn.execute(
            "SELECT id FROM entities WHERE name = ?", (entity_name,)
        ).fetchone()
        if not entity:
            # try alias
            entity = conn.execute(
                """
                SELECT e.id FROM entities e
                JOIN entity_keywords k ON k.entity_id = e.id
                WHERE k.keyword = ? AND k.is_active = 1
                LIMIT 1
                """,
                (entity_name,),
            ).fetchone()
            if not entity:
                raise HTTPException(status_code=404, detail="Entity not found")
        entity_id = int(entity["id"])

        rows = conn.execute(
            """
            SELECT r.id, r.stance, AVG(rr.score) AS avg_score, COUNT(rr.id) AS rater_count
            FROM reviews r
            LEFT JOIN review_ratings rr ON rr.review_id = r.id
            WHERE r.entity_id = ?
            GROUP BY r.id
            HAVING rater_count > 0
            """,
            (entity_id,),
        ).fetchall()

    supporting_weight = 0.0
    opposing_weight = 0.0
    neutral_weight = 0.0
    reviews_rated = 0
    total_ratings = 0
    for r in rows:
        stance = str(r["stance"] or "unclear").lower()
        avg = float(r["avg_score"] or 0.0)
        reviews_rated += 1
        total_ratings += int(r["rater_count"] or 0)
        if stance == "supporting":
            supporting_weight += avg
        elif stance == "opposing":
            opposing_weight += avg
        elif stance == "neutral":
            neutral_weight += avg * 0.5

    denom = supporting_weight + opposing_weight + neutral_weight
    score = None
    if denom > 0 and reviews_rated > 0:
        # raw score then pull slightly toward 50 (bayesian prior) for small samples
        raw = (supporting_weight + neutral_weight * 0.5) / denom * 100
        prior_weight = max(0, 5 - reviews_rated) * 10  # smaller reviews → more pull
        score = round((raw * reviews_rated + 50 * prior_weight) / (reviews_rated + prior_weight), 1)

    return {
        "entity_name": entity_name,
        "score": score,
        "reviews_rated": reviews_rated,
        "total_ratings": total_ratings,
        "breakdown": {
            "supporting_weight": round(supporting_weight, 2),
            "opposing_weight": round(opposing_weight, 2),
            "neutral_weight": round(neutral_weight, 2),
        },
    }
