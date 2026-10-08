import { useState, useCallback } from 'react'
import Header from '../components/Header'
import api from '../lib/api'

// All endpoints — uses the same axios instance (same-origin, auth header auto-attached)
const ENDPOINTS = [
  // Health
  { group: 'Health',     method: 'GET',  path: '/health',                       label: 'Health check',           raw: true },
  { group: 'Health',     method: 'GET',  path: '/',                             label: 'Root',                   raw: true },

  // Dashboard
  { group: 'Dashboard',  method: 'GET',  path: '/api/dashboard/kpis',           label: 'KPIs' },
  { group: 'Dashboard',  method: 'GET',  path: '/api/dashboard/spend-by-category', label: 'Spend by category' },
  { group: 'Dashboard',  method: 'GET',  path: '/api/dashboard/spend-by-location', label: 'Spend by location' },

  // Masters
  { group: 'Masters',    method: 'GET',  path: '/api/locations',                label: 'Locations' },
  { group: 'Masters',    method: 'GET',  path: '/api/vendors',                  label: 'Vendors' },
  { group: 'Masters',    method: 'GET',  path: '/api/items',                    label: 'Items' },
  { group: 'Masters',    method: 'GET',  path: '/api/hk-master',                label: 'HK Catalog' },
  { group: 'Masters',    method: 'GET',  path: '/api/hk-master/categories',     label: 'HK Categories' },

  // Inventory
  { group: 'Inventory',  method: 'GET',  path: '/api/inventory',                label: 'Stock register' },

  // Procurement
  { group: 'Procurement',method: 'GET',  path: '/api/purchase-requisitions',    label: 'PRs' },
  { group: 'Procurement',method: 'GET',  path: '/api/purchase-orders',          label: 'POs' },
  { group: 'Procurement',method: 'GET',  path: '/api/grns',                     label: 'GRNs' },
  { group: 'Procurement',method: 'GET',  path: '/api/issuances',                label: 'Issuances' },
  { group: 'Procurement',method: 'GET',  path: '/api/returns',                  label: 'Returns' },

  // Budget
  { group: 'Budget',     method: 'GET',  path: '/api/budget/calculated',        label: 'Budget calculated' },
  { group: 'Budget',     method: 'GET',  path: '/api/budget/vs-actual?month=1', label: 'vs Actual' },
  { group: 'Budget',     method: 'GET',  path: '/api/budget/category-summary',  label: 'Category summary' },
  { group: 'Budget',     method: 'GET',  path: '/api/budget/location-summary',  label: 'Location summary' },
  { group: 'Budget',     method: 'GET',  path: '/api/budget/monthly-forecast?inflation=6', label: 'Monthly forecast' },
  { group: 'Budget',     method: 'GET',  path: '/api/consumption-norms',        label: 'Consumption norms' },

  // Code gen
  { group: 'Code Gen',   method: 'GET',  path: '/api/next-code/grn',            label: 'Next GRN code' },
  { group: 'Code Gen',   method: 'GET',  path: '/api/next-code/pr',             label: 'Next PR code' },
  { group: 'Code Gen',   method: 'GET',  path: '/api/next-code/po',             label: 'Next PO code' },

  // Auth
  { group: 'Auth',       method: 'GET',  path: '/api/auth/me',                  label: 'Current user' },
  { group: 'Auth',       method: 'GET',  path: '/api/auth/users',               label: 'List users' },

  // Analytics
  { group: 'Analytics',  method: 'GET',  path: '/api/analytics/item-velocity',  label: 'Item velocity' },
  { group: 'Analytics',  method: 'GET',  path: '/api/events?limit=5',           label: 'Event log' },

  // Admin
  { group: 'Admin',      method: 'GET',  path: '/api/admin/data-summary',       label: 'Data summary' },
]

const METHOD_COLOR = { GET: '#2563eb', POST: '#16a34a', PUT: '#d97706', DELETE: '#dc2626' }
const fmtMs = ms => ms < 1000 ? `${ms}ms` : `${(ms/1000).toFixed(1)}s`

export default function ApiHealth() {
  const [results,  setResults]  = useState({})
  const [running,  setRunning]  = useState(false)
  const [progress, setProgress] = useState(0)
  const [filter,   setFilter]   = useState('all')

  const runOne = useCallback(async (ep) => {
    const key   = ep.method + ep.path
    const start = Date.now()
    setResults(r => ({ ...r, [key]: { status: 'running' } }))
    try {
      let res
      if (ep.raw) {
        // for / and /health use fetch directly (no /api prefix conflict)
        const r = await fetch(ep.path, { credentials: 'include' })
        res = { status: r.status, data: await r.json().catch(() => null) }
      } else {
        // strip /api prefix — axios baseURL already has it
        const stripped = ep.path.replace(/^\/api/, '')
        const r = await api.get(stripped)
        res = { status: r.status, data: r.data }
      }
      setResults(r => ({
        ...r,
        [key]: {
          status: res.status >= 200 && res.status < 300 ? 'ok' : 'error',
          httpStatus: res.status,
          ms: Date.now() - start,
          preview: res.data ? summarise(res.data) : null,
        }
      }))
    } catch(e) {
      const httpStatus = e.response?.status
      setResults(r => ({
        ...r,
        [key]: {
          status:     httpStatus === 401 ? 'auth' : 'error',
          httpStatus: httpStatus || 'ERR',
          ms:         Date.now() - start,
          error:      e.response?.data?.detail || e.message,
        }
      }))
    }
  }, [])

  const runAll = useCallback(async () => {
    setResults({}); setRunning(true); setProgress(0)
    for (let i = 0; i < ENDPOINTS.length; i++) {
      await runOne(ENDPOINTS[i])
      setProgress(Math.round(((i + 1) / ENDPOINTS.length) * 100))
      await new Promise(r => setTimeout(r, 50))
    }
    setRunning(false)
  }, [runOne])

  const keys    = ENDPOINTS.map(e => e.method + e.path)
  const done    = keys.filter(k => results[k] && results[k].status !== 'running')
  const passed  = done.filter(k => results[k].status === 'ok').length
  const authed  = done.filter(k => results[k].status === 'auth').length
  const failed  = done.filter(k => results[k].status === 'error').length
  const avgMs   = done.length ? Math.round(done.reduce((s,k) => s+(results[k].ms||0),0)/done.length) : 0

  const groups  = [...new Set(ENDPOINTS.map(e => e.group))]
  const showGroups = filter === 'all'   ? groups
    : filter === 'errors'               ? groups.filter(g => ENDPOINTS.filter(e=>e.group===g).some(e=>['error','auth'].includes(results[e.method+e.path]?.status)))
    : groups.filter(g => g === filter)

  return (
    <>
      <Header title="API Health" subtitle={`${ENDPOINTS.length} endpoints · ${done.length > 0 ? `${passed} passed, ${failed} failed${authed?' · '+authed+' auth':''}` : 'not run yet'}`} />
      <div className="page-content" style={{ maxWidth: 860 }}>

        {/* Run bar */}
        <div className="panel" style={{ marginBottom: 20 }}>
          <div className="panel-body" style={{ display:'flex', alignItems:'center', gap:16, flexWrap:'wrap' }}>
            <button className="btn btn-accent" onClick={runAll} disabled={running} style={{ minWidth: 120 }}>
              {running ? `Running… ${progress}%` : '▶ Run All'}
            </button>

            {done.length > 0 && (
              <div style={{ display:'flex', gap:14, flexWrap:'wrap' }}>
                {[
                  { val: passed,        label: 'passed',   color: '#16a34a', bg: '#f0fdf4' },
                  { val: failed,        label: 'failed',   color: '#dc2626', bg: '#fef2f2' },
                  { val: authed,        label: '401 auth', color: '#d97706', bg: '#fffbeb' },
                  { val: fmtMs(avgMs),  label: 'avg',      color: '#7c3aed', bg: '#f5f3ff' },
                ].filter(s => s.val !== 0 && s.val !== '0ms').map(s => (
                  <div key={s.label} style={{ background:s.bg, borderRadius:9, padding:'6px 14px', display:'flex', gap:6, alignItems:'baseline' }}>
                    <span style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:18, color:s.color }}>{s.val}</span>
                    <span style={{ fontSize:11.5, color:s.color, fontWeight:600 }}>{s.label}</span>
                  </div>
                ))}
              </div>
            )}

            {running && (
              <div style={{ flex:1, minWidth:160, display:'flex', alignItems:'center', gap:8 }}>
                <div style={{ flex:1, height:5, background:'var(--border)', borderRadius:99 }}>
                  <div style={{ width:`${progress}%`, height:'100%', background:'var(--amber)', borderRadius:99, transition:'width 0.2s' }} />
                </div>
                <span style={{ fontSize:12, color:'var(--ink-4)', whiteSpace:'nowrap' }}>{progress}%</span>
              </div>
            )}
          </div>
        </div>

        {/* Filter pills */}
        {done.length > 0 && (
          <div style={{ display:'flex', gap:6, marginBottom:16, flexWrap:'wrap' }}>
            {['all', 'errors', ...groups].map(f => {
              const isErr = f === 'errors'
              const cnt   = f === 'all' ? ENDPOINTS.length
                : f === 'errors' ? failed + authed
                : ENDPOINTS.filter(e=>e.group===f).length
              if (isErr && cnt === 0) return null
              return (
                <button key={f} onClick={() => setFilter(f)}
                  style={{ padding:'4px 13px', borderRadius:20, border:'1.5px solid', fontSize:12.5, fontWeight:600, cursor:'pointer',
                    background: filter===f ? (isErr?'#fef2f2':'var(--amber-soft)') : 'white',
                    borderColor: filter===f ? (isErr?'#dc2626':'var(--amber)') : 'var(--border)',
                    color: filter===f ? (isErr?'#dc2626':'var(--amber-dark)') : 'var(--ink-3)' }}>
                  {f==='all' ? 'All' : f==='errors' ? `⚠ Errors (${cnt})` : f}
                  {f!=='all' && f!=='errors' && <span style={{ marginLeft:5, opacity:0.5 }}>{cnt}</span>}
                </button>
              )
            })}
          </div>
        )}

        {/* Results */}
        {done.length === 0 && !running ? (
          <div className="panel" style={{ textAlign:'center', padding:'56px 24px', color:'var(--ink-4)' }}>
            <div style={{ fontSize:36, marginBottom:12 }}>🔌</div>
            <div style={{ fontSize:15, fontWeight:600, marginBottom:6, color:'var(--ink-3)' }}>Click Run All to test every endpoint</div>
            <div style={{ fontSize:13 }}>Runs directly through the app — no CORS issues</div>
          </div>
        ) : showGroups.map(group => {
          const eps = ENDPOINTS.filter(e => e.group === group)
          if (filter === 'errors' && !eps.some(e => ['error','auth'].includes(results[e.method+e.path]?.status))) return null
          const groupPassed = eps.filter(e => results[e.method+e.path]?.status === 'ok').length

          return (
            <div key={group} className="panel" style={{ marginBottom:10, padding:0, overflow:'hidden' }}>
              <div style={{ padding:'10px 20px', background:'var(--surface)', borderBottom:'1px solid var(--border-2)', display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                <span style={{ fontWeight:700, fontSize:13, color:'var(--ink)' }}>{group}</span>
                <span style={{ fontSize:12, color: groupPassed===eps.length ? 'var(--green)' : 'var(--ink-4)' }}>
                  {groupPassed}/{eps.length}
                </span>
              </div>
              {eps.map(ep => {
                const key = ep.method + ep.path
                const r   = results[key]
                if (filter==='errors' && !['error','auth'].includes(r?.status)) return null

                const dot = !r ? '#e8eaf2'
                  : r.status==='ok'      ? '#16a34a'
                  : r.status==='auth'    ? '#d97706'
                  : r.status==='error'   ? '#dc2626'
                  : '#f0a500'

                return (
                  <div key={key} style={{ display:'flex', alignItems:'center', gap:12, padding:'10px 20px', borderBottom:'1px solid var(--border-2)' }}>
                    <span style={{ background:METHOD_COLOR[ep.method]+'18', color:METHOD_COLOR[ep.method], padding:'2px 7px', borderRadius:5, fontSize:11, fontWeight:700, fontFamily:'monospace', flexShrink:0, minWidth:40, textAlign:'center' }}>
                      {ep.method}
                    </span>

                    <div style={{ width:9, height:9, borderRadius:'50%', flexShrink:0, background:dot,
                      boxShadow: r?.status==='ok' ? '0 0 0 3px #bbf7d060' : r?.status==='error' ? '0 0 0 3px #fecaca60' : 'none' }} />

                    <div style={{ flex:1, minWidth:0 }}>
                      <div style={{ fontSize:13, fontWeight:600, color:'var(--ink)' }}>{ep.label}</div>
                      <div style={{ fontFamily:'monospace', fontSize:11, color:'var(--ink-4)', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>{ep.path}</div>
                      {r?.error && <div style={{ fontSize:11.5, color:'#dc2626', marginTop:2 }}>{r.error}</div>}
                      {r?.preview && <div style={{ fontSize:11, color:'var(--ink-4)', marginTop:1 }}>{r.preview}</div>}
                    </div>

                    <div style={{ display:'flex', alignItems:'center', gap:10, flexShrink:0 }}>
                      {r?.httpStatus && (
                        <span style={{ fontFamily:'monospace', fontSize:12.5, fontWeight:700,
                          color: r.status==='ok' ? '#16a34a' : r.status==='auth' ? '#d97706' : '#dc2626' }}>
                          {r.httpStatus}
                        </span>
                      )}
                      {r?.ms && <span style={{ fontSize:11.5, color:'var(--ink-4)' }}>{fmtMs(r.ms)}</span>}
                    </div>

                    {r?.status === 'running' ? (
                      <div style={{ width:14, height:14, border:'2px solid var(--border)', borderTopColor:'var(--amber)', borderRadius:'50%', flexShrink:0,
                        animation:'spin 0.65s linear infinite' }} />
                    ) : (
                      <button onClick={() => runOne(ep)}
                        style={{ padding:'3px 9px', borderRadius:6, border:'1px solid var(--border)', background:'white', fontSize:12, color:'var(--ink-4)', cursor:'pointer', flexShrink:0 }}>
                        ↺
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </>
  )
}

function summarise(data) {
  if (Array.isArray(data))   return `${data.length} rows`
  if (data && typeof data === 'object') {
    const keys = Object.keys(data)
    if (keys.length <= 4) return keys.map(k => `${k}: ${JSON.stringify(data[k])?.slice(0,30)}`).join(' · ')
    return `${keys.length} fields`
  }
  return String(data).slice(0, 60)
}
