import { ReactNode, useEffect, useRef } from 'react'
import './modal.css'

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  labelledById?: string
}

export function Modal({ open, onClose, title, children, labelledById }: ModalProps) {
  const panelRef = useRef<HTMLDivElement | null>(null)
  const previouslyFocused = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!open) return

    previouslyFocused.current = document.activeElement as HTMLElement | null
    panelRef.current?.focus()

    function handleKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
      }
    }

    document.addEventListener('keydown', handleKey)
    const { body } = document
    const previousOverflow = body.style.overflow
    body.style.overflow = 'hidden'

    return () => {
      document.removeEventListener('keydown', handleKey)
      body.style.overflow = previousOverflow
      previouslyFocused.current?.focus?.()
    }
  }, [open, onClose])

  if (!open) return null

  const titleId = labelledById ?? 'modal-title'

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        ref={panelRef}
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <h2 className="modal-title" id={titleId}>
          {title}
        </h2>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}
