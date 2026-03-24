import { FormEvent, useRef, useState } from 'react'
import './App.css'

type EvidenceCard = {
  title: string
  url: string
  source: string
  source_type: 'official' | 'news' | 'forum' | 'social' | 'other'
  snippet: string
  extracted_at: string | null
  published_at: string | null
  stance: 'supporting' | 'opposing' | 'neutral' | 'unclear'
  claim_type: string
  evidence_strength: 'weak' | 'medium' | 'strong'
  first_hand_score: number
  relevance_score: number
  credibility_score: number
  recency_label: 'recent' | 'dated' | 'unknown'
  duplicate_risk: 'low' | 'medium' | 'high'
  notes: string
}

type SearchResponse = {
  mode: 'live' | 'mock'
  expanded_queries: string[]
  summary: {
    verdict: string
    confidence: number
    supporting_points: string[]
    opposing_points: string[]
    uncertain_points: string[]
    suggested_follow_up: string[]
  }
  evidence_cards: EvidenceCard[]
}

type SourceBreakdownItem = {
  source_type: EvidenceCard['source_type']
  count: number
}

type RecentQueryItem = {
  query_id: number
  question: string
  mode: SearchResponse['mode']
  confidence: number
  created_at: string
}

type EntityProfileResponse = {
  entity_name: string
  total_queries: number
  total_sources: number
  average_confidence: number
  average_credibility: number
  source_breakdown: SourceBreakdownItem[]
  recent_queries: RecentQueryItem[]
}

const DEFAULT_API_BASE_URL =
  typeof window === 'undefined'
    ? 'http://localhost:5173'
    : ''
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL

function getModeLabel(mode: SearchResponse['mode'] | null) {
  if (mode === 'live') {
    return '即時搜尋'
  }

  if (mode === 'mock') {
    return '模擬資料'
  }

  return '待查核'
}

function getStanceLabel(stance: EvidenceCard['stance']) {
  switch (stance) {
    case 'supporting':
      return '支持疑慮'
    case 'opposing':
      return '反駁疑慮'
    case 'neutral':
      return '中性資訊'
    case 'unclear':
      return '立場不明'
  }
}

function getStrengthLabel(strength: EvidenceCard['evidence_strength']) {
  switch (strength) {
    case 'weak':
      return '弱'
    case 'medium':
      return '中'
    case 'strong':
      return '強'
  }
}

function getClaimTypeLabel(claimType: EvidenceCard['claim_type']) {
  switch (claimType) {
    case 'fraud':
      return '詐騙疑慮'
    case 'refund':
      return '退款爭議'
    case 'fundraising':
      return '募資透明'
    case 'animal_welfare':
      return '動物福利'
    case 'general_reputation':
      return '整體評價'
    default:
      return '其他議題'
  }
}

function getSourceTypeLabel(sourceType: EvidenceCard['source_type']) {
  switch (sourceType) {
    case 'official':
      return '官方'
    case 'news':
      return '新聞'
    case 'forum':
      return '論壇'
    case 'social':
      return '社群'
    case 'other':
      return '其他'
  }
}

function getRecencyLabel(recency: EvidenceCard['recency_label']) {
  switch (recency) {
    case 'recent':
      return '近期'
    case 'dated':
      return '較舊'
    case 'unknown':
      return '未取得'
  }
}

function getDuplicateRiskLabel(risk: EvidenceCard['duplicate_risk']) {
  switch (risk) {
    case 'low':
      return '低'
    case 'medium':
      return '中'
    case 'high':
      return '高'
  }
}

function buildSourceTypeSummary(cards: EvidenceCard[]) {
  const counters = {
    official: 0,
    news: 0,
    forum: 0,
    social: 0,
    other: 0,
  }

  for (const card of cards) {
    counters[card.source_type] += 1
  }

  return Object.entries(counters)
    .filter(([, count]) => count > 0)
    .map(([type, count]) => ({
      type: type as EvidenceCard['source_type'],
      count,
      label: getSourceTypeLabel(type as EvidenceCard['source_type']),
    }))
}

function formatDateLabel(value: string | null) {
  if (!value) {
    return null
  }

  const normalized = value.includes('T') ? value.split('T')[0] : value
  return normalized || null
}

function getPublishedDateLabel(card: EvidenceCard) {
  const publishedDate = formatDateLabel(card.published_at)
  if (publishedDate) {
    return publishedDate
  }

  const extractedDate = formatDateLabel(card.extracted_at)
  if (extractedDate) {
    return `未取得，系統擷取於 ${extractedDate}`
  }

  return '未取得'
}

function formatDateTimeLabel(value: string) {
  const normalized = value.includes('T') ? value.replace('T', ' ').slice(0, 16) : value
  return normalized
}

function App() {
  const [entityName, setEntityName] = useState('某某動物園區')
  const [question, setQuestion] = useState('是否有募資不透明或動物福利爭議？')
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [profile, setProfile] = useState<EntityProfileResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const resultSectionRef = useRef<HTMLElement | null>(null)
  const currentModeLabel = getModeLabel(result?.mode ?? null)
  const sourceTypeSummary = result ? buildSourceTypeSummary(result.evidence_cards) : []

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLoading(true)
    setError(null)

    try {
      const response = await fetch(`${API_BASE_URL}/api/search`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          entity_name: entityName,
          question,
        }),
      })

      if (!response.ok) {
        throw new Error('搜尋失敗，請確認後端服務是否已啟動。')
      }

      const data: SearchResponse = await response.json()
      setResult(data)

      const profileResponse = await fetch(
        `${API_BASE_URL}/api/entities/${encodeURIComponent(entityName)}/profile`,
      )
      if (profileResponse.ok) {
        const profileData: EntityProfileResponse = await profileResponse.json()
        setProfile(profileData)
      }

      requestAnimationFrame(() => {
        resultSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : '發生未知錯誤')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="page-shell">
      <section className="hero">
        <div className="hero-copy">
          <div className="hero-topbar">
            <p className="eyebrow">第三方公正平台</p>
            <span className="status-chip">{currentModeLabel}</span>
          </div>
          <h1>動物議題公正查核平台</h1>
          <p className="hero-text">第三方整理公開來源與證據。</p>
        </div>

        <form className="query-panel" onSubmit={handleSubmit}>
          <div className="panel-header">
            <div>
              <p className="eyebrow">開始查核</p>
              <h2>輸入查詢</h2>
            </div>
          </div>

          <label>
            查詢對象
            <input
              value={entityName}
              onChange={(event) => setEntityName(event.target.value)}
              placeholder="例如：某某動物園區"
            />
          </label>

          <label>
            想查的問題
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={4}
              placeholder="例如：是否有退款糾紛、詐騙爭議或動物福利問題？"
            />
          </label>

          <button type="submit" disabled={loading}>
            {loading ? '分析中...' : '開始查核'}
          </button>

          {error ? <p className="error-message">{error}</p> : null}
        </form>
      </section>

      {result ? (
        <section className="results-grid" ref={resultSectionRef}>
          <article className="summary-card">
            <div className="summary-header">
              <div>
                <p className="eyebrow">平衡摘要</p>
                <h2>平衡判讀</h2>
              </div>
              <span className={`mode-badge mode-${result.mode}`}>{getModeLabel(result.mode)}</span>
            </div>

            <p className="verdict">{result.summary.verdict}</p>

            <div className="confidence-row">
              <span>信心值</span>
              <strong>{result.summary.confidence}/100</strong>
            </div>

            <div className="pill-list">
              {result.expanded_queries.map((item) => (
                <span key={item} className="query-pill">
                  {item}
                </span>
              ))}
            </div>

            <div className="source-overview">
              <p className="source-overview-title">本次來源分布</p>
              <div className="source-overview-list">
                {sourceTypeSummary.map((item) => (
                  <span key={item.type} className={`source-type-chip source-type-${item.type}`}>
                    {item.label} {item.count}
                  </span>
                ))}
              </div>
            </div>

            <div className="columns">
              <div>
                <h3>支持疑慮</h3>
                <ul>
                  {result.summary.supporting_points.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>

              <div>
                <h3>反駁或改善</h3>
                <ul>
                  {result.summary.opposing_points.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="columns">
              <div>
                <h3>仍待確認</h3>
                <ul>
                  {result.summary.uncertain_points.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>

              <div>
                <h3>下一步建議</h3>
                <ul>
                  {result.summary.suggested_follow_up.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            </div>
          </article>

          {profile ? (
            <section className="profile-section">
              <div className="section-heading">
                <p className="eyebrow">對象檔案</p>
                <h2>{profile.entity_name}</h2>
              </div>

              <div className="profile-metrics">
                <article>
                  <span>累積查詢</span>
                  <strong>{profile.total_queries}</strong>
                </article>
                <article>
                  <span>累積來源</span>
                  <strong>{profile.total_sources}</strong>
                </article>
                <article>
                  <span>平均信心值</span>
                  <strong>{profile.average_confidence}/100</strong>
                </article>
                <article>
                  <span>平均可信度</span>
                  <strong>{profile.average_credibility}/100</strong>
                </article>
              </div>

              <div className="profile-panels">
                <article className="profile-card">
                  <h3>來源分布</h3>
                  <div className="source-overview-list">
                    {profile.source_breakdown.map((item) => (
                      <span key={item.source_type} className={`source-type-chip source-type-${item.source_type}`}>
                        {getSourceTypeLabel(item.source_type)} {item.count}
                      </span>
                    ))}
                  </div>
                </article>

                <article className="profile-card">
                  <h3>最近查詢</h3>
                  <ul className="recent-query-list">
                    {profile.recent_queries.map((item) => (
                      <li key={item.query_id}>
                        <strong>{item.question}</strong>
                        <span>{getModeLabel(item.mode)}．信心值 {item.confidence}/100．{formatDateTimeLabel(item.created_at)}</span>
                      </li>
                    ))}
                  </ul>
                </article>
              </div>
            </section>
          ) : null}

          <section className="evidence-section">
            <div className="section-heading">
              <p className="eyebrow">來源卡片</p>
              <h2>來源證據</h2>
            </div>

            <div className="evidence-list">
              {result.evidence_cards.map((card) => (
                <article className="evidence-card" key={`${card.url}-${card.title}`}>
                  <div className="evidence-meta">
                    <span className={`stance-badge stance-${card.stance}`}>{getStanceLabel(card.stance)}</span>
                    <span className={`source-type-badge source-type-${card.source_type}`}>
                      {getSourceTypeLabel(card.source_type)}
                    </span>
                    <span className="meta-site">{card.source}</span>
                    <span className="strength-badge">{getStrengthLabel(card.evidence_strength)}強度</span>
                  </div>

                  <h3>
                    <a href={card.url} target="_blank" rel="noreferrer">
                      {card.title}
                    </a>
                  </h3>

                  <p className="snippet">{card.snippet}</p>

                  <dl className="detail-grid">
                    <div>
                      <dt>可信度</dt>
                      <dd>{card.credibility_score}/100</dd>
                    </div>
                    <div>
                      <dt>相關性</dt>
                      <dd>{card.relevance_score}/100</dd>
                    </div>
                    <div>
                      <dt>議題類型</dt>
                      <dd>{getClaimTypeLabel(card.claim_type)}</dd>
                    </div>
                    <div>
                      <dt>第一手程度</dt>
                      <dd>{card.first_hand_score}/100</dd>
                    </div>
                    <div>
                      <dt>發布時間</dt>
                      <dd>{getPublishedDateLabel(card)}</dd>
                    </div>
                    <div>
                      <dt>時間判讀</dt>
                      <dd>{getRecencyLabel(card.recency_label)}</dd>
                    </div>
                    <div>
                      <dt>重複風險</dt>
                      <dd>{getDuplicateRiskLabel(card.duplicate_risk)}</dd>
                    </div>
                  </dl>

                  <p className="notes">{card.notes}</p>

                  <a className="source-link" href={card.url} target="_blank" rel="noreferrer">
                    查看原始來源
                  </a>
                </article>
              ))}
            </div>
          </section>
        </section>
      ) : (
        <section className="empty-state" ref={resultSectionRef}>
          <p className="eyebrow">等待查詢</p>
          <h2>還沒有結果</h2>
          <p>送出查詢後會顯示摘要、來源卡片與對象檔案。</p>
        </section>
      )}
    </main>
  )
}

export default App
