import { useEffect, useState } from 'react'
import { StanceBar } from './StanceBar'

const DEFAULT_API_BASE_URL =
  typeof window === 'undefined' ? 'http://localhost:5173' : ''
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL

type Stance = 'supporting' | 'opposing' | 'neutral'

interface Excerpt {
  review_id: number
  stance: Stance
  excerpt: string
  platform: string
  source_url: string | null
  published_at: string | null
}

interface Dimension {
  dim: string
  label: string
  mention_count: number
  stance_counts: { supporting: number; opposing: number; neutral: number }
  excerpts: Excerpt[]
}

interface DimensionsResponse {
  entity_name: string
  dimensions: Dimension[]
}

const DIM_ICONS: Record<string, string> = {
  staff_attitude: '🧑‍💼',
  transparency: '📋',
  environment: '🧹',
  animal_care: '🐾',
  communication: '💬',
  adoption_process: '📝',
}

interface DimensionOverviewProps {
  entityName: string
  selectedDim: string | null
  onSelectDim: (dim: string | null) => void
}

export function DimensionOverview({
  entityName,
  selectedDim,
  onSelectDim,
}: DimensionOverviewProps) {
  const [data, setData] = useState<DimensionsResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetch(
      `${API_BASE_URL}/api/entities/${encodeURIComponent(entityName)}/dimensions`,
    )
      .then(async (r) => (r.ok ? ((await r.json()) as DimensionsResponse) : null))
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
  }, [entityName])

  if (loading) {
    return <div className="dim-overview-loading">正在整理各維度資訊…</div>
  }
  if (!data) return null

  const totalMentions = data.dimensions.reduce((sum, d) => sum + d.mention_count, 0)
  if (totalMentions === 0) {
    return (
      <div className="dim-overview-empty">
        尚未有足夠 AI 分類過的評論來呈現維度分佈。稍後等分類完成後重新整理。
      </div>
    )
  }

  return (
    <section className="dim-overview">
      <header className="dim-overview-header">
        <h3>📊 各維度資訊整理</h3>
        <p className="dim-overview-hint">
          點擊某個面向可以看到下方的相關評論。平台只整理分類，不給整體分數 —— 好壞留給你判斷。
        </p>
      </header>

      <div className="dim-grid">
        {data.dimensions.map((dim) => {
          const isActive = selectedDim === dim.dim
          const hasData = dim.mention_count > 0
          return (
            <button
              key={dim.dim}
              type="button"
              className={`dim-card${isActive ? ' active' : ''}${hasData ? '' : ' empty'}`}
              onClick={() => onSelectDim(isActive ? null : dim.dim)}
              disabled={!hasData}
            >
              <div className="dim-card-header">
                <span className="dim-icon">{DIM_ICONS[dim.dim] ?? '📌'}</span>
                <span className="dim-label">{dim.label}</span>
                <span className="dim-count">
                  {hasData ? `${dim.mention_count} 則` : '—'}
                </span>
              </div>

              {hasData ? (
                <>
                  <StanceBar
                    supporting={dim.stance_counts.supporting}
                    opposing={dim.stance_counts.opposing}
                    neutral={dim.stance_counts.neutral}
                  />
                  <div className="dim-excerpts">
                    {dim.excerpts.slice(0, 3).map((e) => (
                      <p
                        key={`${dim.dim}-${e.review_id}-${e.stance}`}
                        className={`dim-excerpt dim-excerpt-${e.stance}`}
                      >
                        <span className="dim-excerpt-marker">
                          {e.stance === 'supporting' ? '＋' : e.stance === 'opposing' ? '−' : '○'}
                        </span>
                        <span>「{e.excerpt}」</span>
                      </p>
                    ))}
                  </div>
                  {dim.mention_count > 3 ? (
                    <div className="dim-card-more">
                      {isActive ? '收起' : `看全部 ${dim.mention_count} 則 →`}
                    </div>
                  ) : null}
                </>
              ) : (
                <p className="dim-card-empty-msg">尚無評論提到這點</p>
              )}
            </button>
          )
        })}
      </div>
    </section>
  )
}
