import { Modal } from './Modal'
import { buildLineLoginUrl } from '../api/auth'

interface LoginDialogProps {
  open: boolean
  message?: string
  onClose: () => void
}

export function LoginDialog({ open, message, onClose }: LoginDialogProps) {
  function handleLine() {
    window.location.href = buildLineLoginUrl(window.location.pathname)
  }

  return (
    <Modal open={open} onClose={onClose} title="需要登入">
      <p className="modal-hint">
        {message ?? '給評論打分會計入該狗園的公信力總分。為了避免刷票，請先用 LINE 登入（免費、只拿你的 display name + 頭像）。'}
      </p>

      <div className="modal-actions" style={{ flexDirection: 'column', gap: '0.75rem' }}>
        <button
          type="button"
          className="login-btn login-btn-line"
          onClick={handleLine}
        >
          <span className="login-btn-icon">LINE</span>
          <span>用 LINE 繼續</span>
        </button>
        <button
          type="button"
          className="modal-btn modal-btn-secondary"
          onClick={onClose}
        >
          稍後再說
        </button>
      </div>

      <p className="modal-hint" style={{ fontSize: '0.75rem', marginTop: '1rem', textAlign: 'center', color: '#5f6368' }}>
        我們不會發任何訊息給你，登入只用於識別投票者防刷。
      </p>
    </Modal>
  )
}
