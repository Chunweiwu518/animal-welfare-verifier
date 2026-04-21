import { useState } from 'react'
import type { AuthUser } from '../api/auth'
import { logout } from '../api/auth'

interface UserBadgeProps {
  user: AuthUser
  onLoggedOut: () => void
  onClickLogin: () => void
}

export function UserBadge({ user, onLoggedOut, onClickLogin }: UserBadgeProps) {
  const [open, setOpen] = useState(false)

  if (!user.authenticated) {
    return (
      <button type="button" className="header-login-btn" onClick={onClickLogin}>
        登入
      </button>
    )
  }

  return (
    <div className="user-badge-wrap">
      <button
        type="button"
        className="user-badge-btn"
        onClick={() => setOpen((v) => !v)}
        title={user.display_name}
      >
        {user.avatar_url ? (
          <img
            src={user.avatar_url}
            alt=""
            className="user-avatar"
            referrerPolicy="no-referrer"
            onError={(event) => {
              event.currentTarget.style.display = 'none'
            }}
          />
        ) : (
          <span className="user-avatar-fallback">
            {user.display_name?.slice(0, 1) ?? '?'}
          </span>
        )}
        <span className="user-name">{user.display_name}</span>
      </button>
      {open ? (
        <div className="user-menu">
          <button
            type="button"
            className="user-menu-item"
            onClick={async () => {
              await logout()
              onLoggedOut()
              setOpen(false)
            }}
          >
            登出
          </button>
        </div>
      ) : null}
    </div>
  )
}
