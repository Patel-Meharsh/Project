import { STATUS_CONFIG, PRIORITY_CONFIG } from '../lib/utils'

export function StatusBadge({ status }) {
  const cfg = STATUS_CONFIG[status] || { color: '#64748b', bg: '#f8fafc' }
  return <span className="badge" style={{ color: cfg.color, background: cfg.bg }}>{status}</span>
}

export function PriorityBadge({ priority }) {
  const cfg = PRIORITY_CONFIG[priority] || { color: '#64748b', bg: '#f8fafc' }
  return <span className="badge" style={{ color: cfg.color, background: cfg.bg }}>{priority}</span>
}

export function Spinner({ center = true }) {
  if (center) return <div className="loading-center"><div className="spinner" /></div>
  return <div className="spinner" />
}

export function EmptyState({ icon = '📭', message = 'No data found', action }) {
  return (
    <div className="empty" role="status">
      <div className="empty-icon" aria-hidden="true">{icon}</div>
      <p>{message}</p>
      {action && <div style={{ marginTop: 12 }}>{action}</div>}
    </div>
  )
}

export function Modal({ open, onClose, title, children, footer, large }) {
  if (!open) return null
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()} role="presentation">
      <div className={`modal ${large ? 'modal-lg' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-header">
          <span className="modal-title">{title}</span>
          <button onClick={onClose} aria-label="Close dialog" style={{ background:'none', border:'none', cursor:'pointer', color:'#94a3b8', fontSize:20, lineHeight:1 }}>×</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  )
}

export function FormRow({ label, children, half, third, hint }) {
  const width = third ? 'calc(33.3% - 8px)' : half ? 'calc(50% - 6px)' : '100%'
  return (
    <div style={{ marginBottom:14, width }}>
      <label className="label">{label}</label>
      {children}
      {hint && <div style={{ fontSize:11, color:'#94a3b8', marginTop:3 }}>{hint}</div>}
    </div>
  )
}

export function FormGrid({ children }) {
  return <div style={{ display:'flex', flexWrap:'wrap', gap:12 }}>{children}</div>
}

export function Stars({ rating }) {
  return (
    <div className="stars">
      {[1,2,3,4,5].map(s => (
        <svg key={s} className={`star ${s <= Math.round(rating) ? '' : 'empty'}`} fill="currentColor" viewBox="0 0 20 20">
          <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
        </svg>
      ))}
      <span style={{ fontSize:12, color:'#64748b', marginLeft:4 }}>{rating}</span>
    </div>
  )
}

export function InfoRow({ label, value, mono }) {
  return (
    <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', padding:'8px 0', borderBottom:'1px solid #f8f9fc' }}>
      <span style={{ fontSize:12.5, color:'#64748b' }}>{label}</span>
      <span style={{ fontWeight:500, color:'#0d0f1a', fontFamily: mono ? "'JetBrains Mono',monospace" : 'inherit', fontSize: mono ? 12 : 13.5 }}>{value || '—'}</span>
    </div>
  )
}

export function SectionDivider({ label }) {
  return (
    <div style={{ display:'flex', alignItems:'center', gap:10, margin:'18px 0 14px' }}>
      <span style={{ fontSize:11, fontWeight:600, color:'#94a3b8', textTransform:'uppercase', letterSpacing:'0.1em', whiteSpace:'nowrap' }}>{label}</span>
      <div style={{ flex:1, height:1, background:'#f1f3f8' }} />
    </div>
  )
}

export function SearchInput({ value, onChange, placeholder, style }) {
  return (
    <div className="search-box" style={{ width:240, ...style }}>
      <svg className="search-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
      <input className="input input-sm" value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder || 'Search…'} aria-label={placeholder || 'Search'} />
    </div>
  )
}

export function CategoryDot({ category }) {
  const COLORS = {'Cleaning Chemicals':'#06b6d4','Washroom Supplies':'#8b5cf6','Cleaning Tools':'#10b981','Waste Management':'#f59e0b','Pantry':'#f97316','Electrical':'#3b82f6','PPE & Safety':'#ec4899','Pest Control':'#84cc16'}
  const color = COLORS[category] || '#94a3b8'
  return <span style={{ display:'inline-flex', alignItems:'center', gap:6, whiteSpace:'nowrap' }}><span style={{ width:8, height:8, borderRadius:'50%', background:color, flexShrink:0 }} />{category}</span>
}

export function Tooltip({ text, children }) {
  return (
    <span style={{ position:'relative', display:'inline-flex' }} className="tooltip-wrap">
      {children}
      <span className="tooltip-content">{text}</span>
      <style>{`.tooltip-wrap:hover .tooltip-content{opacity:1;transform:translateY(-2px)}.tooltip-content{position:absolute;bottom:calc(100% + 6px);left:50%;transform:translateX(-50%) translateY(0);background:#0d0f1a;color:white;font-size:11px;padding:5px 9px;border-radius:6px;white-space:nowrap;pointer-events:none;opacity:0;transition:all 0.15s;z-index:999;max-width:280px;white-space:normal;text-align:center;}`}</style>
    </span>
  )
}

export function ProgressRing({ value, max, color = '#f0a500', size = 60 }) {
  const pct = Math.min(value / max * 100, 100)
  const r = (size - 8) / 2
  const circ = 2 * Math.PI * r
  const offset = circ - (pct / 100) * circ
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ transform:'rotate(-90deg)' }}>
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#f1f3f8" strokeWidth={6} />
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth={6} strokeDasharray={circ} strokeDashoffset={offset} strokeLinecap="round" style={{ transition:'stroke-dashoffset 0.5s' }} />
    </svg>
  )
}
