import { ChangeEvent, DragEvent, FormEvent, useEffect, useRef, useState } from 'react'
import './App.css'

type MediaFile = {
  id: number
  entity_name: string
  file_name: string
  original_name: string
  media_type: 'image' | 'video'
  mime_type: string
  file_size: number
  width: number | null
  height: number | null
  caption: string
  created_at: string
  url: string
}

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
  aliases: string[]
  total_queries: number
  total_sources: number
  average_confidence: number
  average_credibility: number
  source_breakdown: SourceBreakdownItem[]
  recent_queries: RecentQueryItem[]
}

type EntityListItem = {
  entity_name: string
  aliases: string[]
  total_queries: number
  total_sources: number
}

type EntityListResponse = {
  items: EntityListItem[]
}

type ReviewFilter =
  | '全部'
  | '最新'
  | '支持疑慮'
  | '反駁疑慮'
  | '官方'
  | '新聞'
  | '論壇'
  | '社群'

const DEFAULT_API_BASE_URL =
  typeof window === 'undefined'
    ? 'http://localhost:5173'
    : ''
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL

const COMMON_QUESTIONS = [
  '是否有動物照顧不當爭議？',
  '是否有募資或財務不透明問題？',
  '是否有官方回應與改善紀錄？',
  '近期評價是偏正面還是偏負面？',
]

const PLATFORM_LABELS = ['Google 評論', 'Facebook', 'Instagram', 'Threads', 'Dcard', 'PTT', '新聞']

type PlatformTab = '本平台' | typeof PLATFORM_LABELS[number]

function matchPlatform(card: EvidenceCard, platform: PlatformTab): boolean {
  if (platform === '本平台') return true
  const src = (card.source + ' ' + card.url).toLowerCase()
  switch (platform) {
    case 'Google 評論': return src.includes('google') || src.includes('maps')
    case 'Facebook': return src.includes('facebook') || src.includes('fb.com')
    case 'Instagram': return src.includes('instagram') || src.includes('ig')
    case 'Threads': return src.includes('threads')
    case 'Dcard': return src.includes('dcard')
    case 'PTT': return src.includes('ptt')
    case '新聞': return card.source_type === 'news'
    default: return true
  }
}

function countPlatformCards(cards: EvidenceCard[], platform: PlatformTab): number {
  return cards.filter((c) => matchPlatform(c, platform)).length
}

function getModeLabel(mode: SearchResponse['mode'] | null) {
  if (mode === 'live') {
    return '即時搜尋'
  }

  if (mode === 'mock') {
    return '模擬資料'
  }

  return '待搜尋'
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

function countByStance(cards: EvidenceCard[], stance: EvidenceCard['stance']) {
  return cards.filter((card) => card.stance === stance).length
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
    return `未取得，擷取於 ${extractedDate}`
  }

  return '未取得'
}

function formatDateTimeLabel(value: string) {
  return value.includes('T') ? value.replace('T', ' ').slice(0, 16) : value
}

function getOverallScore(result: SearchResponse, profile: EntityProfileResponse | null) {
  const sourceScore = profile?.average_credibility ?? result.summary.confidence
  return Math.max(0, Math.min(100, Math.round(sourceScore * 0.55 + result.summary.confidence * 0.45)))
}

function getOverallLabel(score: number) {
  if (score >= 88) {
    return '整體評價穩定'
  }
  if (score >= 74) {
    return '可作為主要參考'
  }
  if (score >= 60) {
    return '評價混合'
  }
  return '需人工補查'
}

function toFivePointScore(score: number) {
  return (score / 20).toFixed(1)
}

function getFilterCount(filter: ReviewFilter, cards: EvidenceCard[]) {
  switch (filter) {
    case '全部':
      return cards.length
    case '最新':
      return cards.filter((card) => card.published_at || card.extracted_at).length
    case '支持疑慮':
      return countByStance(cards, 'supporting')
    case '反駁疑慮':
      return countByStance(cards, 'opposing')
    case '官方':
      return cards.filter((card) => card.source_type === 'official').length
    case '新聞':
      return cards.filter((card) => card.source_type === 'news').length
    case '論壇':
      return cards.filter((card) => card.source_type === 'forum').length
    case '社群':
      return cards.filter((card) => card.source_type === 'social').length
  }
}

function filterEvidenceCards(filter: ReviewFilter, cards: EvidenceCard[]) {
  const sortedCards = [...cards]

  if (filter === '最新') {
    return sortedCards.sort((left, right) => {
      const leftValue = left.published_at ?? left.extracted_at ?? ''
      const rightValue = right.published_at ?? right.extracted_at ?? ''
      return rightValue.localeCompare(leftValue)
    })
  }

  return sortedCards.filter((card) => {
    switch (filter) {
      case '全部':
        return true
      case '支持疑慮':
        return card.stance === 'supporting'
      case '反駁疑慮':
        return card.stance === 'opposing'
      case '官方':
        return card.source_type === 'official'
      case '新聞':
        return card.source_type === 'news'
      case '論壇':
        return card.source_type === 'forum'
      case '社群':
        return card.source_type === 'social'
      default:
        return true
    }
  })
}

function getReviewTone(cards: EvidenceCard[]) {
  const supporting = countByStance(cards, 'supporting')
  const opposing = countByStance(cards, 'opposing')

  if (supporting > opposing + 1) {
    return '近期負面議題較多'
  }

  if (opposing > supporting + 1) {
    return '近期正面與改善資訊較多'
  }

  return '近期評價偏混合'
}

function getFakePlatformReviewCount(cards: EvidenceCard[]) {
  return cards.reduce((total, card) => total + Math.max(1, Math.round(card.credibility_score / 18)), 0)
}

function getIntroParagraph(result: SearchResponse) {
  const firstSupporting = result.summary.supporting_points[0]
  const firstOpposing = result.summary.opposing_points[0]

  if (firstSupporting && firstOpposing) {
    return `${firstSupporting}；同時也有資料指出 ${firstOpposing}。目前較適合把它視為存在爭議、但仍需持續追蹤的對象。`
  }

  if (firstSupporting) {
    return `${firstSupporting}。目前公開資訊以疑慮內容為主，建議補找官方回應與近期改善紀錄。`
  }

  if (firstOpposing) {
    return `${firstOpposing}。目前公開資料偏向改善或緩和說法，但仍建議持續檢查是否有新的爭議。`
  }

  return result.summary.verdict
}

function getMetricBars(cards: EvidenceCard[], overallScore: number) {
  const relevanceAverage = cards.length
    ? Math.round(cards.reduce((sum, card) => sum + card.relevance_score, 0) / cards.length)
    : 0
  const firstHandAverage = cards.length
    ? Math.round(cards.reduce((sum, card) => sum + card.first_hand_score, 0) / cards.length)
    : 0
  const recencyAverage = cards.length
    ? Math.round(
        (cards.filter((card) => card.recency_label === 'recent').length / cards.length) * 100,
      )
    : 0

  return [
    { label: '可信度', value: overallScore },
    { label: '相關性', value: relevanceAverage },
    { label: '第一手程度', value: firstHandAverage },
    { label: '近期資訊比例', value: recencyAverage },
  ]
}

function App() {
  const [entityName, setEntityName] = useState('某某動物園區')
  const [question, setQuestion] = useState('是否有募資不透明或動物福利爭議？')
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [profile, setProfile] = useState<EntityProfileResponse | null>(null)
  const [entityOptions, setEntityOptions] = useState<EntityListItem[]>([])
  const [activeFilter, setActiveFilter] = useState<ReviewFilter>('全部')
  const [activePlatform, setActivePlatform] = useState<PlatformTab>('本平台')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const resultSectionRef = useRef<HTMLElement | null>(null)

  // Media upload state
  const [mediaFiles, setMediaFiles] = useState<MediaFile[]>([])
  const [uploadQueue, setUploadQueue] = useState<{ file: File; progress: number; status: 'pending' | 'uploading' | 'done' | 'error'; errorMsg?: string }[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const [uploadCaption, setUploadCaption] = useState('')
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const reviewFilters: ReviewFilter[] = ['全部', '最新', '支持疑慮', '反駁疑慮', '官方', '新聞', '論壇', '社群']
  const sourceTypeSummary = result ? buildSourceTypeSummary(result.evidence_cards) : []
  const platformCards = result ? result.evidence_cards.filter((c) => matchPlatform(c, activePlatform)) : []
  const visibleCards = result ? filterEvidenceCards(activeFilter, platformCards) : []
  const overallScore = result ? getOverallScore(result, profile) : 0
  const metricBars = result ? getMetricBars(result.evidence_cards, overallScore) : []

  useEffect(() => {
    void loadEntityOptions('')
  }, [])

  async function loadEntityOptions(keyword: string) {
    const target = keyword.trim()
    const suffix = target ? `?q=${encodeURIComponent(target)}` : ''
    const response = await fetch(`${API_BASE_URL}/api/entities${suffix}`)
    if (!response.ok) {
      return
    }

    const data: EntityListResponse = await response.json()
    setEntityOptions(data.items)
  }

  function handleQuestionSelect(nextQuestion: string) {
    setQuestion(nextQuestion)
  }

  function handleEntityPick(item: EntityListItem) {
    setEntityName(item.entity_name)
  }

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
      setActiveFilter('全部')
      setActivePlatform('本平台')

      const profileResponse = await fetch(
        `${API_BASE_URL}/api/entities/${encodeURIComponent(entityName)}/profile`,
      )
      if (profileResponse.ok) {
        const profileData: EntityProfileResponse = await profileResponse.json()
        setProfile(profileData)
      } else {
        setProfile(null)
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

  // ── Media upload helpers ──
  async function loadMediaFiles(entity: string) {
    try {
      const res = await fetch(`${API_BASE_URL}/api/media/list?entity_name=${encodeURIComponent(entity)}&limit=50`)
      if (res.ok) {
        const data = await res.json()
        setMediaFiles(data.items ?? [])
      }
    } catch { /* ignore */ }
  }

  async function uploadSingleFile(file: File, idx: number) {
    setUploadQueue((prev) => prev.map((item, i) => i === idx ? { ...item, status: 'uploading' as const, progress: 0 } : item))

    const formData = new FormData()
    formData.append('file', file)
    formData.append('entity_name', entityName)
    formData.append('caption', uploadCaption)

    try {
      const xhr = new XMLHttpRequest()
      await new Promise<void>((resolve, reject) => {
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            const pct = Math.round((e.loaded / e.total) * 100)
            setUploadQueue((prev) => prev.map((item, i) => i === idx ? { ...item, progress: pct } : item))
          }
        }
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            setUploadQueue((prev) => prev.map((item, i) => i === idx ? { ...item, status: 'done' as const, progress: 100 } : item))
            resolve()
          } else {
            const errMsg = (() => { try { return JSON.parse(xhr.responseText)?.detail } catch { return xhr.statusText } })()
            setUploadQueue((prev) => prev.map((item, i) => i === idx ? { ...item, status: 'error' as const, errorMsg: errMsg } : item))
            reject(new Error(errMsg))
          }
        }
        xhr.onerror = () => {
          setUploadQueue((prev) => prev.map((item, i) => i === idx ? { ...item, status: 'error' as const, errorMsg: '網路錯誤' } : item))
          reject(new Error('Network error'))
        }
        xhr.open('POST', `${API_BASE_URL}/api/media/upload`)
        xhr.send(formData)
      })
    } catch { /* error already set in queue */ }
  }

  async function handleFilesSelected(files: FileList | File[]) {
    const fileArray = Array.from(files)
    if (fileArray.length === 0) return

    const newItems = fileArray.map((f) => ({ file: f, progress: 0, status: 'pending' as const }))
    setUploadQueue((prev) => [...prev, ...newItems])

    const startIdx = uploadQueue.length
    for (let i = 0; i < fileArray.length; i++) {
      await uploadSingleFile(fileArray[i], startIdx + i)
    }

    // Reload media list after all uploads
    await loadMediaFiles(entityName)
  }

  function handleFileInputChange(e: ChangeEvent<HTMLInputElement>) {
    if (e.target.files) {
      void handleFilesSelected(e.target.files)
      e.target.value = ''
    }
  }

  function handleDragOver(e: DragEvent) {
    e.preventDefault()
    setIsDragging(true)
  }

  function handleDragLeave(e: DragEvent) {
    e.preventDefault()
    setIsDragging(false)
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault()
    setIsDragging(false)
    if (e.dataTransfer.files) {
      void handleFilesSelected(e.dataTransfer.files)
    }
  }

  function formatFileSize(bytes: number) {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  function clearCompletedUploads() {
    setUploadQueue((prev) => prev.filter((item) => item.status !== 'done'))
  }

  return (
    <div className="app-shell">
      {/* ── Header ── */}
      <header className="header">
        <div className="header-inner">
          <a href="/" className="logo">
            <span className="logo-icon">🐾</span>
            <span className="logo-text">動保評價</span>
          </a>
          <nav className="nav">
            <a href="#search" className="nav-link active">首頁</a>
            <a href="#search" className="nav-link">園區名單</a>
            <a href="#search" className="nav-link">最新爭議</a>
            <a href="#search" className="nav-link">關於平台</a>
          </nav>
          <div className="header-actions">
            <span className="mode-badge">{getModeLabel(result?.mode ?? null)}</span>
          </div>
        </div>
      </header>

      {/* ── Hero Search ── */}
      <section className="hero" id="search">
        <div className="hero-inner">
          <p className="hero-badge">🛡️ 第三方評論匯整平台</p>
          <h1 className="hero-title">搜尋動保園區，查看全網評論</h1>
          <p className="hero-subtitle">
            匯整 Google、Facebook、PTT、Dcard、新聞等平台的公開評論，AI 摘要分析，一站掌握。
          </p>

          <form className="search-form" onSubmit={handleSubmit}>
            <div className="search-row">
              <div className="search-field">
                <label htmlFor="entity-input">查詢對象</label>
                <input
                  id="entity-input"
                  value={entityName}
                  onChange={(event) => {
                    const nextValue = event.target.value
                    setEntityName(nextValue)
                    void loadEntityOptions(nextValue)
                  }}
                  onFocus={() => void loadEntityOptions(entityName)}
                  placeholder="輸入園區名稱，例如：TSSDA、某某狗園"
                />
              </div>
              <div className="search-field search-field-grow">
                <label htmlFor="question-input">想查的問題</label>
                <input
                  id="question-input"
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="例如：是否有動物福利爭議？"
                />
              </div>
              <button type="submit" className="search-btn" disabled={loading}>
                {loading ? '搜尋中…' : '開始搜尋'}
              </button>
            </div>

            <div className="quick-tags">
              {COMMON_QUESTIONS.map((item) => (
                <button
                  key={item}
                  type="button"
                  className={`quick-tag${question === item ? ' active' : ''}`}
                  onClick={() => handleQuestionSelect(item)}
                >
                  {item}
                </button>
              ))}
            </div>

            {error ? <p className="error-msg">{error}</p> : null}
          </form>

          {entityOptions.length > 0 ? (
            <div className="suggestion-row">
              {entityOptions.slice(0, 5).map((item) => (
                <button
                  key={item.entity_name}
                  type="button"
                  className="suggestion-chip"
                  onClick={() => handleEntityPick(item)}
                >
                  <strong>{item.entity_name}</strong>
                  <span>{item.total_queries} 次查詢</span>
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </section>

      {/* ── Platform Sources ── */}
      <section className="sources-bar">
        <div className="sources-inner">
          <span className="sources-label">資料來源</span>
          {PLATFORM_LABELS.map((item) => (
            <span key={item} className="source-pill">{item}</span>
          ))}
        </div>
      </section>

      {result ? (
        <section className="result-page" ref={resultSectionRef}>
          {/* ── Entity Header ── */}
          <div className="result-container">
            <div className="entity-header-card">
              <div className="entity-header-top">
                <div className="entity-header-info">
                  <a href="#search" className="back-link">← 返回搜尋</a>
                  <h2 className="entity-name">{profile?.entity_name ?? entityName}</h2>
                  {profile?.aliases.length ? (
                    <p className="entity-aliases">別名：{profile.aliases.join('、')}</p>
                  ) : null}
                  <p className="entity-question">🔍 {question}</p>
                </div>
                <div className="score-box">
                  <div className="score-number">{toFivePointScore(overallScore)}</div>
                  <div className="score-label">{getOverallLabel(overallScore)}</div>
                  <div className="score-count">{result.evidence_cards.length} 則來源</div>
                </div>
              </div>

              <p className="entity-intro">{getIntroParagraph(result)}</p>

              <div className="entity-tags">
                <span className="entity-tag">{getReviewTone(result.evidence_cards)}</span>
                <span className="entity-tag">{getFakePlatformReviewCount(result.evidence_cards)} 則整合評論</span>
                {sourceTypeSummary.map((item) => (
                  <span key={item.type} className={`entity-tag tag-${item.type}`}>
                    {item.label} {item.count}
                  </span>
                ))}
              </div>
            </div>

            {/* ── Metrics + Summary Grid ── */}
            <div className="summary-grid">
              <div className="summary-card">
                <h3>📊 分析指標</h3>
                <div className="metrics-list">
                  {metricBars.map((item) => (
                    <div key={item.label} className="metric-row">
                      <span className="metric-name">{item.label}</span>
                      <div className="metric-bar">
                        <div className="metric-fill" style={{ width: `${item.value}%` }} />
                      </div>
                      <span className="metric-val">{item.value}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="summary-card">
                <h3>⚠️ 主要疑慮</h3>
                <ul className="point-list">
                  {result.summary.supporting_points.slice(0, 3).map((item) => (
                    <li key={item} className="point-item concern">{item}</li>
                  ))}
                </ul>
              </div>

              <div className="summary-card">
                <h3>✅ 正面資訊</h3>
                <ul className="point-list">
                  {result.summary.opposing_points.slice(0, 3).map((item) => (
                    <li key={item} className="point-item positive">{item}</li>
                  ))}
                </ul>
              </div>

              <div className="summary-card">
                <h3>❓ 待查證</h3>
                <ul className="point-list">
                  {result.summary.uncertain_points.slice(0, 3).map((item) => (
                    <li key={item} className="point-item uncertain">{item}</li>
                  ))}
                </ul>
              </div>
            </div>

            {/* ── Stats Row ── */}
            <div className="stats-row">
              <div className="stat-card">
                <span className="stat-value">{profile?.total_queries ?? 0}</span>
                <span className="stat-label">累積查詢</span>
              </div>
              <div className="stat-card">
                <span className="stat-value">{profile?.total_sources ?? result.evidence_cards.length}</span>
                <span className="stat-label">累積來源</span>
              </div>
              <div className="stat-card">
                <span className="stat-value">{profile?.average_confidence ?? result.summary.confidence}</span>
                <span className="stat-label">平均把握度</span>
              </div>
              <div className="stat-card">
                <span className="stat-value">{overallScore}</span>
                <span className="stat-label">綜合可信度</span>
              </div>
            </div>

            {/* ── Reviews Section ── */}
            <div className="reviews-section">
              <div className="reviews-header">
                <h3>📝 評論與證據（{result.evidence_cards.length}）</h3>
                <p className="reviews-hint">ⓘ 部分內容已透過 AI 摘要整理</p>
              </div>

              <div className="platform-tabs">
                <button
                  type="button"
                  className={`ptab${activePlatform === '本平台' ? ' active' : ''}`}
                  onClick={() => setActivePlatform('本平台')}
                >
                  本平台 ({result.evidence_cards.length})
                </button>
                {PLATFORM_LABELS.map((label) => {
                  const count = countPlatformCards(result.evidence_cards, label)
                  return (
                    <button
                      key={label}
                      type="button"
                      className={`ptab${activePlatform === label ? ' active' : ''}${count === 0 ? ' disabled' : ''}`}
                      onClick={() => setActivePlatform(label)}
                    >
                      {label}{count > 0 ? ` (${count})` : ''}
                    </button>
                  )
                })}
              </div>

              <div className="filter-bar">
                {reviewFilters.map((filter) => (
                  <button
                    key={filter}
                    type="button"
                    className={`filter-chip${activeFilter === filter ? ' active' : ''}`}
                    onClick={() => setActiveFilter(filter)}
                  >
                    {filter} ({getFilterCount(filter, platformCards)})
                  </button>
                ))}
              </div>

              <div className="review-list">
                {visibleCards.map((card) => (
                  <article className="review-card" key={`${card.url}-${card.title}`}>
                    <div className="review-top">
                      <div className="review-avatar">{card.source.slice(0, 1).toUpperCase()}</div>
                      <div className="review-meta">
                        <span className="review-source-name">{card.source}</span>
                        <span className="review-date">{getPublishedDateLabel(card)}</span>
                      </div>
                      <div className="review-badges">
                        <span className={`stance-badge stance-${card.stance}`}>{getStanceLabel(card.stance)}</span>
                        <span className={`type-badge type-${card.source_type}`}>{getSourceTypeLabel(card.source_type)}</span>
                        <span className="score-badge">{toFivePointScore(card.credibility_score)}</span>
                      </div>
                    </div>

                    <h4 className="review-title">{card.title}</h4>
                    <p className="review-snippet">{card.snippet}</p>

                    <div className="review-tags">
                      <span>{getClaimTypeLabel(card.claim_type)}</span>
                      <span>強度：{getStrengthLabel(card.evidence_strength)}</span>
                      <span>第一手 {card.first_hand_score}</span>
                      <span>相關性 {card.relevance_score}</span>
                      <span>{getRecencyLabel(card.recency_label)}</span>
                    </div>

                    {card.notes ? <p className="review-note">{card.notes}</p> : null}

                    <div className="review-footer">
                      <a href={card.url} target="_blank" rel="noreferrer" className="view-original">
                        查看原文 →
                      </a>
                    </div>
                  </article>
                ))}
              </div>
            </div>

            {/* ── Media Upload ── */}
            <div className="media-section">
              <div className="media-header">
                <h3>📷 上傳證據照片／影片</h3>
                <p className="media-hint">支援 JPG、PNG、WebP、GIF、HEIC、MP4、MOV、WebM（單檔最大 200MB）</p>
              </div>

              <div
                className={`upload-dropzone${isDragging ? ' dragging' : ''}`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*,video/*"
                  multiple
                  hidden
                  onChange={handleFileInputChange}
                />
                <div className="dropzone-content">
                  <span className="dropzone-icon">📁</span>
                  <p className="dropzone-text">拖拉檔案到此區域，或<strong>點擊選擇檔案</strong></p>
                  <p className="dropzone-sub">可一次選取多個檔案</p>
                </div>
              </div>

              <div className="upload-caption-row">
                <input
                  className="caption-input"
                  value={uploadCaption}
                  onChange={(e) => setUploadCaption(e.target.value)}
                  placeholder="備註說明（選填），例如：園區環境照"
                />
              </div>

              {/* Upload Queue */}
              {uploadQueue.length > 0 && (
                <div className="upload-queue">
                  <div className="queue-header">
                    <span>上傳佇列（{uploadQueue.length}）</span>
                    <button type="button" className="clear-done-btn" onClick={clearCompletedUploads}>清除已完成</button>
                  </div>
                  {uploadQueue.map((item, idx) => (
                    <div key={`${item.file.name}-${idx}`} className="queue-item">
                      <span className="queue-name">{item.file.name}</span>
                      <span className="queue-size">{formatFileSize(item.file.size)}</span>
                      <div className="queue-progress-bar">
                        <div
                          className={`queue-progress-fill ${item.status}`}
                          style={{ width: `${item.progress}%` }}
                        />
                      </div>
                      <span className={`queue-status ${item.status}`}>
                        {item.status === 'pending' && '等待中'}
                        {item.status === 'uploading' && `${item.progress}%`}
                        {item.status === 'done' && '✓ 完成'}
                        {item.status === 'error' && `✗ ${item.errorMsg ?? '失敗'}`}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* Media Gallery */}
              {mediaFiles.length > 0 && (
                <div className="media-gallery">
                  <h4>已上傳的檔案（{mediaFiles.length}）</h4>
                  <div className="gallery-grid">
                    {mediaFiles.map((mf) => (
                      <div key={mf.id} className="gallery-item">
                        {mf.media_type === 'image' ? (
                          <img
                            src={`${API_BASE_URL}${mf.url}`}
                            alt={mf.original_name}
                            className="gallery-thumb"
                            loading="lazy"
                          />
                        ) : (
                          <div className="gallery-video-thumb">
                            <span className="video-icon">🎬</span>
                            <span>{mf.original_name}</span>
                          </div>
                        )}
                        <div className="gallery-info">
                          <span className="gallery-name" title={mf.original_name}>{mf.original_name}</span>
                          <span className="gallery-meta">{formatFileSize(mf.file_size)}{mf.caption ? ` · ${mf.caption}` : ''}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {result && mediaFiles.length === 0 && uploadQueue.length === 0 && (
                <button
                  type="button"
                  className="load-media-btn"
                  onClick={() => void loadMediaFiles(entityName)}
                >
                  載入已上傳的檔案
                </button>
              )}
            </div>

            {/* ── History ── */}
            {profile ? (
              <div className="history-section">
                <h3>🕐 近期查詢紀錄</h3>
                <div className="history-list">
                  {profile.recent_queries.map((item) => (
                    <div key={item.query_id} className="history-item">
                      <strong>{item.question}</strong>
                      <span>{formatDateTimeLabel(item.created_at)} · {getModeLabel(item.mode)} · 把握度 {item.confidence}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </section>
      ) : (
        <section className="empty-state" ref={resultSectionRef}>
          <div className="empty-card">
            <div className="empty-icon">🔍</div>
            <h2>輸入園區名稱開始查詢</h2>
            <p>搜尋後將顯示全網評價匯總、AI 分析摘要、以及完整證據列表。</p>
          </div>
        </section>
      )}

      {/* ── Footer ── */}
      <footer className="footer">
        <div className="footer-inner">
          <span>© 2026 動保評價 — 動物福利評論匯整平台</span>
          <span>資料來源：Google、Facebook、PTT、Dcard、新聞媒體等公開平台</span>
        </div>
      </footer>
    </div>
  )
}

export default App
