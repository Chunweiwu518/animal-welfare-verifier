import { useEffect, useState } from 'react'
import { Modal } from './Modal'
import { getAdminToken, setAdminToken } from '../api/adminToken'

interface AdminTokenDialogProps {
  open: boolean
  onClose: () => void
  onSaved?: (token: string) => void
}

export function AdminTokenDialog({ open, onClose, onSaved }: AdminTokenDialogProps) {
  const [value, setValue] = useState('')

  useEffect(() => {
    if (open) setValue(getAdminToken())
  }, [open])

  function handleSave() {
    setAdminToken(value)
    onSaved?.(value.trim())
    onClose()
  }

  function handleClear() {
    setAdminToken('')
    setValue('')
    onSaved?.('')
    onClose()
  }

  return (
    <Modal open={open} onClose={onClose} title="設定管理員 Token">
      <p className="modal-hint">
        建立/驗證狗園、上傳媒體會消耗 OpenAI、Tavily、SerpApi 等 API 配額，所以需要管理員 Token。
        Token 只存在你自己的瀏覽器 localStorage，不會送到別的地方。
        （瀏覽狗園、看評論、留言都不需要 Token。）
      </p>

      <div className="modal-field">
        <label htmlFor="admin-token-input">Admin Token</label>
        <input
          id="admin-token-input"
          type="password"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="貼上你的 ADMIN_TOKEN"
          autoComplete="off"
          spellCheck={false}
        />
      </div>

      <div className="modal-actions">
        <button type="button" className="modal-btn modal-btn-secondary" onClick={handleClear}>
          清除
        </button>
        <button type="button" className="modal-btn modal-btn-secondary" onClick={onClose}>
          取消
        </button>
        <button type="button" className="modal-btn modal-btn-primary" onClick={handleSave}>
          儲存
        </button>
      </div>
    </Modal>
  )
}
