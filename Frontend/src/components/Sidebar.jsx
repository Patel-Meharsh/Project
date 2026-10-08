import { useState, useRef, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/AuthContext'
import { ROLES, canDo } from '../lib/auth'

// Full nav — filtered by role below
const NAV_ALL = [
  { section: 'Overview' },
  { label: 'Dashboard', path: '/', icon: 'grid', minRole: 'observer' },

  { section: 'Operations' },
  { label: 'Stock Register',  path: '/inventory', icon: 'box',     minRole: 'observer' },
  {
    label: 'Procurement', icon: 'cart', key: 'proc', minRole: 'observer',
    children: [
      { label: 'Requisitions (PR)', path: '/procurement/pr',  minRole: 'observer' },
      { label: 'Purchase Orders',   path: '/procurement/po',  minRole: 'observer' },
      { label: 'Goods Receipt',     path: '/procurement/grn', minRole: 'observer' },
      { label: 'Returns Log',       path: '/returns',         minRole: 'observer' },
    ]
  },
  { label: 'Issuance Log', path: '/issuance', icon: 'arrow', minRole: 'observer' },
  { label: 'Import Hub',   path: '/import',   icon: 'upload', minRole: 'admin'      },
  { label: 'Admin Tools',   path: '/admin',    icon: 'shield', minRole: 'super_admin' },
  { label: 'API Health',    path: '/admin/health', icon: 'pulse',  minRole: 'super_admin' },

  { section: 'Masters' },
  {
    label: 'Item Masters', icon: 'catalog', key: 'masters', minRole: 'observer',
    children: [
      { label: 'Active Items',         path: '/masters/items',          minRole: 'observer' },
      { label: 'Master Groups',        path: '/masters/master-groups',  minRole: 'observer' },
      { label: 'HK Benchmark Catalog', path: '/masters/hk',             minRole: 'observer' },
      { label: 'Vendor Directory',     path: '/masters/vendors',         minRole: 'observer' },
    ]
  },
  { label: 'Locations', path: '/locations', icon: 'pin', minRole: 'observer' },

  { section: 'Finance' },
  {
    label: 'Budget & Analytics', icon: 'chart', key: 'budget', minRole: 'observer',
    children: [
      { label: 'Overview',          path: '/budget',            minRole: 'observer' },
      { label: 'Budget vs Actual',  path: '/budget/variance',   minRole: 'observer' },
      { label: 'Budget Calculator', path: '/budget/calculator', minRole: 'observer' },
      { label: 'Consumption Norms', path: '/budget/norms',      minRole: 'observer' },
      { label: 'Forecasting',       path: '/budget/forecast',   minRole: 'observer' },
    ]
  },
]

const ICONS = {
  grid:    <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>,
  box:     <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"/></svg>,
  cart:    <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.3 2.3c-.6.6-.2 1.7.7 1.7H17m0 0a2 2 0 100 4 2 2 0 000-4zm-10 2a2 2 0 100 4 2 2 0 000-4z"/></svg>,
  arrow:   <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4"/></svg>,
  upload:  <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/></svg>,
  catalog: <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/></svg>,
  pin:     <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"/><path strokeLinecap="round" strokeLinejoin="round" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"/></svg>,
  pulse:   <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M9 19V6l2 5h4l2-7v16"/></svg>,
  shield:  <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg>,
  chart:   <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>,
}

function filterNav(nav, userRole) {
  return nav.reduce((acc, item) => {
    if (!item.minRole && !item.section && !item.children) { acc.push(item); return acc }
    if (item.section) { acc.push(item); return acc }
    if (!canDo(userRole, item.minRole)) return acc
    if (item.children) {
      const kids = item.children.filter(c => canDo(userRole, c.minRole))
      if (kids.length) acc.push({ ...item, children: kids })
      return acc
    }
    acc.push(item)
    return acc
  }, [])
}

export default function Sidebar() {
  const location = useLocation()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [open, setOpen] = useState(() => {
    try { return JSON.parse(localStorage.getItem('sidebar_open')) || { proc: true, masters: true, budget: true } }
    catch { return { proc: true, masters: true, budget: true } }
  })
  const [mobileOpen, setMobileOpen] = useState(false)
  const sidebarRef = useRef(null)

  // Close mobile sidebar on route change
  useEffect(() => { setMobileOpen(false) }, [location.pathname])

  // Close mobile sidebar on outside click
  useEffect(() => {
    if (!mobileOpen) return
    const handler = (e) => {
      if (sidebarRef.current && !sidebarRef.current.contains(e.target) && !e.target.closest('.sidebar-hamburger')) {
        setMobileOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [mobileOpen])

  // Close on Escape
  useEffect(() => {
    if (!mobileOpen) return
    const handler = (e) => { if (e.key === 'Escape') setMobileOpen(false) }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [mobileOpen])

  const role    = user?.role || 'observer'
  const nav     = filterNav(NAV_ALL, role)

  const isActive       = (path) => location.pathname === path
  const isParentActive = (children) => children?.some(c => isActive(c.path))

  const handleNavigate = (path) => {
    navigate(path)
    setMobileOpen(false)
  }

  return (
    <>
      {/* Mobile hamburger button */}
      <button
        className="sidebar-hamburger"
        onClick={() => setMobileOpen(v => !v)}
        aria-label={mobileOpen ? 'Close navigation' : 'Open navigation'}
        aria-expanded={mobileOpen}
      >
        <svg width="22" height="22" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          {mobileOpen
            ? <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12"/>
            : <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16"/>
          }
        </svg>
      </button>

      {/* Mobile overlay */}
      {mobileOpen && <div className="sidebar-overlay" onClick={() => setMobileOpen(false)} />}

      <nav
        ref={sidebarRef}
        className={`sidebar ${mobileOpen ? 'sidebar-mobile-open' : ''}`}
        role="navigation"
        aria-label="Main navigation"
      >
        <div className="sidebar-logo">
          <div className="sidebar-logo-mark">G</div>
          <div className="sidebar-logo-text">
            <div className="brand">Gateway Group</div>
            <div className="sub">Inventory OS</div>
          </div>
        </div>

        <div style={{ flex:1, paddingBottom:8, overflowY:'auto' }}>
          {nav.map((item, i) => {
            if (item.section) return (
              <div key={i} className="nav-section"><div className="nav-section-label">{item.section}</div></div>
            )
            if (item.children) {
              const isOpen = open[item.key]
              const parentActive = isParentActive(item.children)
              return (
                <div key={i} style={{ padding:'0 12px' }}>
                  <div className={`nav-parent ${isOpen?'open':''} ${parentActive?'active':''}`}
                    onClick={() => setOpen(s => { const n = {...s,[item.key]:!s[item.key]}; localStorage.setItem('sidebar_open', JSON.stringify(n)); return n })}
                    role="button"
                    aria-expanded={isOpen}
                    tabIndex={0}
                    onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(s => { const n = {...s,[item.key]:!s[item.key]}; localStorage.setItem('sidebar_open', JSON.stringify(n)); return n }) } }}
                    >
                    <span style={{ fontSize:16, width:22, flexShrink:0 }}>{ICONS[item.icon]||item.icon}</span>
                    <span style={{ flex:1, fontSize:13.5 }}>{item.label}</span>
                    <svg className={`nav-chevron ${isOpen?'open':''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/>
                    </svg>
                  </div>
                  {isOpen && (
                    <div className="nav-sub" role="group" aria-label={item.label}>
                      {item.children.map((child, j) => (
                        <div key={j} className={`nav-item ${isActive(child.path)?'active':''}`}
                          id={`nav-${child.path.replace(/\//g,'-').slice(1)}`}
                          onClick={() => handleNavigate(child.path)}
                          role="link"
                          tabIndex={0}
                          onKeyDown={e => { if (e.key === 'Enter') handleNavigate(child.path) }}
                        >
                          <span style={{ width:6, height:6, borderRadius:'50%', background:isActive(child.path)?'var(--amber)':'var(--border)', flexShrink:0 }} />
                          {child.label}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            }
            return (
              <div key={i} style={{ padding:'0 12px' }}>
                <div className={`nav-item ${isActive(item.path)?'active':''}`}
                  id={`nav-${item.path.replace(/\//g,'-').slice(1)||'home'}`}
                  onClick={() => handleNavigate(item.path)}
                  role="link"
                  tabIndex={0}
                  onKeyDown={e => { if (e.key === 'Enter') handleNavigate(item.path) }}
                >
                  <span style={{ fontSize:16, width:22, textAlign:'center', flexShrink:0 }}>{ICONS[item.icon]||item.icon}</span>
                  {item.label}
                </div>
              </div>
            )
          })}
        </div>

        {/* User pill */}
        <div id="sidebar-user-pill" style={{ padding:'0 12px 16px' }}>
          <div onClick={() => handleNavigate('/profile')}
            style={{ display:'flex', alignItems:'center', gap:10, padding:'10px 12px', borderRadius:10, background:'var(--surface)', cursor:'pointer', border:'1px solid var(--border-2)', transition:'background 0.15s' }}
            onMouseEnter={e=>e.currentTarget.style.background='var(--border-2)'}
            onMouseLeave={e=>e.currentTarget.style.background='var(--surface)'}
            role="link"
            tabIndex={0}
            onKeyDown={e => { if (e.key === 'Enter') handleNavigate('/profile') }}
            aria-label="Go to profile"
          >
            <div style={{ width:30, height:30, borderRadius:'50%', background:`linear-gradient(135deg,${user?.avatar_color||'#f0a500'},${user?.avatar_color||'#f0a500'}99)`, display:'flex', alignItems:'center', justifyContent:'center', color:'white', fontWeight:700, fontSize:11, flexShrink:0 }}>
              {(user?.full_name||'U').split(' ').map(p=>p[0]).slice(0,2).join('').toUpperCase()}
            </div>
            <div style={{ flex:1, minWidth:0 }}>
              <div style={{ fontSize:12.5, fontWeight:600, color:'var(--ink)', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{user?.full_name||'User'}</div>
              <div style={{ fontSize:10.5, color:ROLES[user?.role]?.color||'#94a3b8', fontWeight:500 }}>{ROLES[user?.role]?.label||'Observer'}</div>
            </div>
            <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="var(--ink-4)" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7"/></svg>
          </div>
        </div>
      </nav>
    </>
  )
}
