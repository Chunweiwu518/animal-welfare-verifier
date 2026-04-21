import { useEffect, useRef, useState } from 'react'

const DEFAULT_API_BASE_URL =
  typeof window === 'undefined' ? 'http://localhost:5173' : ''
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL

const MAX_ATTACHMENTS = 3

interface Attachment {
  url: string
  media_type: 'image' | 'video'
}

interface ReviewComment {
  id: number
  comment: string
  display_name: string
  avatar_url: string | null
  created_at: string
  user_id: number | null
  attachments: Attachment[]
}

interface ReviewCommentThreadProps {
  reviewId: number
  isLoggedIn: boolean
  currentUserId?: number | null
  onRequireLogin: () => void
}

export function ReviewCommentThread({
  reviewId,
  isLoggedIn,
  currentUserId,
  onRequireLogin,
}: ReviewCommentThreadProps) {
  const [comments, setComments] = useState<ReviewComment[]>([])
  const [expanded, setExpanded] = useState(false)
  const [draft, setDraft] = useState('')
  const [pendingAttachments, setPendingAttachments] = useState<Attachment[]>([])
  const [uploading, setUploading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [anonymous, setAnonymous] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  async function load() {
    try {
      const res = await fetch(`${API_BASE_URL}/api/reviews/${reviewId}/comments`, {
        credentials: 'include',
      })
      if (res.ok) {
        const items = (await res.json()) as ReviewComment[]
        const normalized = items.map((c) => ({ ...c, attachments: c.attachments ?? [] }))
        setComments(normalized)
        // Auto-expand when there are existing comments so users immediately see discussion.
        if (normalized.length > 0) {
          setExpanded(true)
        }
      }
      setLoaded(true)
    } catch {
      setLoaded(true)
    }
  }

  // Fetch on mount so the toggle badge shows the accurate count even when collapsed.
  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reviewId])

  async function handleFileSelect(files: FileList | null) {
    if (!files || files.length === 0) return
    if (!isLoggedIn) {
      onRequireLogin()
      return
    }
    if (pendingAttachments.length >= MAX_ATTACHMENTS) {
      setError(`最多只能附 ${MAX_ATTACHMENTS} 個檔案`)
      return
    }
    setError(null)
    setUploading(true)
    try {
      const remaining = MAX_ATTACHMENTS - pendingAttachments.length
      const selected = Array.from(files).slice(0, remaining)
      const uploaded: Attachment[] = []
      for (const file of selected) {
        const form = new FormData()
        form.append('file', file)
        const res = await fetch(`${API_BASE_URL}/api/review-attachments/upload`, {
          method: 'POST',
          credentials: 'include',
          body: form,
        })
        if (res.status === 401) {
          onRequireLogin()
          return
        }
        if (!res.ok) {
          const payload = await res.json().catch(() => null)
          throw new Error(payload?.detail ?? `上傳失敗 (${res.status})`)
        }
        const data = (await res.json()) as Attachment
        uploaded.push(data)
      }
      setPendingAttachments((prev) => [...prev, ...uploaded])
    } catch (err) {
      setError(err instanceof Error ? err.message : '上傳失敗')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  function removeAttachment(url: string) {
    setPendingAttachments((prev) => prev.filter((a) => a.url !== url))
  }

  async function handleSubmit() {
    if (!isLoggedIn) {
      onRequireLogin()
      return
    }
    const text = draft.trim()
    if (!text && pendingAttachments.length === 0) return
    setSubmitting(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE_URL}/api/reviews/${reviewId}/comments`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          comment: text || '(附件)',
          attachments: pendingAttachments,
          anonymous,
        }),
      })
      if (res.status === 401) {
        onRequireLogin()
        return
      }
      if (!res.ok) {
        throw new Error(`${res.status}`)
      }
      const created = (await res.json()) as ReviewComment
      setComments((prev) => [...prev, { ...created, attachments: created.attachments ?? [] }])
      setDraft('')
      setPendingAttachments([])
    } catch (err) {
      setError(err instanceof Error ? err.message : '送出失敗')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDelete(commentId: number) {
    try {
      const res = await fetch(
        `${API_BASE_URL}/api/reviews/${reviewId}/comments/${commentId}`,
        { method: 'DELETE', credentials: 'include' },
      )
      if (res.ok) {
        setComments((prev) => prev.filter((c) => c.id !== commentId))
      }
    } catch {
      /* ignore */
    }
  }

  const count = comments.length

  return (
    <div className="review-thread">
      <button
        type="button"
        className="review-thread-toggle"
        onClick={() => setExpanded((v) => !v)}
      >
        💬 {expanded ? '收起' : count > 0 ? `${count} 則留言` : '留言'}
      </button>
      {expanded ? (
        <div className="review-thread-body">
          {!loaded ? (
            <p className="review-thread-empty">載入中…</p>
          ) : comments.length === 0 ? (
            <p className="review-thread-empty">還沒有人對這則評論補充。</p>
          ) : (
            <ul className="review-thread-list">
              {comments.map((c) => (
                <li key={c.id} className="review-thread-item">
                  <div className="review-thread-head">
                    {c.avatar_url ? (
                      <img
                        src={c.avatar_url}
                        alt=""
                        className="review-thread-avatar"
                        referrerPolicy="no-referrer"
                        onError={(e) => {
                          e.currentTarget.style.display = 'none'
                        }}
                      />
                    ) : (
                      <span className="review-thread-avatar-fallback">
                        {c.display_name?.slice(0, 1) ?? '?'}
                      </span>
                    )}
                    <strong className="review-thread-name">
                      {c.display_name || '匿名用戶'}
                    </strong>
                    <span className="review-thread-date">
                      {c.created_at?.slice(0, 10)}
                    </span>
                    {currentUserId && c.user_id === currentUserId ? (
                      <button
                        type="button"
                        className="review-thread-delete"
                        onClick={() => handleDelete(c.id)}
                        title="刪除我的留言"
                      >
                        ✕
                      </button>
                    ) : null}
                  </div>
                  <p className="review-thread-text">{c.comment}</p>
                  {c.attachments.length > 0 ? (
                    <div className="review-thread-attachments">
                      {c.attachments.map((a) =>
                        a.media_type === 'image' ? (
                          <a
                            key={a.url}
                            href={`${API_BASE_URL}${a.url}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            <img
                              src={`${API_BASE_URL}${a.url}`}
                              alt="附件"
                              className="review-thread-attachment-thumb"
                              loading="lazy"
                            />
                          </a>
                        ) : (
                          <video
                            key={a.url}
                            src={`${API_BASE_URL}${a.url}`}
                            controls
                            className="review-thread-attachment-video"
                          />
                        ),
                      )}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}

          <div className="review-thread-compose">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={
                isLoggedIn ? '寫下你對這則評論的補充或不同看法…(可 Ctrl+V 貼圖)' : '登入後才能留言'
              }
              disabled={!isLoggedIn || submitting}
              rows={2}
              maxLength={1000}
              onFocus={() => {
                if (!isLoggedIn) onRequireLogin()
              }}
              onPaste={(e) => {
                if (!isLoggedIn) return
                const files: File[] = []
                for (const item of Array.from(e.clipboardData.items)) {
                  if (item.kind === 'file') {
                    const f = item.getAsFile()
                    if (f) files.push(f)
                  }
                }
                if (files.length > 0) {
                  e.preventDefault()
                  const dt = new DataTransfer()
                  files.forEach((f) => dt.items.add(f))
                  void handleFileSelect(dt.files)
                }
              }}
            />

            {pendingAttachments.length > 0 ? (
              <div className="review-thread-preview">
                {pendingAttachments.map((a) => (
                  <div key={a.url} className="review-thread-preview-item">
                    {a.media_type === 'image' ? (
                      <img
                        src={`${API_BASE_URL}${a.url}`}
                        alt=""
                        className="review-thread-preview-thumb"
                      />
                    ) : (
                      <div className="review-thread-preview-video">🎬 影片</div>
                    )}
                    <button
                      type="button"
                      className="review-thread-preview-remove"
                      onClick={() => removeAttachment(a.url)}
                      title="移除"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            ) : null}

            {error ? <p className="review-thread-error">{error}</p> : null}

            <input
              ref={fileInputRef}
              type="file"
              accept="image/*,video/*"
              hidden
              multiple
              onChange={(e) => void handleFileSelect(e.target.files)}
            />

            <div className="review-thread-actions">
              <button
                type="button"
                className="review-thread-attach-btn"
                onClick={() => {
                  if (!isLoggedIn) {
                    onRequireLogin()
                    return
                  }
                  fileInputRef.current?.click()
                }}
                disabled={uploading || submitting || pendingAttachments.length >= MAX_ATTACHMENTS}
                title={`附加圖片或影片（${pendingAttachments.length}/${MAX_ATTACHMENTS}）`}
              >
                {uploading ? '上傳中…' : `📎 附件 ${pendingAttachments.length}/${MAX_ATTACHMENTS}`}
              </button>
              {isLoggedIn ? (
                <label
                  className="review-thread-anon"
                  title="勾選後你的名字會顯示為「匿名用戶」，但系統仍記錄你的身份以防濫用"
                >
                  <input
                    type="checkbox"
                    checked={anonymous}
                    onChange={(e) => setAnonymous(e.target.checked)}
                  />
                  匿名
                </label>
              ) : null}
              <span className="review-thread-hint">{draft.length}/1000</span>
              <button
                type="button"
                className="review-thread-submit"
                onClick={handleSubmit}
                disabled={
                  submitting || (!draft.trim() && pendingAttachments.length === 0)
                }
              >
                {submitting ? '送出中…' : isLoggedIn ? '送出' : '登入以留言'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
