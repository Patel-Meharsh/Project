import { useEffect } from 'react'

export default function SlideOver({ open, onClose, title, subtitle, children, footer, wide, xl }) {
  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null

  return (
    <>
      <div className="slideover-overlay" onClick={onClose} aria-hidden="true" />
      <div className={`slideover ${wide ? 'slideover-wide' : ''} ${xl ? 'slideover-xl' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="slideover-header">
          <div>
            <div className="slideover-title">{title}</div>
            {subtitle && <div className="slideover-sub">{subtitle}</div>}
          </div>
          <button className="slideover-close" onClick={onClose} aria-label="Close panel">×</button>
        </div>
        <div className="slideover-body">{children}</div>
        {footer && <div className="slideover-footer">{footer}</div>}
      </div>
    </>
  )
}
