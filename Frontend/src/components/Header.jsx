import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { prApi, poApi, grnApi, issuanceApi, itemApi, vendorApi } from '../lib/api'
import { useAuth } from '../lib/AuthContext'

export default function Header({ title, subtitle, actions }) {
  const { user } = useAuth()
  const [query, setQuery]       = useState('')
  const [results, setResults]   = useState([])
  const [open, setOpen]         = useState(false)
  const [searching, setSearching] = useState(false)
  const inputRef  = useRef(null)
  const wrapRef   = useRef(null)
  const navigate  = useNavigate()

  // ⌘K / Ctrl+K shortcut
  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        inputRef.current?.focus()
        setOpen(true)
      }
      if (e.key === 'Escape') { setOpen(false); setQuery('') }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // Click outside to close
  useEffect(() => {
    const handler = (e) => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Search across all data
  useEffect(() => {
    if (!query.trim() || query.length < 2) { setResults([]); return }
    const q = query.toLowerCase()
    setSearching(true)
    Promise.all([
      prApi.getAll().catch(() => []),
      poApi.getAll().catch(() => []),
      itemApi.getAll().catch(() => []),
      vendorApi.getAll().catch(() => []),
      issuanceApi.getAll().catch(() => []),
    ]).then(([prs, pos, items, vendors, iss]) => {
      const hits = []

      prs.filter(r =>
        (r.pr_no||'').toLowerCase().includes(q) ||
        (r.item_name||'').toLowerCase().includes(q) ||
        (r.department||'').toLowerCase().includes(q)
      ).slice(0, 4).forEach(r => hits.push({
        type: 'PR', icon: '🛒',
        title: r.pr_no,
        sub: `${r.item_name} · ${r.department} · ${r.status}`,
        color: '#8b5cf6',
        path: '/procurement/pr'
      }))

      pos.filter(r =>
        (r.po_no||'').toLowerCase().includes(q) ||
        (r.item_name||'').toLowerCase().includes(q) ||
        (r.vendor_name||'').toLowerCase().includes(q)
      ).slice(0, 4).forEach(r => hits.push({
        type: 'PO', icon: '📋',
        title: r.po_no,
        sub: `${r.vendor_name} · ${r.item_name} · ${r.status}`,
        color: '#3b82f6',
        path: '/procurement/po'
      }))

      items.filter(r =>
        (r.code||'').toLowerCase().includes(q) ||
        (r.name||'').toLowerCase().includes(q) ||
        (r.category||'').toLowerCase().includes(q)
      ).slice(0, 4).forEach(r => hits.push({
        type: 'Item', icon: '📦',
        title: `${r.code} — ${r.name}`,
        sub: `${r.category} · ₹${r.rate} · ${r.status}`,
        color: '#10b981',
        path: '/masters/items'
      }))

      vendors.filter(r =>
        (r.code||'').toLowerCase().includes(q) ||
        (r.name||'').toLowerCase().includes(q) ||
        (r.category||'').toLowerCase().includes(q)
      ).slice(0, 3).forEach(r => hits.push({
        type: 'Vendor', icon: '🏭',
        title: r.name,
        sub: `${r.code} · ${r.category} · ${r.city||''}`,
        color: '#f59e0b',
        path: '/masters/vendors'
      }))

      iss.filter(r =>
        (r.issue_id||'').toLowerCase().includes(q) ||
        (r.item_code||'').toLowerCase().includes(q) ||
        (r.department||'').toLowerCase().includes(q)
      ).slice(0, 3).forEach(r => hits.push({
        type: 'Issuance', icon: '🔄',
        title: r.issue_id,
        sub: `${r.item_code} · ${r.department} · ${r.qty} ${r.uom}`,
        color: '#06b6d4',
        path: '/issuance'
      }))

      setResults(hits.slice(0, 12))
      setSearching(false)
    })
  }, [query])

  const go = (path) => {
    navigate(path)
    setOpen(false)
    setQuery('')
    setResults([])
  }

  return (
    <div className="topbar">
      <div className="topbar-left">
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      <div className="topbar-right">

        {/* ── Global Search ── */}
        <div ref={wrapRef} className="header-search-wrap" style={{ position: 'relative' }}>
          <div className="topbar-search" style={{ cursor: 'text', minWidth: 220 }}
            onClick={() => { setOpen(true); inputRef.current?.focus() }}>
            <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            {open ? (
              <input ref={inputRef} autoFocus value={query} onChange={e => setQuery(e.target.value)}
                placeholder="Search PRs, POs, items, vendors…"
                style={{ border: 'none', outline: 'none', background: 'transparent', fontSize: 13, width: 200, color: '#141720' }} />
            ) : (
              <span style={{ color: '#94a3b8', fontSize: 13 }}>Quick search…</span>
            )}
            <span style={{ fontSize: 11, background: '#edf0f7', borderRadius: 4, padding: '1px 5px', color: '#94a3b8', flexShrink: 0 }}>⌘K</span>
          </div>

          {/* Dropdown results */}
          {open && (
            <div style={{
              position: 'absolute', top: 'calc(100% + 8px)', right: 0,
              width: 380, background: 'white', borderRadius: 14,
              boxShadow: '0 20px 60px rgba(0,0,0,0.15)', border: '1px solid #edf0f7',
              zIndex: 999, overflow: 'hidden',
              animation: 'rowIn 0.2s ease both'
            }}>
              {!query && (
                <div style={{ padding: '20px 16px' }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>Quick Jump</div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                    {[
                      { icon: '🛒', label: 'Requisitions', path: '/procurement/pr', color: '#8b5cf6' },
                      { icon: '📋', label: 'Purchase Orders', path: '/procurement/po', color: '#3b82f6' },
                      { icon: '📦', label: 'GRN', path: '/procurement/grn', color: '#10b981' },
                      { icon: '🔄', label: 'Issuance', path: '/issuance', color: '#f59e0b' },
                      { icon: '🏭', label: 'Vendors', path: '/masters/vendors', color: '#06b6d4' },
                      { icon: '📊', label: 'Budget', path: '/budget', color: '#ec4899' },
                    ].map(item => (
                      <button key={item.path} onClick={() => go(item.path)}
                        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderRadius: 8,
                          border: '1px solid #f1f3f8', background: 'white', cursor: 'pointer', textAlign: 'left',
                          fontSize: 12.5, fontWeight: 500, color: '#374151', transition: 'all 0.12s' }}
                        onMouseEnter={e => { e.currentTarget.style.background = '#f8f9fc'; e.currentTarget.style.borderColor = item.color+'44' }}
                        onMouseLeave={e => { e.currentTarget.style.background = 'white'; e.currentTarget.style.borderColor = '#f1f3f8' }}>
                        <span style={{ fontSize: 15 }}>{item.icon}</span>
                        {item.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {query && searching && (
                <div style={{ padding: 20, textAlign: 'center', color: '#94a3b8', fontSize: 13 }}>Searching…</div>
              )}

              {query && !searching && results.length === 0 && (
                <div style={{ padding: 20, textAlign: 'center', color: '#94a3b8', fontSize: 13 }}>
                  No results for "<strong>{query}</strong>"
                </div>
              )}

              {query && !searching && results.length > 0 && (
                <div>
                  {results.map((r, i) => (
                    <button key={i} onClick={() => go(r.path)}
                      style={{ display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                        padding: '10px 16px', border: 'none', background: 'white', cursor: 'pointer',
                        textAlign: 'left', borderBottom: '1px solid #f8f9fc', transition: 'background 0.1s' }}
                      onMouseEnter={e => e.currentTarget.style.background = '#f8f9fc'}
                      onMouseLeave={e => e.currentTarget.style.background = 'white'}>
                      <div style={{ width: 32, height: 32, borderRadius: 8, background: r.color + '15',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, flexShrink: 0 }}>
                        {r.icon}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 600, fontSize: 13, color: '#141720', marginBottom: 1 }}>{r.title}</div>
                        <div style={{ fontSize: 11, color: '#94a3b8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.sub}</div>
                      </div>
                      <span style={{ fontSize: 10, fontWeight: 600, padding: '2px 7px', borderRadius: 5,
                        background: r.color + '15', color: r.color, flexShrink: 0 }}>{r.type}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {actions}
        <div className="avatar" onClick={() => navigate('/profile')} title={user?.full_name || 'Profile'}
          style={{ cursor:'pointer', background: user?.avatar_color ? `linear-gradient(135deg,${user.avatar_color},${user.avatar_color}cc)` : undefined, transition:'transform 0.15s' }}
          onMouseEnter={e=>e.currentTarget.style.transform='scale(1.08)'}
          onMouseLeave={e=>e.currentTarget.style.transform=''}>
          {user ? (user.full_name||'U').split(' ').map(p=>p[0]).slice(0,2).join('').toUpperCase() : 'A'}
        </div>
      </div>
    </div>
  )
}