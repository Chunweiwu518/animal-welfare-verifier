import { Modal } from './Modal'

interface CreateShelterDialogProps {
  open: boolean
  query: string
  loading: boolean
  error: string | null
  onConfirm: () => void
  onCancel: () => void
}

export function CreateShelterDialog({
  open,
  query,
  loading,
  error,
  onConfirm,
  onCancel,
}: CreateShelterDialogProps) {
  return (
    <Modal open={open} onClose={onCancel} title="這個狗園還沒收錄">
      <p className="modal-hint">
        在資料庫中找不到「<strong>{query}</strong>」。
        要我用 LLM 加上網路搜尋確認它是否存在，並把它加入每月定期爬取清單嗎？
      </p>
      {error && <div className="modal-error">{error}</div>}
      {loading && <div className="modal-loading">正在用 AI 查證，大約 10–30 秒…</div>}
      <div className="modal-actions">
        <button
          type="button"
          className="modal-btn modal-btn-secondary"
          onClick={onCancel}
          disabled={loading}
        >
          取消
        </button>
        <button
          type="button"
          className="modal-btn modal-btn-primary"
          onClick={onConfirm}
          disabled={loading}
        >
          {loading ? '查證中…' : '好，幫我查'}
        </button>
      </div>
    </Modal>
  )
}
