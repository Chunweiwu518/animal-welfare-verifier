import { useEffect, useState } from 'react'
import { Modal } from './Modal'
import type { ShelterCandidate } from '../api/shelters'

interface VerificationReviewDialogProps {
  open: boolean
  candidate: ShelterCandidate | null
  submitting: boolean
  error: string | null
  onConfirm: (edited: ShelterCandidate) => void
  onCancel: () => void
}

export function VerificationReviewDialog({
  open,
  candidate,
  submitting,
  error,
  onConfirm,
  onCancel,
}: VerificationReviewDialogProps) {
  const [draft, setDraft] = useState<ShelterCandidate | null>(candidate)

  useEffect(() => {
    setDraft(candidate)
  }, [candidate])

  if (!draft) {
    return null
  }

  function update<K extends keyof ShelterCandidate>(field: K, value: ShelterCandidate[K]) {
    setDraft((prev) => (prev ? { ...prev, [field]: value } : prev))
  }

  const aliasesString = draft.aliases.join('、')

  return (
    <Modal open={open} onClose={onCancel} title="確認狗園資訊">
      <p className="modal-hint">
        AI 查證結果如下。確認無誤後會建立狗園並立刻背景爬取 8 個平台的評論。
      </p>

      <div className="modal-field">
        <label htmlFor="shelter-name">正式名稱</label>
        <input
          id="shelter-name"
          value={draft.canonical_name}
          onChange={(event) => update('canonical_name', event.target.value)}
          disabled={submitting}
        />
      </div>

      <div className="modal-field">
        <label htmlFor="shelter-type">類型</label>
        <input
          id="shelter-type"
          value={draft.entity_type}
          onChange={(event) => update('entity_type', event.target.value)}
          placeholder="例如：公立動物之家、私人狗園"
          disabled={submitting}
        />
      </div>

      <div className="modal-field">
        <label htmlFor="shelter-address">地址</label>
        <input
          id="shelter-address"
          value={draft.address}
          onChange={(event) => update('address', event.target.value)}
          disabled={submitting}
        />
      </div>

      <div className="modal-field">
        <label htmlFor="shelter-website">官網</label>
        <input
          id="shelter-website"
          value={draft.website}
          onChange={(event) => update('website', event.target.value)}
          disabled={submitting}
        />
      </div>

      <div className="modal-field">
        <label htmlFor="shelter-fb">Facebook 粉絲頁</label>
        <input
          id="shelter-fb"
          value={draft.facebook_url}
          onChange={(event) => update('facebook_url', event.target.value)}
          disabled={submitting}
        />
      </div>

      <div className="modal-field">
        <label htmlFor="shelter-aliases">別名（用「、」或逗號分隔）</label>
        <input
          id="shelter-aliases"
          value={aliasesString}
          onChange={(event) =>
            update(
              'aliases',
              event.target.value
                .split(/[、,，]/)
                .map((item) => item.trim())
                .filter(Boolean),
            )
          }
          disabled={submitting}
        />
      </div>

      <div className="modal-field">
        <label htmlFor="shelter-intro">一句話介紹</label>
        <textarea
          id="shelter-intro"
          value={draft.introduction}
          onChange={(event) => update('introduction', event.target.value)}
          disabled={submitting}
        />
      </div>

      <div className="modal-field">
        <label htmlFor="shelter-cover">封面圖片網址</label>
        <input
          id="shelter-cover"
          value={draft.cover_image_url}
          onChange={(event) => update('cover_image_url', event.target.value)}
          placeholder="https://..."
          disabled={submitting}
        />
        {draft.cover_image_url ? (
          <img
            src={draft.cover_image_url}
            alt="封面預覽"
            className="modal-cover-preview"
            referrerPolicy="no-referrer"
            onError={(event) => {
              event.currentTarget.style.display = 'none'
            }}
          />
        ) : null}
      </div>

      {draft.evidence_urls.length > 0 && (
        <div className="modal-field">
          <label>AI 引用來源</label>
          <ul className="modal-evidence-list">
            {draft.evidence_urls.map((url) => (
              <li key={url}>
                <a href={url} target="_blank" rel="noreferrer noopener">
                  {url}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && <div className="modal-error">{error}</div>}
      {submitting && <div className="modal-loading">正在建立…</div>}

      <div className="modal-actions">
        <button
          type="button"
          className="modal-btn modal-btn-secondary"
          onClick={onCancel}
          disabled={submitting}
        >
          取消
        </button>
        <button
          type="button"
          className="modal-btn modal-btn-primary"
          onClick={() => onConfirm(draft)}
          disabled={submitting || !draft.canonical_name.trim()}
        >
          {submitting ? '建立中…' : '確認建立並開始爬取'}
        </button>
      </div>
    </Modal>
  )
}
