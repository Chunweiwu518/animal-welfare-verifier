import { FormEvent, useState } from 'react'
import './App.css'

type EvidenceCard = {
  title: string
  url: string
  source: string
  snippet: string
  extracted_at: string | null
  published_at: string | null
  stance: 'supporting' | 'opposing' | 'neutral' | 'unclear'
  claim_type: string
  evidence_strength: 'weak' | 'medium' | 'strong'
  first_hand_score: number
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

const DEFAULT_API_BASE_URL =
  typeof window === 'undefined'
    ? 'http://localhost:8010'
    : `${window.location.protocol}//${window.location.hostname}:8010`
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL

function App() {
  const [entityName, setEntityName] = useState('某某動物園區')
  const [question, setQuestion] = useState('是否有募資不透明或動物福利爭議？')
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
          <p className="eyebrow">Animal Welfare Verifier</p>
          <h1>把網路上的說法拆成可追溯的證據，不只看情緒。</h1>
          <p className="hero-text">
            第一版先聚焦在搜尋公開資料、整理正反觀點、顯示證據卡片，
            讓使用者快速查看一個園區、機構或個人的公開爭議與回應。
          </p>
        </div>

        <form className="query-panel" onSubmit={handleSubmit}>
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
        <section className="results-grid">
          <article className="summary-card">
            <div className="summary-header">
              <div>
                <p className="eyebrow">Balanced Summary</p>
                <h2>平衡判讀</h2>
              </div>
              <span className={`mode-badge mode-${result.mode}`}>
                {result.mode === 'live' ? 'Live Search' : 'Mock Data'}
              </span>
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

          <section className="evidence-section">
            <div className="section-heading">
              <p className="eyebrow">Evidence Cards</p>
              <h2>來源證據</h2>
            </div>

            <div className="evidence-list">
              {result.evidence_cards.map((card) => (
                <article className="evidence-card" key={`${card.url}-${card.title}`}>
                  <div className="evidence-meta">
                    <span className={`stance-badge stance-${card.stance}`}>{card.stance}</span>
                    <span>{card.source}</span>
                    <span>{card.evidence_strength}</span>
                  </div>

                  <h3>
                    <a href={card.url} target="_blank" rel="noreferrer">
                      {card.title}
                    </a>
                  </h3>

                  <p>{card.snippet}</p>

                  <dl className="detail-grid">
                    <div>
                      <dt>Claim</dt>
                      <dd>{card.claim_type}</dd>
                    </div>
                    <div>
                      <dt>First-hand</dt>
                      <dd>{card.first_hand_score}/100</dd>
                    </div>
                    <div>
                      <dt>Published</dt>
                      <dd>{card.published_at ?? '未知'}</dd>
                    </div>
                  </dl>

                  <p className="notes">{card.notes}</p>
                </article>
              ))}
            </div>
          </section>
        </section>
      ) : (
        <section className="empty-state">
          <p className="eyebrow">Workflow</p>
          <h2>輸入查詢後，系統會先擴寫搜尋詞，再整理公開來源與正反觀點。</h2>
          <p>
            這版先支援 web search 型流程，等你給 API key 後就可以切到真實搜尋與 LLM 摘要。
          </p>
        </section>
      )}
    </main>
  )
}

export default App
