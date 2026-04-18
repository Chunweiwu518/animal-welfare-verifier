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
  excerpt?: string | null
  ai_summary?: string | null
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
  mode: 'live' | 'mock' | 'cached'
  search_mode: 'general' | 'animal_law'
  animal_focus: boolean
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
  diagnostics: {
    query_count: number
    raw_merged_results: number
    deduplicated_results: number
    low_signal_filtered: number
    relevance_filtered: number
    prioritized_results: number
    final_results: number
    providers: {
      firecrawl_results: number
      serpapi_results: number
      platform_results: number
      cached_results: number
    }
    analysis?: {
      input_results: number
      noise_filtered: number
      low_relevance_filtered: number
      gray_candidates: number
      ai_gray_filtered: number
      final_cards: number
    } | null
  }
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

type EntityPageImageItem = {
  url: string
  alt_text: string
  caption: string
  source_page_url: string
}

type EntityComment = {
  id: number
  entity_name: string
  comment: string
  created_at: string
}

type EntityPageResponse = {
  entity_name: string
  entity_type: string
  aliases: string[]
  headline: string
  introduction: string
  location: string
  cover_image_url: string
  cover_image_alt: string
  gallery: EntityPageImageItem[]
  total_comments: number
  comments: EntityComment[]
  recent_media: MediaFile[]
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

type EntityQuestionSuggestionItem = {
  category: string
  question_text: string
  confidence_score: number
  generated_from: string
}

type EntityQuestionSuggestionsResponse = {
  entity_name: string
  mode: 'general' | 'animal_law'
  animal_focus: boolean
  items: EntityQuestionSuggestionItem[]
}

type EntitySummarySnapshotResponse = {
  entity_name: string
  mode: 'general' | 'animal_law'
  animal_focus: boolean
  source_count: number
  source_window_days: number
  generated_at: string
  summary: SearchResponse['summary']
  evidence_cards: EvidenceCard[]
}

type EvidenceFilter =
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
  '近期整體資訊是偏正面還是偏負面？',
  '有哪些真實心得、官方說法與第三方資料？',
  '最近是否有照護爭議、聲明或負面新聞？',
  'Google、PTT、社群與新聞上怎麼說？',
]

const ANIMAL_FOCUS_QUESTIONS = [
  '是否可能涉及動保法、虐待、棄養或超收問題？',
  '有哪些內容明確提到動物福利、照護或飼養環境疑慮？',
  '最近是否有收容、繁殖、救援、醫療或死亡相關爭議？',
  '目前公開資料可支持哪些動物福利疑慮，哪些部分仍待查？',
]

const PLATFORM_LABELS = ['Google', 'Facebook', 'Instagram', 'Threads', 'Dcard', 'PTT', '新聞', '官方']
const SEARCH_SESSION_STORAGE_KEY = 'animal-welfare-search-session-v1'
const SEARCH_PROGRESS_STEPS = [
  '正在展開爭議、聲明、評論與募資等查詢詞',
  '正在整理 Firecrawl、PTT 與其他公開來源',
  '正在清洗內文並挑出可讀的證據摘錄',
] as const

const ANIMAL_SEARCH_PROGRESS_STEPS = [
  '正在展開動保法、動物福利、照護與稽查相關查詢詞',
  '正在優先整理與收容、繁殖、虐待、棄養有關的公開來源',
  '正在排除非動物相關內容並保守整理可引用證據',
] as const

type PlatformTab = '全部來源' | typeof PLATFORM_LABELS[number]
type SearchSessionState = {
  entityName: string
  question: string
  animalFocus: boolean
  result: SearchResponse | null
  profile: EntityProfileResponse | null
  activeFilter: EvidenceFilter
  activePlatform: PlatformTab
}

type AppRoute =
  | { name: 'home' }
  | { name: 'entity'; entityName: string }

function parseAppRoute(pathname: string): AppRoute {
  const trimmedPath = pathname.replace(/\/+$/, '') || '/'
  if (!trimmedPath.startsWith('/entities/')) {
    return { name: 'home' }
  }

  const rawEntityName = trimmedPath.slice('/entities/'.length)
  if (!rawEntityName) {
    return { name: 'home' }
  }

  try {
    return { name: 'entity', entityName: decodeURIComponent(rawEntityName) }
  } catch {
    return { name: 'home' }
  }
}

function buildEntityPath(entityName: string) {
  return `/entities/${encodeURIComponent(entityName.trim())}`
}

function matchPlatform(card: EvidenceCard, platform: PlatformTab): boolean {
  if (platform === '全部來源') return true
  const src = (card.source + ' ' + card.url).toLowerCase()
  switch (platform) {
    case 'Google': return src.includes('google') || src.includes('maps')
    case 'Facebook': return src.includes('facebook') || src.includes('fb.com')
    case 'Instagram': return src.includes('instagram') || src.includes('ig')
    case 'Threads': return src.includes('threads')
    case 'Dcard': return src.includes('dcard')
    case 'PTT': return src.includes('ptt')
    case '新聞': return card.source_type === 'news'
    case '官方': return card.source_type === 'official'
    default: return true
  }
}

function countPlatformCards(cards: EvidenceCard[], platform: PlatformTab): number {
  return cards.filter((c) => matchPlatform(c, platform)).length
}

function getModeLabel(mode: SearchResponse['mode'] | null) {
  if (mode === 'live') {
    return '即時全網搜尋'
  }

  if (mode === 'cached') {
    return '資料庫快取'
  }

  if (mode === 'mock') {
    return '示例資料'
  }

  return '待搜尋'
}

function getSearchModeLabel(result: SearchResponse | null, animalFocus: boolean) {
  const focusEnabled = result?.animal_focus ?? animalFocus
  return focusEnabled ? '動保法模式' : '一般模式'
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

function getPlatformLabel(card: EvidenceCard) {
  const sourceText = `${card.source} ${card.url}`.toLowerCase()
  if (sourceText.includes('dcard')) return 'Dcard'
  if (sourceText.includes('ptt.cc') || sourceText.includes(' ptt')) return 'PTT'
  if (sourceText.includes('facebook') || sourceText.includes('fb.com')) return 'Facebook'
  if (sourceText.includes('instagram')) return 'Instagram'
  if (sourceText.includes('threads.net') || sourceText.includes('threads')) return 'Threads'
  if (sourceText.includes('google') || sourceText.includes('maps')) return 'Google'
  if (card.source_type === 'news') return '新聞'
  if (card.source_type === 'official') return '官方'
  return '其他'
}

function getCardExcerpt(card: EvidenceCard) {
  return card.excerpt?.trim() || card.snippet?.trim() || '目前沒有可用的相關段落。'
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

function getFilterCount(filter: EvidenceFilter, cards: EvidenceCard[]) {
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

function filterEvidenceCards(filter: EvidenceFilter, cards: EvidenceCard[]) {
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

    return '近期資訊偏混合'
}

function getEvidenceCount(cards: EvidenceCard[]) {
  return cards.length
}

function getIntroParagraph(result: SearchResponse) {
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

function getEvidenceOriginLabel(card: EvidenceCard) {
  if (card.source_type === 'official') {
    return '官方說明'
  }
  if (card.first_hand_score >= 75) {
    return '第一手描述'
  }
  if (card.source_type === 'news') {
    return '新聞轉述'
  }
  if ((card.source_type === 'forum' || card.source_type === 'social') && card.first_hand_score >= 55) {
    return '社群第一手貼文'
  }
  if (card.source_type === 'forum' || card.source_type === 'social') {
    return '社群討論'
  }
  return '整理資料'
}

function getEvidenceOriginClassName(card: EvidenceCard) {
  if (card.source_type === 'official') {
    return 'origin-official'
  }
  if (card.first_hand_score >= 75) {
    return 'origin-first-hand'
  }
  if (card.source_type === 'news') {
    return 'origin-reported'
  }
  return 'origin-aggregated'
}

function getMetricDescription(label: string, value: number) {
  switch (label) {
    case '第一手程度':
      if (value >= 70) return '多數來源帶有現場觀察、官方公告或直接敘述。'
      if (value >= 45) return '目前以混合來源為主，包含部分轉述與間接說法。'
      return '多數內容偏新聞轉述、訪談引述或二手整理，不能直接當成定論。'
    case '相關性':
      return value >= 70 ? '多數結果有直接提到查詢主體。' : '部分結果仍需要人工確認是否真的與主體直接相關。'
    case '近期資訊比例':
      return value >= 50 ? '近期資料比例足夠。' : '近期資料偏少，建議補抓近一年來源。'
    default:
      return value >= 70 ? '可作為主要參考，但仍應交叉驗證。' : '目前只適合作為初步線索。'
  }
}

function buildStoredSession(state: SearchSessionState) {
  return JSON.stringify(state)
}

function App() {
  const [route, setRoute] = useState<AppRoute>(() => parseAppRoute(window.location.pathname))
  const [entityName, setEntityName] = useState('')
  const [question, setQuestion] = useState('')
  const [animalFocus, setAnimalFocus] = useState(false)
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [profile, setProfile] = useState<EntityProfileResponse | null>(null)
  const [entityPageData, setEntityPageData] = useState<EntityPageResponse | null>(null)
  const [entityOptions, setEntityOptions] = useState<EntityListItem[]>([])
  const [entitySnapshot, setEntitySnapshot] = useState<EntitySummarySnapshotResponse | null>(null)
  const [entityQuestions, setEntityQuestions] = useState<EntityQuestionSuggestionItem[]>([])
  const [activeFilter, setActiveFilter] = useState<EvidenceFilter>('全部')
  const [activePlatform, setActivePlatform] = useState<PlatformTab>('全部來源')
  const [loading, setLoading] = useState(false)
  const [entityPageLoading, setEntityPageLoading] = useState(false)
  const [entityPageError, setEntityPageError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [searchStepIndex, setSearchStepIndex] = useState(0)
  const resultSectionRef = useRef<HTMLElement | null>(null)

  // Media upload state
  const [mediaFiles, setMediaFiles] = useState<MediaFile[]>([])
  const [uploadQueue, setUploadQueue] = useState<{ file: File; progress: number; status: 'pending' | 'uploading' | 'done' | 'error'; errorMsg?: string }[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const [uploadComment, setUploadComment] = useState('')
  const [commentSubmitting, setCommentSubmitting] = useState(false)
  const [commentError, setCommentError] = useState<string | null>(null)
  const [hiddenBrokenImages, setHiddenBrokenImages] = useState<Record<string, boolean>>({})
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  // Crawled reviews state
  type CrawledReview = {
    id: number
    platform: string
    author: string | null
    content: string
    sentiment: string | null
    rating: number | null
    source_url: string
    parent_title: string | null
    likes: number
    published_at: string | null
    fetched_at: string
  }
  const [crawledReviews, setCrawledReviews] = useState<CrawledReview[]>([])
  const [reviewStats, setReviewStats] = useState<Record<string, number>>({})
  const [reviewPlatformTab, setReviewPlatformTab] = useState<string>('all')
  const [reviewsLoading, setReviewsLoading] = useState(false)

  // Autocomplete state
  type SuggestItem = { name: string; aliases: string[]; review_count: number }
  const [suggestions, setSuggestions] = useState<SuggestItem[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const suggestTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const evidenceFilters: EvidenceFilter[] = ['全部', '最新', '支持疑慮', '反駁疑慮', '官方', '新聞', '論壇', '社群']
  const isEntityRoute = route.name === 'entity'
  const quickQuestions = entityQuestions.length
    ? entityQuestions.map((item) => item.question_text)
    : (animalFocus ? ANIMAL_FOCUS_QUESTIONS : COMMON_QUESTIONS)
  const searchProgressSteps = animalFocus ? ANIMAL_SEARCH_PROGRESS_STEPS : SEARCH_PROGRESS_STEPS
  const questionPlaceholder = animalFocus
    ? '例如：是否可能涉及動保法、超收、飼養環境或照護問題？'
    : '例如：是否有動物福利爭議？'
  const sourceTypeSummary = result ? buildSourceTypeSummary(result.evidence_cards) : []
  const platformCards = result ? result.evidence_cards.filter((c) => matchPlatform(c, activePlatform)) : []
  const visibleCards = result ? filterEvidenceCards(activeFilter, platformCards) : []
  const overallScore = result ? getOverallScore(result, profile) : 0
  const metricBars = result ? getMetricBars(result.evidence_cards, overallScore) : []
  const entityPagePlatformCards = entitySnapshot ? entitySnapshot.evidence_cards.filter((card) => matchPlatform(card, activePlatform)) : []
  const entityPageVisibleCards = entitySnapshot ? filterEvidenceCards(activeFilter, entityPagePlatformCards).slice(0, 6) : []
  const entityPageSourceSummary = entitySnapshot ? buildSourceTypeSummary(entitySnapshot.evidence_cards) : []
  const entityPageScore = entitySnapshot
    ? Math.max(0, Math.min(100, Math.round((profile?.average_credibility ?? entitySnapshot.summary.confidence) * 0.5 + entitySnapshot.summary.confidence * 0.5)))
    : 0
  const selectedEntityLabel = entityPageData?.entity_name ?? profile?.entity_name ?? entitySnapshot?.entity_name ?? entityName

  useEffect(() => {
    try {
      const raw = window.sessionStorage.getItem(SEARCH_SESSION_STORAGE_KEY)
      if (route.name === 'entity') {
        setEntityName(route.entityName)
        if (!raw) {
          void loadEntityOptions(route.entityName)
          return
        }

        const restored = JSON.parse(raw) as SearchSessionState
        if (restored.entityName === route.entityName) {
          setQuestion(restored.question)
          setAnimalFocus(Boolean(restored.animalFocus))
          setResult(restored.result)
          setProfile(restored.profile)
          setActiveFilter(restored.activeFilter)
          setActivePlatform(restored.activePlatform)
        }
        void loadEntityOptions(route.entityName)
        return
      }

      if (!raw) {
        void loadEntityOptions('')
        return
      }

      const restored = JSON.parse(raw) as SearchSessionState
      setEntityName(restored.entityName)
      setQuestion(restored.question)
      setAnimalFocus(Boolean(restored.animalFocus))
      setResult(restored.result)
      setProfile(restored.profile)
      setActiveFilter(restored.activeFilter)
      setActivePlatform(restored.activePlatform)
      void loadEntityOptions(restored.entityName)
    } catch {
      void loadEntityOptions('')
    }
  }, [])

  useEffect(() => {
    function handlePopState() {
      setRoute(parseAppRoute(window.location.pathname))
    }

    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  useEffect(() => {
    if (route.name !== 'entity') {
      setEntityPageData(null)
      setEntityPageError(null)
      setEntityPageLoading(false)
      setCommentError(null)
      setHiddenBrokenImages({})
      return
    }

    if (entityName.trim() !== route.entityName.trim()) {
      setResult(null)
      setProfile(null)
      setEntityPageData(null)
      setMediaFiles([])
      setUploadComment('')
    }

    setEntityName(route.entityName)
  }, [entityName, route])

  useEffect(() => {
    setHiddenBrokenImages({})
  }, [entityPageData?.entity_name, entityPageData?.cover_image_url, entityPageData?.gallery.length])

  useEffect(() => {
    try {
      window.sessionStorage.setItem(
        SEARCH_SESSION_STORAGE_KEY,
        buildStoredSession({
          entityName,
          question,
          animalFocus,
          result,
          profile,
          activeFilter,
          activePlatform,
        }),
      )
    } catch {
      // Ignore storage failures on restricted browsers.
    }
  }, [activeFilter, activePlatform, animalFocus, entityName, profile, question, result])

  useEffect(() => {
    if (!loading) {
      setSearchStepIndex(0)
      return
    }

    const timer = window.setInterval(() => {
      setSearchStepIndex((previous) => (previous + 1) % searchProgressSteps.length)
    }, 1200)

    return () => window.clearInterval(timer)
  }, [loading, searchProgressSteps])

  useEffect(() => {
    if (result) {
      void loadMediaFiles(entityName)
    }
  }, [entityName, result])

  useEffect(() => {
    if (isEntityRoute) {
      return
    }

    const target = entityName.trim()
    if (target.length < 2) {
      setEntitySnapshot(null)
      setEntityQuestions([])
      return
    }

    const timer = window.setTimeout(() => {
      void loadEntityDatabasePreview(target, animalFocus)
    }, 250)

    return () => window.clearTimeout(timer)
  }, [animalFocus, entityName, isEntityRoute])

  useEffect(() => {
    if (route.name !== 'entity') {
      return
    }

    const target = route.entityName.trim()
    if (target.length < 2) {
      setEntityPageError('實體名稱格式不正確。')
      return
    }

    let isCurrent = true
    setEntityPageLoading(true)
    setEntityPageError(null)

    void (async () => {
      const [previewData, profileData, pageData, mediaData] = await Promise.all([
        loadEntityDatabasePreview(target, animalFocus),
        loadEntityProfile(target),
        loadEntityPage(target),
        loadMediaFiles(target),
      ])

      if (!isCurrent) {
        return
      }

      const hasAnyData = Boolean(previewData.snapshot || previewData.suggestions.length || profileData || pageData || mediaData.length)
      if (!hasAnyData) {
        setEntityPageError('目前這個實體還沒有整理完成，可先送出一次搜尋建立摘要。')
      }
      setEntityPageLoading(false)
    })()

    return () => {
      isCurrent = false
    }
  }, [animalFocus, route])

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

  async function loadEntityDatabasePreview(targetEntity: string, focusEnabled: boolean) {
    const suffix = focusEnabled ? '?animal_focus=true' : ''

    try {
      const [snapshotResponse, suggestionsResponse] = await Promise.all([
        fetch(`${API_BASE_URL}/api/entities/${encodeURIComponent(targetEntity)}/snapshot${suffix}`),
        fetch(`${API_BASE_URL}/api/entities/${encodeURIComponent(targetEntity)}/suggestions${suffix}`),
      ])

      let snapshotData: EntitySummarySnapshotResponse | null = null
      if (snapshotResponse.ok) {
        snapshotData = await snapshotResponse.json()
        setEntitySnapshot(snapshotData)
      } else {
        setEntitySnapshot(null)
      }

      let suggestionItems: EntityQuestionSuggestionItem[] = []
      if (suggestionsResponse.ok) {
        const suggestionsData: EntityQuestionSuggestionsResponse = await suggestionsResponse.json()
        suggestionItems = suggestionsData.items
        setEntityQuestions(suggestionsData.items)
      } else {
        setEntityQuestions([])
      }

      return {
        snapshot: snapshotData,
        suggestions: suggestionItems,
      }
    } catch {
      setEntitySnapshot(null)
      setEntityQuestions([])
      return {
        snapshot: null,
        suggestions: [] as EntityQuestionSuggestionItem[],
      }
    }
  }

  async function loadEntityProfile(targetEntity: string) {
    try {
      const profileResponse = await fetch(
        `${API_BASE_URL}/api/entities/${encodeURIComponent(targetEntity)}/profile`,
      )
      if (!profileResponse.ok) {
        setProfile(null)
        return null
      }

      const profileData: EntityProfileResponse = await profileResponse.json()
      setProfile(profileData)
      return profileData
    } catch {
      setProfile(null)
      return null
    }
  }

  async function loadEntityPage(targetEntity: string) {
    try {
      const pageResponse = await fetch(
        `${API_BASE_URL}/api/entities/${encodeURIComponent(targetEntity)}/page`,
      )
      if (!pageResponse.ok) {
        setEntityPageData(null)
        return null
      }

      const pageData: EntityPageResponse = await pageResponse.json()
      setEntityPageData(pageData)

      // Load crawled reviews and stats in parallel
      loadCrawledReviews(targetEntity)

      return pageData
    } catch {
      setEntityPageData(null)
      return null
    }
  }

  async function loadCrawledReviews(targetEntity: string, platform?: string) {
    setReviewsLoading(true)
    try {
      const enc = encodeURIComponent(targetEntity)
      const platformParam = platform && platform !== 'all' ? `&platform=${platform}` : ''
      const [reviewsRes, statsRes] = await Promise.all([
        fetch(`${API_BASE_URL}/api/entities/${enc}/reviews?limit=50${platformParam}`),
        fetch(`${API_BASE_URL}/api/entities/${enc}/reviews/stats`),
      ])
      if (reviewsRes.ok) {
        setCrawledReviews(await reviewsRes.json())
      }
      if (statsRes.ok) {
        setReviewStats(await statsRes.json())
      }
    } catch {
      // silent
    } finally {
      setReviewsLoading(false)
    }
  }

  function handleReviewPlatformTab(platform: string) {
    setReviewPlatformTab(platform)
    if (route.name === 'entity') {
      loadCrawledReviews(route.entityName, platform)
    }
  }

  function handleSuggestInput(value: string) {
    setEntityName(value)
    if (suggestTimeoutRef.current) clearTimeout(suggestTimeoutRef.current)
    if (value.trim().length < 1) {
      setSuggestions([])
      setShowSuggestions(false)
      return
    }
    suggestTimeoutRef.current = setTimeout(async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/entities/suggest?q=${encodeURIComponent(value)}&limit=8`)
        if (res.ok) {
          const data: SuggestItem[] = await res.json()
          setSuggestions(data)
          setShowSuggestions(data.length > 0)
        }
      } catch {
        // silent
      }
    }, 300)
  }

  function handleSuggestPick(item: SuggestItem) {
    setEntityName(item.name)
    setSuggestions([])
    setShowSuggestions(false)
    navigateToRoute({ name: 'entity', entityName: item.name })
  }

  function handleQuestionSelect(nextQuestion: string) {
    setQuestion(nextQuestion)
  }

  function scrollToPageTop() {
    requestAnimationFrame(() => {
      window.scrollTo({ top: 0, behavior: 'smooth' })
    })
  }

  function navigateToRoute(nextRoute: AppRoute, preserveResult = false) {
    const nextPath = nextRoute.name === 'entity' ? buildEntityPath(nextRoute.entityName) : '/'
    window.history.pushState({}, '', nextPath)
    if (!preserveResult && nextRoute.name === 'entity') {
      setResult(null)
      scrollToPageTop()
    }
    setRoute(nextRoute)
  }

  function handleAnimalFocusToggle() {
    const next = !animalFocus
    setAnimalFocus(next)
    setQuestion((current) => {
      if (next && (!current.trim() || COMMON_QUESTIONS.includes(current))) {
        return ANIMAL_FOCUS_QUESTIONS[0]
      }
      if (!next && ANIMAL_FOCUS_QUESTIONS.includes(current)) {
        return COMMON_QUESTIONS[0]
      }
      return current
    })
  }

  function handleEntityPick(item: EntityListItem) {
    setEntityName(item.entity_name)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!entityName.trim()) {
      setError('請輸入搜尋內容')
      return
    }
    setLoading(true)
    setError(null)

    const effectiveQuestion = question.trim() || (animalFocus
      ? '是否可能涉及動保法、虐待、超收或飼養環境問題？'
      : '近期整體公開評價與相關爭議？')

    try {
      const response = await fetch(`${API_BASE_URL}/api/search`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          entity_name: entityName.trim(),
          question: effectiveQuestion,
          animal_focus: animalFocus,
        }),
      })

      if (!response.ok) {
        throw new Error('搜尋失敗，請確認後端服務是否已啟動。')
      }

      const data: SearchResponse = await response.json()
      setResult(data)
      await loadEntityDatabasePreview(entityName, animalFocus)
      await loadEntityProfile(entityName)
      setActiveFilter('全部')
      setActivePlatform('全部來源')

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
        const items = data.items ?? []
        setMediaFiles(items)
        return items
      }
    } catch { /* ignore */ }
    setMediaFiles([])
    return [] as MediaFile[]
  }

  async function createEntityComment(targetEntity: string, commentText: string) {
    const response = await fetch(`${API_BASE_URL}/api/entities/${encodeURIComponent(targetEntity)}/comments`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ comment: commentText }),
    })

    if (!response.ok) {
      const payload = await response.json().catch(() => null)
      throw new Error(payload?.detail ?? '評論送出失敗，請稍後再試。')
    }

    return response.json() as Promise<EntityComment>
  }

  async function handleCommentSubmit() {
    const targetEntity = (entityPageData?.entity_name ?? entityName).trim()
    const commentText = uploadComment.trim()
    if (!targetEntity) {
      setCommentError('找不到對應的實體名稱。')
      return
    }
    if (!commentText) {
      setCommentError('請先輸入評論內容。')
      return
    }

    setCommentSubmitting(true)
    setCommentError(null)
    try {
      await createEntityComment(targetEntity, commentText)
      await loadEntityPage(targetEntity)
      setUploadComment('')
    } catch (err) {
      setCommentError(err instanceof Error ? err.message : '評論送出失敗，請稍後再試。')
    } finally {
      setCommentSubmitting(false)
    }
  }

  async function uploadSingleFile(file: File, idx: number, targetEntity: string) {
    setUploadQueue((prev) => prev.map((item, i) => i === idx ? { ...item, status: 'uploading' as const, progress: 0 } : item))

    const formData = new FormData()
    formData.append('file', file)
    formData.append('entity_name', targetEntity)

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
    const targetEntity = (entityPageData?.entity_name ?? entityName).trim()
    const commentText = uploadComment.trim()
    if (!targetEntity) {
      setCommentError('找不到對應的實體名稱。')
      return
    }

    setCommentError(null)

    if (commentText) {
      try {
        setCommentSubmitting(true)
        await createEntityComment(targetEntity, commentText)
      } catch (err) {
        setCommentSubmitting(false)
        setCommentError(err instanceof Error ? err.message : '評論送出失敗，請稍後再試。')
        return
      }
      setCommentSubmitting(false)
    }

    const newItems = fileArray.map((f) => ({ file: f, progress: 0, status: 'pending' as const }))
    setUploadQueue((prev) => [...prev, ...newItems])

    const startIdx = uploadQueue.length
    for (let i = 0; i < fileArray.length; i++) {
      await uploadSingleFile(fileArray[i], startIdx + i, targetEntity)
    }

    await Promise.all([loadMediaFiles(targetEntity), loadEntityPage(targetEntity)])
    if (commentText) {
      setUploadComment('')
    }
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
          <div className="header-actions">
            <span className="mode-badge">{getModeLabel(result?.mode ?? null)}</span>
            <span className={`mode-badge mode-badge-secondary${(result?.animal_focus ?? animalFocus) ? ' active' : ''}`}>
              {getSearchModeLabel(result, animalFocus)}
            </span>
          </div>
        </div>
      </header>

      {!isEntityRoute ? (
        <>
          {/* ── Hero Search ── */}
          <section className="hero" id="search">
            <div className="hero-inner">
              <p className="hero-badge">第三方公開資料搜尋平台</p>
              <h1 className="hero-title">搜尋動保園區，快速看全網證據</h1>
              <p className="hero-subtitle">
                整理官方、新聞、社群、論壇、Google 與募資相關公開資料，幫你快速掌握評價與背景。
              </p>

              <form className="search-form" onSubmit={handleSubmit}>
                <div className="focus-toggle-row">
                  <button
                    type="button"
                    className={`focus-toggle${animalFocus ? ' active' : ''}`}
                    aria-pressed={animalFocus}
                    onClick={handleAnimalFocusToggle}
                  >
                    動保法模式
                  </button>
                  <p className="focus-mode-note">
                    {animalFocus
                      ? '只顯示與動物福利、照護、疑似違規或動保法相關的內容'
                      : '一般模式會保留較廣泛的評價、聲明、新聞與社群資訊'}
                  </p>
                </div>

                <div className="search-row search-row-single">
                  <div className="search-field search-field-grow" style={{ position: 'relative' }}>
                    <input
                      id="entity-input"
                      value={entityName}
                      onChange={(event) => {
                        const nextValue = event.target.value
                        handleSuggestInput(nextValue)
                        void loadEntityOptions(nextValue)
                      }}
                      onFocus={() => {
                        void loadEntityOptions(entityName)
                        if (entityName.trim()) handleSuggestInput(entityName)
                      }}
                      onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
                      placeholder="搜尋動保園區或協會，例如：董旺旺狗園、壽山動物園"
                      autoComplete="off"
                    />
                    {showSuggestions && suggestions.length > 0 ? (
                      <div className="suggest-dropdown">
                        {suggestions.map((item) => (
                          <button
                            key={item.name}
                            type="button"
                            className="suggest-item"
                            onMouseDown={() => handleSuggestPick(item)}
                          >
                            <span className="suggest-name">{item.name}</span>
                            {item.aliases.length > 0 ? <span className="suggest-alias">({item.aliases.join(', ')})</span> : null}
                            {item.review_count > 0 ? <span className="suggest-count">{item.review_count} 則評論</span> : null}
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </div>
                  <button type="submit" className="search-btn" disabled={loading}>
                    {loading ? '搜尋中…' : '搜尋'}
                  </button>
                </div>

                {error ? <p className="error-msg">{error}</p> : null}

                {loading ? (
                  <div className="search-loading-panel" aria-live="polite">
                    <div className="loading-pulse-row">
                      {searchProgressSteps.map((step, index) => (
                        <span
                          key={step}
                          className={`loading-dot${index === searchStepIndex ? ' active' : ''}${index < searchStepIndex ? ' done' : ''}`}
                        />
                      ))}
                    </div>
                    <p className="loading-title">搜尋中，正在整理可用證據</p>
                    <p className="loading-detail">{searchProgressSteps[searchStepIndex]}</p>
                  </div>
                ) : null}

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
        </>
      ) : null}

      {result ? (
        <section className="result-page" ref={resultSectionRef}>
          {/* ── Entity Header ── */}
          <div className="result-container">
            <div className="entity-header-card">
              <div className="entity-header-top">
                <div className="entity-header-info">
                  <a href="#search" className="back-link">← 返回搜尋</a>
                  <h2 className="entity-name">
                    <a
                      href={buildEntityPath(profile?.entity_name ?? entityName)}
                      className="entity-name-link"
                      target="_blank"
                      rel="noreferrer"
                    >
                      {profile?.entity_name ?? entityName}
                    </a>
                  </h2>
                  {profile?.aliases.length ? (
                    <p className="entity-aliases">別名：{profile.aliases.join('、')}</p>
                  ) : null}
                  <p className={`entity-mode-note${result.animal_focus ? ' active' : ''}`}>
                    {result.animal_focus
                      ? '動保法模式已啟用：摘要只聚焦動物福利、照護、收容、繁殖、救援與相關法規風險。'
                      : '一般模式：保留較廣泛的公開評價、聲明、新聞與社群資訊。'}
                  </p>
                  <p className="entity-question">🔍 {question}</p>
                </div>
                <div className="score-box">
                  <div className="score-number">{toFivePointScore(overallScore)}</div>
                  <div className="score-label">{getOverallLabel(overallScore)}</div>
                  <div className="score-count">保留 {result.evidence_cards.length} 則證據</div>
                </div>
              </div>

              <p className="entity-intro">{getIntroParagraph(result)}</p>

              <div className="entity-tags">
                <span className={`entity-tag ${result.animal_focus ? 'tag-animal-mode' : 'tag-general-mode'}`}>
                  {result.search_mode === 'animal_law' ? '動保法模式' : '一般模式'}
                </span>
                <span className="entity-tag">{getReviewTone(result.evidence_cards)}</span>
                <span className="entity-tag">{getEvidenceCount(result.evidence_cards)} 則整合證據</span>
                <span className="entity-tag">原始抓到 {result.diagnostics.raw_merged_results}</span>
                <span className="entity-tag">過濾後保留 {result.evidence_cards.length}</span>
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
                <p className="metric-explainer">
                  {metricBars.map((item) => `${item.label}：${getMetricDescription(item.label, item.value)}`).join(' ')}
                </p>
              </div>

              <div className="summary-card">
                <h3>⚠️ 主要疑慮</h3>
                <p className="summary-caption">優先列出高相關、非單純轉述的來源；如果證據太弱，這裡會保守顯示。</p>
                <ul className="point-list">
                  {result.summary.supporting_points.slice(0, 3).map((item) => (
                    <li key={item} className="point-item concern">{item}</li>
                  ))}
                </ul>
              </div>

              <div className="summary-card">
                <h3>✅ 正面資訊</h3>
                <p className="summary-caption">包含改善措施、官方回應與較可交叉對照的正面資訊。</p>
                <ul className="point-list">
                  {result.summary.opposing_points.slice(0, 3).map((item) => (
                    <li key={item} className="point-item positive">{item}</li>
                  ))}
                </ul>
              </div>

              <div className="summary-card">
                <h3>❓ 待查證</h3>
                <p className="summary-caption">這些多半屬於訪談引述、片段敘述或證據不足，適合人工複核。</p>
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
                <span className="stat-label">歷史累積來源</span>
              </div>
              <div className="stat-card">
                <span className="stat-value">{result.diagnostics.raw_merged_results}</span>
                <span className="stat-label">本次原始抓取</span>
              </div>
              <div className="stat-card">
                <span className="stat-value">{result.evidence_cards.length}</span>
                <span className="stat-label">本次保留證據</span>
              </div>
            </div>

            {/* ── Evidence Section ── */}
            <div className="reviews-section">
              <div className="reviews-header">
                <h3>📝 證據列表（{result.evidence_cards.length}）</h3>
                <p className="reviews-hint">
                  ⓘ 本次共展開 {result.diagnostics.query_count} 個查詢，原始抓到 {result.diagnostics.raw_merged_results} 筆，
                  去重後 {result.diagnostics.deduplicated_results} 筆，低品質/不相關過濾掉 {result.diagnostics.low_signal_filtered + result.diagnostics.relevance_filtered}
                  筆，最後留下 {result.evidence_cards.length} 則可摘要證據。
                </p>
                <p className="reviews-hint">
                  Firecrawl {result.diagnostics.providers.firecrawl_results}、SerpAPI {result.diagnostics.providers.serpapi_results}、
                  平台來源 {result.diagnostics.providers.platform_results}、歷史快取 {result.diagnostics.providers.cached_results}
                  。SerpAPI 會抓比較廣，所以也比較容易混入分類頁、導覽頁或弱相關結果，後面仍會被過濾。
                </p>
                {result.diagnostics.analysis ? (
                  <p className="reviews-hint">
                    分析階段另外排除了 {result.diagnostics.analysis.noise_filtered + result.diagnostics.analysis.low_relevance_filtered}
                    筆低訊號卡片，AI 灰頁判斷再剔除 {result.diagnostics.analysis.ai_gray_filtered} 筆。
                  </p>
                ) : null}
              </div>

              <div className="platform-tabs">
                <button
                  type="button"
                  className={`ptab${activePlatform === '全部來源' ? ' active' : ''}`}
                  onClick={() => setActivePlatform('全部來源')}
                >
                  全部來源 ({result.evidence_cards.length})
                </button>
                {PLATFORM_LABELS.map((label) => {
                  const count = countPlatformCards(result.evidence_cards, label)
                  if (count === 0) return null
                  return (
                    <button
                      key={label}
                      type="button"
                      className={`ptab${activePlatform === label ? ' active' : ''}`}
                      onClick={() => setActivePlatform(label)}
                    >
                      {label} ({count})
                    </button>
                  )
                })}
              </div>

              <div className="filter-bar">
                {evidenceFilters.map((filter) => (
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
                {visibleCards.length === 0 ? (
                  <div className="empty-review-state">
                    目前這個篩選條件下沒有可顯示的來源，建議切回「全部」或改看其他平台。
                  </div>
                ) : visibleCards.map((card) => (
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
                    {card.ai_summary ? <p className="review-summary">AI 摘要：{card.ai_summary}</p> : null}
                    <div className="review-excerpt-block">
                      <span className="review-excerpt-label">證據摘錄</span>
                      <p className="review-snippet">{getCardExcerpt(card)}</p>
                    </div>

                    <div className="review-tags">
                      <span className="platform-tag">{getPlatformLabel(card)}</span>
                      <span className={`origin-tag ${getEvidenceOriginClassName(card)}`}>{getEvidenceOriginLabel(card)}</span>
                      <span>{getClaimTypeLabel(card.claim_type)}</span>
                      <span>強度：{getStrengthLabel(card.evidence_strength)}</span>
                      <span>第一手 {card.first_hand_score}</span>
                      <span>相關性 {card.relevance_score}</span>
                      <span>{getRecencyLabel(card.recency_label)}</span>
                    </div>

                    {card.notes ? <p className="review-note">{card.notes}</p> : null}

                    <div className="review-footer">
                      <span className="review-url">{new URL(card.url).hostname}</span>
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
                <h3>📝 留下評論並上傳附件</h3>
                <p className="media-hint">先寫下你觀察到的內容，再附上照片或影片。支援 JPG、PNG、WebP、GIF、HEIC、MP4、MOV、WebM（單檔最大 200MB）</p>
              </div>

              <div className="upload-caption-row">
                <label className="upload-form-label" htmlFor="upload-comment-input">
                  評論內容
                </label>
                <textarea
                  id="upload-comment-input"
                  className="caption-input comment-input"
                  value={uploadComment}
                  onChange={(e) => setUploadComment(e.target.value)}
                  placeholder="例如：今天看到欄舍潮濕、有異味，動物活動空間偏小。也可以補充時間、地點與觀察到的情況。"
                />
                <p className="upload-form-hint">可先填評論，再拖拉照片／影片上傳；評論會一起附在這批檔案上。</p>
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
                  <p className="dropzone-sub">可一次選取多個檔案，並把上方評論一起附上</p>
                </div>
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
                          <span className="gallery-meta">{formatFileSize(mf.file_size)}</span>
                          {mf.caption ? <p className="gallery-comment">{mf.caption}</p> : null}
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
      ) : isEntityRoute ? (
        <section className="result-page" ref={resultSectionRef}>
          <div className="result-container">
            <div className="entity-header-card entity-page-card">
              <div className="entity-header-top">
                <div className="entity-header-info">
                  <button type="button" className="back-link back-link-button" onClick={() => navigateToRoute({ name: 'home' }, true)}>
                    ← 返回搜尋首頁
                  </button>
                  <p className="entity-page-kicker">Entity Page</p>
                  <h2 className="entity-name">{selectedEntityLabel}</h2>
                  {(entityPageData?.aliases.length ?? profile?.aliases.length ?? 0) > 0 ? (
                    <p className="entity-aliases">別名：{(entityPageData?.aliases ?? profile?.aliases ?? []).join('、')}</p>
                  ) : null}
                  {entityPageData?.headline ? <p className="entity-page-headline">{entityPageData.headline}</p> : null}
                  <p className={`entity-mode-note${animalFocus ? ' active' : ''}`}>
                    {animalFocus
                      ? '目前正在看動保法模式的摘要與待查問題。'
                      : '目前正在看一般模式的整理摘要，可切換成動保法模式查看更聚焦的內容。'}
                  </p>
                </div>
                <div className="score-box">
                  <div className="score-number">{toFivePointScore(entityPageScore)}</div>
                  <div className="score-label">{entitySnapshot ? '資料庫摘要' : '尚待建立'}</div>
                  <div className="score-count">{entitySnapshot ? `${entitySnapshot.source_count} 則整理證據` : '先建立第一筆摘要'}</div>
                </div>
              </div>

              <div className="entity-page-hero">
                <div className="entity-page-copy">
                  <p className="entity-intro">
                    {entityPageData?.introduction
                      ? entityPageData.introduction
                      : entitySnapshot
                        ? entitySnapshot.summary.verdict
                        : '目前這個實體還沒有資料庫摘要，你可以直接用上方搜尋建立第一筆整理結果。'}
                  </p>
                  {entityPageData?.location ? <p className="entity-page-location">📍 {entityPageData.location}</p> : null}
                </div>
                {entityPageData?.cover_image_url && !hiddenBrokenImages[entityPageData.cover_image_url] ? (
                  <img
                    src={entityPageData.cover_image_url}
                    alt={entityPageData.cover_image_alt || `${selectedEntityLabel} 介紹圖片`}
                    className="entity-page-cover"
                    loading="lazy"
                    referrerPolicy="no-referrer"
                    onError={() => {
                      setHiddenBrokenImages((prev) => ({ ...prev, [entityPageData.cover_image_url]: true }))
                    }}
                  />
                ) : null}
              </div>

              <div className="entity-tags">
                <span className={`entity-tag ${animalFocus ? 'tag-animal-mode' : 'tag-general-mode'}`}>
                  {animalFocus ? '動保法模式' : '一般模式'}
                </span>
                {entitySnapshot ? <span className="entity-tag">{entitySnapshot.source_count} 則已整理證據</span> : null}
                {profile ? <span className="entity-tag">累積查詢 {profile.total_queries}</span> : null}
                {entityPageData ? <span className="entity-tag">累積評論 {entityPageData.total_comments}</span> : null}
                {entityPageSourceSummary.map((item) => (
                  <span key={item.type} className={`entity-tag tag-${item.type}`}>
                    {item.label} {item.count}
                  </span>
                ))}
              </div>

              <div className="entity-page-actions">
                <button
                  type="button"
                  className="search-btn"
                  onClick={() => {
                    navigateToRoute({ name: 'home' }, true)
                    requestAnimationFrame(() => {
                      document.getElementById('search')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                    })
                  }}
                >
                  用這個實體開始搜尋
                </button>
              </div>
            </div>

            {entityPageLoading ? (
              <div className="empty-card entity-page-empty">
                <div className="empty-icon">🧭</div>
                <h2>正在載入實體頁資料</h2>
                <p>正在整理介紹、圖片、評論、媒體檔案與歷史查詢紀錄。</p>
              </div>
            ) : null}

            {!entityPageLoading && entityPageData?.gallery.length ? (
              <div className="summary-card entity-gallery-section">
                <div className="reviews-header">
                  <h3>🖼️ 實體介紹圖片</h3>
                  <p className="reviews-hint">這裡會先顯示資料庫內建的介紹圖片，之後也可以持續搭配下方附件一起觀察。</p>
                </div>
                <div className="entity-gallery-grid">
                  {entityPageData.gallery.filter((item) => !hiddenBrokenImages[item.url]).map((item) => (
                    <figure key={`${item.url}-${item.caption}`} className="entity-gallery-card">
                      <img
                        src={item.url}
                        alt={item.alt_text || `${selectedEntityLabel} 圖片`}
                        className="entity-gallery-image"
                        loading="lazy"
                        referrerPolicy="no-referrer"
                        onError={() => {
                          setHiddenBrokenImages((prev) => ({ ...prev, [item.url]: true }))
                        }}
                      />
                      {item.caption || item.source_page_url ? (
                        <figcaption className="entity-gallery-caption">
                          {item.caption ? <span>{item.caption}</span> : null}
                          {item.source_page_url ? (
                            <a
                              href={item.source_page_url}
                              target="_blank"
                              rel="noreferrer"
                              className="entity-gallery-source-link"
                            >
                              查看來源頁 ↗
                            </a>
                          ) : null}
                        </figcaption>
                      ) : null}
                    </figure>
                  ))}
                </div>
              </div>
            ) : null}

            {!entityPageLoading && entitySnapshot ? (
              <>
                <div className="summary-grid">
                  <div className="summary-card">
                    <h3>📌 資料庫摘要</h3>
                    <p className="summary-caption">最近更新：{formatDateTimeLabel(entitySnapshot.generated_at)}</p>
                    <p className="entity-overview-hint">{entitySnapshot.summary.verdict}</p>
                  </div>
                  <div className="summary-card">
                    <h3>⚠️ 主要疑慮</h3>
                    <ul className="point-list">
                      {entitySnapshot.summary.supporting_points.slice(0, 3).map((item) => (
                        <li key={item} className="point-item concern">{item}</li>
                      ))}
                    </ul>
                  </div>
                  <div className="summary-card">
                    <h3>✅ 正面資訊</h3>
                    <ul className="point-list">
                      {entitySnapshot.summary.opposing_points.slice(0, 3).map((item) => (
                        <li key={item} className="point-item positive">{item}</li>
                      ))}
                    </ul>
                  </div>
                  <div className="summary-card">
                    <h3>❓ 待查證</h3>
                    <ul className="point-list">
                      {entitySnapshot.summary.uncertain_points.slice(0, 3).map((item) => (
                        <li key={item} className="point-item uncertain">{item}</li>
                      ))}
                    </ul>
                  </div>
                </div>

                {entityQuestions.length > 0 ? (
                  <div className="summary-card entity-question-section">
                    <h3>🧠 建議追問</h3>
                    <p className="summary-caption">點一下就會帶回搜尋區，直接用這個實體開始查。</p>
                    <div className="entity-question-grid">
                      {entityQuestions.slice(0, 8).map((item) => (
                        <button
                          key={`${item.category}-${item.question_text}`}
                          type="button"
                          className="entity-question-card"
                          onClick={() => {
                            setQuestion(item.question_text)
                            navigateToRoute({ name: 'home' }, true)
                            requestAnimationFrame(() => {
                              document.getElementById('search')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                            })
                          }}
                        >
                          <span className="entity-question-category">{item.category}</span>
                          <strong>{item.question_text}</strong>
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="reviews-section">
                  <div className="reviews-header">
                    <h3>📝 已整理證據（{entitySnapshot.evidence_cards.length}）</h3>
                    <p className="reviews-hint">以下優先顯示資料庫已整理好的證據卡，可直接當成這個實體頁的快速入口。</p>
                  </div>
                  <div className="platform-tabs">
                    <button
                      type="button"
                      className={`ptab${activePlatform === '全部來源' ? ' active' : ''}`}
                      onClick={() => setActivePlatform('全部來源')}
                    >
                      全部來源 ({entitySnapshot.evidence_cards.length})
                    </button>
                    {PLATFORM_LABELS.map((label) => {
                      const count = countPlatformCards(entitySnapshot.evidence_cards, label)
                      if (count === 0) return null
                      return (
                        <button
                          key={label}
                          type="button"
                          className={`ptab${activePlatform === label ? ' active' : ''}`}
                          onClick={() => setActivePlatform(label)}
                        >
                          {label} ({count})
                        </button>
                      )
                    })}
                  </div>
                  <div className="filter-bar">
                    {evidenceFilters.map((filter) => (
                      <button
                        key={filter}
                        type="button"
                        className={`filter-chip${activeFilter === filter ? ' active' : ''}`}
                        onClick={() => setActiveFilter(filter)}
                      >
                        {filter} ({getFilterCount(filter, entityPagePlatformCards)})
                      </button>
                    ))}
                  </div>
                  <div className="review-list">
                    {entityPageVisibleCards.length === 0 ? (
                      <div className="empty-review-state">目前這個篩選條件下沒有可顯示的資料庫證據卡。</div>
                    ) : entityPageVisibleCards.map((card) => (
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
                          </div>
                        </div>
                        <h4 className="review-title">{card.title}</h4>
                        <p className="review-snippet">{getCardExcerpt(card)}</p>
                        <div className="review-footer">
                          <span className="review-url">{new URL(card.url).hostname}</span>
                          <a href={card.url} target="_blank" rel="noreferrer" className="view-original">
                            查看原文 →
                          </a>
                        </div>
                      </article>
                    ))}
                  </div>
                </div>
              </>
            ) : null}

            {!entityPageLoading && entityPageError ? (
              <div className="empty-card entity-page-empty">
                <div className="empty-icon">📭</div>
                <h2>這個實體頁還沒有完整資料</h2>
                <p>{entityPageError}</p>
              </div>
            ) : null}

            {/* Crawled platform reviews */}
            <div className="reviews-section crawled-reviews-section">
              <div className="reviews-header">
                <h3>各平台評論（{Object.values(reviewStats).reduce((a, b) => a + b, 0)}）</h3>
              </div>
              <div className="review-platform-tabs">
                {[
                  { key: 'all', label: '全部', count: Object.values(reviewStats).reduce((a, b) => a + b, 0) },
                  { key: 'ptt', label: 'PTT', count: reviewStats['ptt'] || 0 },
                  { key: 'google_maps', label: 'Google Maps', count: reviewStats['google_maps'] || 0 },
                  { key: 'news', label: '新聞', count: reviewStats['news'] || 0 },
                  { key: 'threads', label: 'Threads', count: reviewStats['threads'] || 0 },
                  { key: 'instagram_posts', label: 'IG 貼文', count: reviewStats['instagram_posts'] || 0 },
                  { key: 'instagram_comments', label: 'IG 留言', count: reviewStats['instagram_comments'] || 0 },
                  { key: 'facebook_posts', label: 'FB 貼文', count: reviewStats['facebook_posts'] || 0 },
                  { key: 'facebook_comments', label: 'FB 留言', count: reviewStats['facebook_comments'] || 0 },
                ].filter(t => t.key === 'all' || t.count > 0).map(tab => (
                  <button
                    key={tab.key}
                    className={`review-platform-tab${reviewPlatformTab === tab.key ? ' active' : ''}`}
                    onClick={() => handleReviewPlatformTab(tab.key)}
                  >
                    {tab.label} ({tab.count})
                  </button>
                ))}
              </div>
              {reviewsLoading ? (
                <div className="reviews-loading">載入評論中...</div>
              ) : crawledReviews.length > 0 ? (
                <div className="crawled-review-list">
                  {crawledReviews.map((review) => (
                    <article key={review.id} className="crawled-review-card">
                      <div className="crawled-review-meta">
                        {review.sentiment ? (
                          <span className={`review-sentiment sentiment-${review.sentiment === '推' ? 'positive' : review.sentiment === '噓' ? 'negative' : 'neutral'}`}>
                            {review.sentiment}
                          </span>
                        ) : review.rating ? (
                          <span className="review-rating">{'★'.repeat(review.rating)}{'☆'.repeat(5 - review.rating)}</span>
                        ) : null}
                        {review.author ? <span className="review-author">{review.author}</span> : null}
                        <span className="review-platform-badge">{review.platform}</span>
                        {review.published_at ? <span className="review-date">{review.published_at.slice(0, 10)}</span> : null}
                      </div>
                      <p className="crawled-review-content">{review.content}</p>
                      {review.parent_title ? (
                        <div className="crawled-review-source">
                          {review.source_url ? (
                            <a href={review.source_url} target="_blank" rel="noopener noreferrer">{review.parent_title}</a>
                          ) : (
                            <span>{review.parent_title}</span>
                          )}
                        </div>
                      ) : null}
                    </article>
                  ))}
                </div>
              ) : (
                <div className="empty-review-state">尚未爬取到此對象的評論。可以透過 pipeline 排程爬取。</div>
              )}
            </div>

            <div className="reviews-section comment-section">
              <div className="reviews-header">
                <h3>使用者評論（{entityPageData?.total_comments ?? 0}）</h3>
                <p className="reviews-hint">這裡會持續累積針對這個實體的觀察評論，可單獨送出，也可搭配下方附件一起補充。</p>
              </div>
              {entityPageData?.comments.length ? (
                <div className="entity-comment-list">
                  {entityPageData.comments.map((item) => (
                    <article key={item.id} className="entity-comment-card">
                      <div className="entity-comment-top">
                        <strong>{item.entity_name}</strong>
                        <span>{formatDateTimeLabel(item.created_at)}</span>
                      </div>
                      <p className="entity-comment-body">{item.comment}</p>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="empty-review-state">目前還沒有評論，歡迎成為第一位留下觀察的人。</div>
              )}
            </div>

            <div className="media-section">
              <div className="media-header">
                <h3>📝 留下評論並上傳附件</h3>
                <p className="media-hint">先寫下你觀察到的內容，再選擇單獨送出評論，或附上照片/影片。支援 JPG、PNG、WebP、GIF、HEIC、MP4、MOV、WebM（單檔最大 200MB）</p>
              </div>

              <div className="upload-caption-row">
                <label className="upload-form-label" htmlFor="upload-comment-input">
                  評論內容
                </label>
                <textarea
                  id="upload-comment-input"
                  className="caption-input comment-input"
                  value={uploadComment}
                  onChange={(e) => setUploadComment(e.target.value)}
                  placeholder="例如：今天看到欄舍潮濕、有異味，動物活動空間偏小。也可以補充時間、地點與觀察到的情況。"
                />
                <div className="comment-action-row">
                  <button
                    type="button"
                    className="search-btn comment-submit-btn"
                    onClick={() => void handleCommentSubmit()}
                    disabled={commentSubmitting}
                  >
                    {commentSubmitting ? '送出中…' : '先送出評論'}
                  </button>
                  <p className="upload-form-hint">你也可以不傳檔案，先單獨送出評論；若接著上傳附件，會自動沿用這段評論一起存進實體頁。</p>
                </div>
                {commentError ? <p className="comment-error-text">{commentError}</p> : null}
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
                  <p className="dropzone-sub">可一次選取多個檔案；若上方已有評論，會先新增到此實體的累積評論區</p>
                </div>
              </div>

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
                          <span className="gallery-meta">{formatFileSize(mf.file_size)}</span>
                          {mf.caption ? <p className="gallery-comment">{mf.caption}</p> : null}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {mediaFiles.length === 0 && uploadQueue.length === 0 ? (
                <button
                  type="button"
                  className="load-media-btn"
                  onClick={() => void loadMediaFiles(selectedEntityLabel)}
                >
                  載入已上傳的檔案
                </button>
              ) : null}
            </div>

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
            <p>搜尋後將顯示全網公開資料摘要、AI 分析重點，以及完整證據列表。</p>
          </div>
        </section>
      )}

      {/* ── Footer ── */}
      <footer className="footer">
        <div className="footer-inner">
          <span>© 2026 動保評價 — 動物福利公開資料搜尋平台</span>
          <span>資料來源：Google、Facebook、PTT、Dcard、新聞、官方網站與其他公開平台</span>
        </div>
      </footer>
    </div>
  )
}

export default App
