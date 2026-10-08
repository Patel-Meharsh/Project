import { useState } from 'react'
import Header from '../components/Header'
import { adminApi } from '../lib/api'
import { useAuth } from '../lib/AuthContext'
import { fmtNum } from '../lib/utils'
import { Spinner } from '../components/UI'
import useDataFetch from '../lib/useDataFetch'
import { useToast } from '../components/Toast'

const TABLE_LABELS = {
  locations: 'Locations', vendors: 'Vendors', hk_master: 'HK Benchmark Catalog',
  items: 'Active Items', inventory: 'Inventory Rows', consumption_norms: 'Consumption Norms',
  purchase_requisitions: 'Purchase Requisitions', purchase_orders: 'Purchase Orders',
  grns: 'Goods Receipt Notes', issuances: 'Issuance Log', returns: 'Returns Log',
  monthly_budget: 'Monthly Budget', event_log: 'Event Log', users: 'User Accounts',
  issuance_log: 'Issuance Log', returns_log: 'Returns Log',
  third_party_services: 'Third-Party Services',
}

const TRANSACTIONAL = ['purchase_requisitions','purchase_orders','grns','issuances','returns','monthly_budget','inventory','consumption_norms','event_log']
const MASTERS       = ['locations','vendors','hk_master','items']


export default function Admin() {
  const { user } = useAuth()
  const toast = useToast()
  const { data: summary, loading, refetch: load } = useDataFetch(() =>
    adminApi.dataSummary().catch(err => { toast.error('Failed to load data summary'); return null })
  )
  const [keepMasters, setKeepMasters] = useState(false)
  const [phase, setPhase]           = useState('idle')
  const [result, setResult]         = useState(null)
  const [typed,  setTyped]          = useState('')
  const [error,  setError]          = useState('')


  const doReset = async () => {
    if (typed !== 'RESET') return
    setPhase('resetting')
    setError('')
    try {
      const res = await adminApi.resetData(keepMasters)
      setResult(res); setPhase('done'); load()
      toast.success('Data reset complete')
    } catch(e) {
      setError('Reset failed: ' + (e.response?.data?.detail || e.message))
      toast.error('Data reset failed')
      setPhase('confirm')
    }
  }

  const totalRows    = summary ? Object.entries(summary).filter(([k])=>k!=='users').reduce((s,[,v])=>s+v,0) : 0
  const mastersCount = summary ? (summary.locations+summary.vendors+summary.hk_master+summary.items) : 0
  const txnCount     = summary ? (totalRows - mastersCount) : 0

  return (
    <>
      <Header title="Admin Tools" subtitle="Super admin controls — users, data reset, system management" />
      <div className="page-content" style={{ maxWidth: 900 }}>

        {/* ── DATA SUMMARY ── */}
        <div className="panel" style={{ marginBottom:24 }}>
          <div className="panel-header">
            <div>
              <div className="panel-title">Data Summary</div>
              <div className="panel-sub">Live row counts across all tables</div>
            </div>
            <button className="btn btn-outline btn-sm" onClick={load} disabled={loading}>
              {loading ? 'Loading…' : '↻ Refresh'}
            </button>
          </div>
          <div className="panel-body" style={{ paddingTop:0 }}>
            {loading ? (
              <div style={{ padding:32, textAlign:'center' }}><Spinner /></div>
            ) : summary ? (
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:8 }}>
                <div>
                  <div style={{ fontSize:10.5, fontWeight:700, color:'var(--ink-4)',
                    textTransform:'uppercase', letterSpacing:'0.1em', marginBottom:8 }}>Masters</div>
                  {MASTERS.map(k => (
                    <div key={k} className="stat-row">
                      <span style={{ fontSize:13.5, color:'var(--ink-2)' }}>{TABLE_LABELS[k]}</span>
                      <span style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:15,
                        color: summary[k] > 0 ? 'var(--ink)' : 'var(--ink-4)' }}>{fmtNum(summary[k])}</span>
                    </div>
                  ))}
                  <div className="stat-row" style={{ borderTop:'1px solid var(--border)', marginTop:4, paddingTop:8 }}>
                    <span style={{ fontSize:12, fontWeight:600, color:'var(--ink-3)' }}>Users</span>
                    <span style={{ fontFamily:"'Fraunces',serif", fontWeight:700, color:'var(--green)' }}>{summary.users}</span>
                  </div>
                </div>
                <div>
                  <div style={{ fontSize:10.5, fontWeight:700, color:'var(--ink-4)',
                    textTransform:'uppercase', letterSpacing:'0.1em', marginBottom:8 }}>Transactional</div>
                  {TRANSACTIONAL.map(k => (
                    <div key={k} className="stat-row">
                      <span style={{ fontSize:13.5, color:'var(--ink-2)' }}>{TABLE_LABELS[k]}</span>
                      <span style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:15,
                        color: summary[k] > 0 ? 'var(--ink)' : 'var(--ink-4)' }}>{fmtNum(summary[k])}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : <div style={{ color:'var(--ink-4)', padding:24 }}>Could not load summary</div>}
          </div>
        </div>

        {/* ── DATA RESET ── */}
        <div style={{ background:'#fff1f2', border:'1.5px solid #fecdd3', borderRadius:16, padding:28 }}>
          <div style={{ display:'flex', alignItems:'flex-start', gap:14, marginBottom:20 }}>
            <div style={{ fontSize:28, flexShrink:0 }}>⚠️</div>
            <div>
              <div style={{ fontFamily:"'Fraunces',serif", fontSize:18, fontWeight:700,
                color:'#be123c', marginBottom:4 }}>Reset All Data</div>
              <div style={{ fontSize:13.5, color:'#9f1239', lineHeight:1.6 }}>
                Permanently deletes inventory, procurement, and financial data.
                User accounts are <strong>always preserved</strong>. Cannot be undone.
              </div>
            </div>
          </div>

          <div style={{ background:'white', borderRadius:10, padding:'14px 18px',
            marginBottom:20, border:'1px solid #fecdd3' }}>
            <div style={{ fontSize:12, fontWeight:700, color:'#be123c', textTransform:'uppercase',
              letterSpacing:'0.08em', marginBottom:10 }}>Choose what to delete</div>
            <label style={{ display:'flex', alignItems:'flex-start', gap:12, cursor:'pointer', marginBottom:12 }}>
              <input type="radio" checked={!keepMasters} onChange={()=>setKeepMasters(false)}
                style={{ marginTop:3, accentColor:'#dc2626' }} />
              <div>
                <div style={{ fontWeight:600, fontSize:13.5, color:'var(--ink)' }}>Full reset</div>
                <div style={{ fontSize:12.5, color:'var(--ink-3)', marginTop:2 }}>
                  Deletes everything including locations, vendors, items and HK catalog.
                </div>
              </div>
            </label>
            <label style={{ display:'flex', alignItems:'flex-start', gap:12, cursor:'pointer' }}>
              <input type="radio" checked={keepMasters} onChange={()=>setKeepMasters(true)}
                style={{ marginTop:3, accentColor:'#dc2626' }} />
              <div>
                <div style={{ fontWeight:600, fontSize:13.5, color:'var(--ink)' }}>Transactional reset only</div>
                <div style={{ fontSize:12.5, color:'var(--ink-3)', marginTop:2 }}>
                  Keeps masters. Clears PR, PO, GRN, issuances, returns, stock levels and budget actuals.
                </div>
              </div>
            </label>
          </div>

          {summary && (
            <div style={{ display:'flex', gap:10, marginBottom:20 }}>
              <div style={{ flex:1, background:'white', borderRadius:10, padding:'12px 16px',
                border:'1px solid #fecdd3', textAlign:'center' }}>
                <div style={{ fontFamily:"'Fraunces',serif", fontSize:22, fontWeight:700, color:'#dc2626' }}>
                  {fmtNum(keepMasters ? txnCount : totalRows)}
                </div>
                <div style={{ fontSize:11.5, color:'#9f1239', fontWeight:600 }}>rows to delete</div>
              </div>
              <div style={{ flex:1, background:'white', borderRadius:10, padding:'12px 16px',
                border:'1px solid #bbf7d0', textAlign:'center' }}>
                <div style={{ fontFamily:"'Fraunces',serif", fontSize:22, fontWeight:700, color:'var(--green)' }}>
                  {summary.users}
                </div>
                <div style={{ fontSize:11.5, color:'var(--green)', fontWeight:600 }}>user accounts kept</div>
              </div>
            </div>
          )}

          {phase === 'idle' && (
            <button className="btn" onClick={() => setPhase('confirm')}
              style={{ background:'#dc2626', color:'white', fontWeight:700, padding:'10px 22px' }}>
              Proceed to confirm →
            </button>
          )}

          {phase === 'confirm' && (
            <div style={{ background:'white', borderRadius:10, padding:20, border:'1px solid #fecdd3' }}>
              {error && (
                <div style={{ background:'#fef2f2', border:'1px solid #fecaca', borderRadius:8, padding:'10px 14px', marginBottom:14, fontSize:13, color:'#dc2626', fontWeight:500 }}>
                  ❌ {error}
                </div>
              )}
              <div style={{ fontSize:13.5, fontWeight:600, color:'var(--ink)', marginBottom:12 }}>
                Type <code style={{ background:'#fef2f2', padding:'2px 7px', borderRadius:5,
                  fontFamily:'monospace', color:'#dc2626' }}>RESET</code> to confirm
              </div>
              <input className="input" value={typed}
                onChange={e => setTyped(e.target.value.toUpperCase())}
                placeholder="Type RESET" autoFocus
                style={{ marginBottom:14, fontFamily:'monospace', fontSize:15,
                  letterSpacing:'0.1em',
                  borderColor: typed === 'RESET' ? '#16a34a' : undefined }} />
              <div style={{ display:'flex', gap:10 }}>
                <button className="btn btn-outline btn-sm"
                  onClick={() => { setPhase('idle'); setTyped(''); setError('') }}>Cancel</button>
                <button className="btn btn-sm" disabled={typed !== 'RESET'} onClick={doReset}
                  style={{ background: typed==='RESET' ? '#dc2626' : '#f1f3f8',
                    color: typed==='RESET' ? 'white' : 'var(--ink-4)',
                    fontWeight:700, padding:'8px 20px' }}>
                  🗑 Confirm Reset
                </button>
              </div>
            </div>
          )}

          {phase === 'resetting' && (
            <div style={{ display:'flex', alignItems:'center', gap:12,
              color:'#9f1239', fontWeight:600 }}>
              <Spinner /> Deleting data…
            </div>
          )}

          {phase === 'done' && result && (
            <div style={{ background:'var(--green-soft)', border:'1px solid #bbf7d0',
              borderRadius:10, padding:20 }}>
              <div style={{ fontWeight:700, color:'var(--green)', fontSize:15, marginBottom:8 }}>
                ✓ Reset complete
              </div>
              <div style={{ fontSize:13, color:'var(--ink-2)', marginBottom:12 }}>{result.message}</div>
              <div style={{ display:'flex', flexWrap:'wrap', gap:8 }}>
                {result.tables_cleared?.map(t => (
                  <span key={t.table} style={{
                    background: t.deleted > 0 ? '#dcfce7' : '#f1f3f8',
                    color: t.deleted > 0 ? '#15803d' : 'var(--ink-4)',
                    padding:'3px 10px', borderRadius:20, fontSize:12, fontWeight:600 }}>
                    {TABLE_LABELS[t.table]||t.table}: {t.deleted}
                  </span>
                ))}
              </div>
              <button className="btn btn-outline btn-sm" style={{ marginTop:14 }}
                onClick={() => { setPhase('idle'); setTyped(''); setResult(null) }}>
                ↩ Back
              </button>
            </div>
          )}
        </div>

        {/* Import Hub reminder */}
        <div style={{ background:'var(--blue-soft)', border:'1px solid #bfdbfe', borderRadius:12,
          padding:'14px 18px', marginTop:20, display:'flex', gap:12, alignItems:'flex-start' }}>
          <span style={{ fontSize:20 }}>📥</span>
          <div>
            <div style={{ fontWeight:600, fontSize:13.5, color:'#1d4ed8', marginBottom:3 }}>
              After reset — use Import Hub to populate data
            </div>
            <div style={{ fontSize:13, color:'#1e40af' }}>
              Upload Excel files for Locations, Vendors, HK Catalog, Items and Consumption Norms via Import Hub.
            </div>
          </div>
        </div>

      </div>


    </>
  )
}
