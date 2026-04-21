import { useEffect, useState } from 'react'
import {
  flagReviewIrrelevant,
  getReviewRatingSummary,
  rateReview,
  removeReviewRating,
  type ReviewRatingSummary,
} from '../api/ratings'

interface ReviewRatingBarProps {
  reviewId: number
  isLoggedIn: boolean
  onRequireLogin: () => void
}

export function ReviewRatingBar({
  reviewId,
  isLoggedIn,
  onRequireLogin,
}: ReviewRatingBarProps) {
  const [summary, setSummary] = useState<ReviewRatingSummary | null>(null)
  const [hoverStar, setHoverStar] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [flagged, setFlagged] = useState(false)

  useEffect(() => {
    let cancelled = false
    getReviewRatingSummary(reviewId)
      .then((s) => {
        if (!cancelled) setSummary(s)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [reviewId, isLoggedIn])

  async function handleClick(star: number) {
    if (!isLoggedIn) {
      onRequireLogin()
      return
    }
    setBusy(true)
    try {
      if (summary?.mine === star) {
        await removeReviewRating(reviewId)
      } else {
        await rateReview(reviewId, star)
      }
      setSummary(await getReviewRatingSummary(reviewId))
    } catch (err) {
      if (err instanceof Error && err.message === 'LOGIN_REQUIRED') {
        onRequireLogin()
      }
    } finally {
      setBusy(false)
    }
  }

  async function handleFlag() {
    if (!isLoggedIn) {
      onRequireLogin()
      return
    }
    try {
      await flagReviewIrrelevant(reviewId)
      setFlagged(true)
    } catch (err) {
      if (err instanceof Error && err.message === 'LOGIN_REQUIRED') {
        onRequireLogin()
      }
    }
  }

  const mine = summary?.mine ?? 0
  const hover = hoverStar ?? 0
  const showValue = hover || mine

  return (
    <div className="review-rating-bar">
      <div
        className="rating-stars"
        onMouseLeave={() => setHoverStar(null)}
        role="radiogroup"
        aria-label="這則評論的可信度"
      >
        {[1, 2, 3, 4, 5].map((star) => (
          <button
            key={star}
            type="button"
            role="radio"
            aria-checked={mine === star}
            className={`rating-star${star <= showValue ? ' active' : ''}${mine === star ? ' mine' : ''}`}
            onMouseEnter={() => setHoverStar(star)}
            onClick={() => handleClick(star)}
            disabled={busy}
            title={isLoggedIn ? `打 ${star} 星` : '登入後才能打分'}
          >
            ★
          </button>
        ))}
      </div>
      {summary && summary.count > 0 ? (
        <span className="rating-meta">
          {summary.avg_score?.toFixed(1)}★ · {summary.count} 人
        </span>
      ) : (
        <span className="rating-meta rating-meta-empty">尚無評分</span>
      )}
      <button
        type="button"
        className={`flag-btn${flagged ? ' flagged' : ''}`}
        onClick={handleFlag}
        disabled={flagged}
        title={flagged ? '已標記' : '與此狗園無關 / 應該不列入'}
      >
        🏳️ {flagged ? '已標記' : '不相關'}
      </button>
    </div>
  )
}
