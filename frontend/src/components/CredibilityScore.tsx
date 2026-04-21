import { useEffect, useState } from 'react'
import { getEntityCredibility, type EntityCredibility } from '../api/ratings'

interface CredibilityScoreProps {
  entityName: string
  refreshKey?: number
}

export function CredibilityScore({ entityName, refreshKey }: CredibilityScoreProps) {
  const [data, setData] = useState<EntityCredibility | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getEntityCredibility(entityName)
      .then((d) => {
        if (!cancelled) setData(d)
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [entityName, refreshKey])

  if (loading) {
    return (
      <div className="credibility-box">
        <div className="credibility-score">…</div>
        <div className="credibility-label">載入中</div>
      </div>
    )
  }

  if (!data || data.score === null) {
    return (
      <div className="credibility-box credibility-empty">
        <div className="credibility-score">—</div>
        <div className="credibility-label">尚無評分</div>
        <div className="credibility-count">
          {data?.reviews_rated ?? 0} 則評論已評分
        </div>
      </div>
    )
  }

  const level =
    data.score >= 75
      ? 'high'
      : data.score >= 55
        ? 'mid'
        : data.score >= 35
          ? 'low'
          : 'critical'
  const label =
    level === 'high'
      ? '高公信力'
      : level === 'mid'
        ? '中度公信力'
        : level === 'low'
          ? '爭議明顯'
          : '重大疑慮'

  return (
    <div className={`credibility-box credibility-${level}`}>
      <div className="credibility-score">{data.score.toFixed(1)}</div>
      <div className="credibility-label">{label}</div>
      <div className="credibility-count">
        {data.reviews_rated} 則評論 · {data.total_ratings} 次評分
      </div>
    </div>
  )
}
