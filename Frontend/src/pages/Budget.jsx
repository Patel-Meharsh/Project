import { useEffect, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid, Legend, Cell, AreaChart, Area, ReferenceLine
} from 'recharts'
import { budgetCalcApi, normsApi as normApi, locationApi } from '../lib/api'
import { fmtCurrency, CATEGORY_COLORS } from '../lib/utils'
import { Spinner, FormRow, FormGrid } from '../components/UI'
import SlideOver from '../components/SlideOver'
import Tip from '../components/Tooltip'
import Header from '../components/Header'
import { useToast } from '../components/Toast'

const MONTHS = ['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
const BASIS_COLORS = { 'Per Person':'#8b5cf6','Per 1000 SqFt':'#06b6d4','Per Washroom':'#10b981','Per Urinal':'#f59e0b','Per Pantry':'#f97316' }

// ── Sparkline mini-component ──────────────────────────────────────────────────
function Sparkline({ data, color = '#f0a500', height = 40 }) {
  if (!data || data.length < 2) return null
  const clean = data.filter(v => v != null && !isNaN(v) && isFinite(v) && v >= 0)
  if (clean.length < 2) return null
  const max = Math.max(...clean)
  const min = Math.min(...clean)
  const range = max - min || 1
  const w = 80, h = height
  const pts = clean.map((v, i) => [
    (i / (clean.length - 1)) * w,
    h - ((v - min) / range) * (h - 4) - 2
  ])
  const path = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none" style={{ display: 'block' }}>
      <path d={path} fill="none" stroke={color} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={pts[pts.length-1][0]} cy={pts[pts.length-1][1]} r={2.5} fill={color} />
    </svg>
  )
}

// ── Gauge widget ──────────────────────────────────────────────────────────────
function Gauge({ pct, color }) {
  const clamped = Math.min(pct, 150)
  const angle = (clamped / 150) * 180
  const rad = (angle - 90) * (Math.PI / 180)
  const r = 40, cx = 50, cy = 50
  const x = cx + r * Math.cos(rad), y = cy + r * Math.sin(rad)
  const sweep = angle > 0 ? 1 : 0
  const bg = `M${cx-r},${cy} A${r},${r} 0 0 1 ${cx+r},${cy}`
  const fg = `M${cx-r},${cy} A${r},${r} 0 ${angle > 180 ? 1 : 0} 1 ${x.toFixed(2)},${y.toFixed(2)}`
  return (
    <svg width={100} height={56} viewBox="0 0 100 56">
      <path d={bg} fill="none" stroke="#f1f3f8" strokeWidth={8} strokeLinecap="round" />
      {pct > 0 && <path d={fg} fill="none" stroke={color} strokeWidth={8} strokeLinecap="round" />}
      <text x={50} y={52} textAnchor="middle" fontSize={13} fontWeight={700} fill={color}>{pct}%</text>
    </svg>
  )
}

// ── Waterfall row ─────────────────────────────────────────────────────────────
function BudgetWaterfall({ items }) {
  if (!items || items.length === 0) return null
  const total = items.reduce((s, i) => s + i.monthly, 0)
  let cum = 0
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {items.slice(0, 8).map(item => {
        const pct = total > 0 ? (item.monthly / total) * 100 : 0
        const color = CATEGORY_COLORS[item.category] || '#94a3b8'
        cum += item.monthly
        const cumPct = total > 0 ? (cum / total) * 100 : 0
        return (
          <div key={item.item_code} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 120, fontSize: 11, color: '#374151', flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={item.item_name}>{item.item_name}</div>
            <div style={{ flex: 1, height: 14, background: '#f1f3f8', borderRadius: 4, overflow: 'hidden', position: 'relative' }}>
              <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 4, transition: 'width 0.6s cubic-bezier(0.22,1,0.36,1)' }} />
            </div>
            <div style={{ width: 70, textAlign: 'right', fontFamily: "'Fraunces',serif", fontWeight: 600, fontSize: 12 }}>{fmtCurrency(item.monthly)}</div>
            <div style={{ width: 32, textAlign: 'right', fontSize: 10, color: '#94a3b8' }}>{pct.toFixed(0)}%</div>
          </div>
        )
      })}
    </div>
  )
}

export default function Budget({ defaultTab = 'overview' }) {
  const toast = useToast()
  const [tab, setTab]             = useState(defaultTab)
  const [catSummary, setCatSummary] = useState([])
  const [locSummary, setLocSummary] = useState([])
  const [calculated, setCalculated] = useState(null)
  const [vsActual, setVsActual]   = useState(null)
  const [forecast, setForecast]   = useState(null)
  const [norms, setNorms]         = useState([])
  const [locations, setLocations] = useState([])
  const [loading, setLoading]     = useState(true)
  const [selectedMonth, setSelectedMonth] = useState(new Date().getMonth() + 1 || 1)
  const [inflation, setInflation] = useState(6)
  const [normSlide, setNormSlide] = useState(null)
  const [editNorm, setEditNorm]   = useState({})
  const [recalcMsg, setRecalcMsg] = useState('')
  const [monthlyFc, setMonthlyFc] = useState(null)

  const load = async () => {
    setLoading(true)
    try {
      const [cs, ls, calc, nrm, locs] = await Promise.all([
        budgetCalcApi.getCategorySummary().catch(() => []),
        budgetCalcApi.getLocationSummary().catch(() => []),
        budgetCalcApi.getCalculated().catch(() => null),
        normApi.getAll().catch(() => []),
        locationApi.getAll().catch(() => []),
      ])
      setCatSummary(Array.isArray(cs) ? cs : [])
      setLocSummary(Array.isArray(ls) ? ls : [])
      setCalculated(calc || null)
      setNorms(Array.isArray(nrm) ? nrm : [])
      setLocations(Array.isArray(locs) ? locs : [])
    } finally { setLoading(false) }
  }

  const loadVsActual = async (m) => {
    try {
      const d = await budgetCalcApi.getVsActual(m)
      setVsActual(d && d.items ? d : null)
    } catch { setVsActual(null) }
  }

  const loadForecast = async (inf) => {
    try {
      const d = await budgetCalcApi.getForecast(inf).catch(()=>null)
      setForecast(d)
      const mf = await budgetCalcApi.getMonthlyForecast(inf).catch(()=>null)
      setMonthlyFc(mf)
    } catch { setForecast(null); setMonthlyFc(null) }
  }

  useEffect(() => { load() }, [])
  useEffect(() => { if (tab === 'variance') loadVsActual(selectedMonth) }, [tab, selectedMonth])
  useEffect(() => { if (tab === 'forecast') loadForecast(inflation) }, [tab, inflation])

  const recalculate = async () => {
    setRecalcMsg('Recalculating…')
    try {
      await budgetCalcApi.calculate()
      await load()
      setRecalcMsg('✅ Recalculated!')
      toast.success('Budget recalculated')
    } catch { toast.error('Failed to recalculate budget') }
    setTimeout(() => setRecalcMsg(''), 2500)
  }

  const saveNorm = async () => {
    try {
      await normApi.update(editNorm.id, { norm_value: parseFloat(editNorm.norm_value || "0"), rate: parseFloat(editNorm.rate || "0") })
      toast.success('Norm updated')
    } catch { toast.error('Failed to update norm') }
    setNormSlide(null)
    await load()
  }

  if (loading) return <><Header title="Budget & Analytics" /><div className="page-content"><Spinner /></div></>

  const monthly = calculated?.total_monthly ?? 60100
  const quarterly = calculated?.total_quarterly ?? 180000
  const halfYearly = calculated?.total_half_yearly ?? 360000
  const yearly = calculated?.total_yearly ?? 720000

  return (
    <>
      <Header
        title="Budget & Analytics"
        subtitle={`₹${fmtCurrency(monthly)}/mo · ₹${fmtCurrency(yearly)}/yr · ${(calculated?.items||[]).length} items`}
        actions={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {recalcMsg && <span style={{ fontSize: 13, color: '#16a34a', fontWeight: 500 }}>{recalcMsg}</span>}
            <button className="btn btn-outline btn-sm" onClick={recalculate}>🔄 Recalculate</button>
          </div>
        }
      />
      <div className="page-content">

        {/* ── Hero KPI strip ─────────────────────────────────────────── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 14, marginBottom: 24 }}>
          {[
            { l: 'Monthly Budget', v: fmtCurrency(monthly),       sub: 'Current month', c: '#3b82f6',  ic: '📅', sparkData: catSummary.map(c => c.monthly) },
            { l: 'Quarterly',      v: fmtCurrency(quarterly),   sub: 'Approved quarterly budget',   c: '#06b6d4',  ic: '📆', sparkData: null },
            { l: 'Half-Yearly',    v: fmtCurrency(halfYearly),   sub: 'Approved half-year budget',   c: '#8b5cf6',  ic: '🗓',  sparkData: null },
            { l: 'Annual Budget',  v: fmtCurrency(yearly),        sub: `${(calculated?.items||[]).length} line items`, c: '#16a34a', ic: '📊', sparkData: catSummary.map(c => c.yearly) },
            { l: `Next Year (+${inflation}%)`, v: fmtCurrency(forecast?.next_year ?? yearly * (1 + inflation/100)), sub: `At ${inflation}% inflation`, c: '#f59e0b', ic: '📈', sparkData: null },
          ].map(k => (
            <div key={k.l} style={{
              background: 'white', borderRadius: 16, padding: 18, border: '1px solid #edf0f7',
              transition: 'all 0.2s cubic-bezier(0.34,1.56,0.64,1)', cursor: 'default',
              position: 'relative', overflow: 'hidden'
            }}
              onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-3px)'; e.currentTarget.style.boxShadow = `0 8px 24px ${k.c}22` }}
              onMouseLeave={e => { e.currentTarget.style.transform = ''; e.currentTarget.style.boxShadow = '' }}
            >
              <div style={{ position: 'absolute', top: 14, right: 14, fontSize: 18, opacity: 0.3 }}>{k.ic}</div>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>{k.l}</div>
              <div style={{ fontFamily: "'Fraunces',serif", fontWeight: 800, fontSize: 22, color: k.c, lineHeight: 1.1, marginBottom: 4 }}>{k.v}</div>
              <div style={{ fontSize: 11, color: '#94a3b8' }}>{k.sub}</div>
              {k.sparkData && <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 44, opacity: 0.25, overflow: 'hidden' }}><Sparkline data={k.sparkData} color={k.c} height={44} /></div>}
            </div>
          ))}
        </div>

        {/* ── Tabs ────────────────────────────────────────────────────── */}
        <div className="tabs-line">
          {[['overview','📊 Overview'],['calculator','🧮 Calculator'],['variance','⚖️ vs Actual'],['norms','📐 Norms'],['forecast','🔮 Forecast']].map(([k, l]) => (
            <button key={k} className={`tab-line ${tab === k ? 'active' : ''}`} onClick={() => setTab(k)}>{l}</button>
          ))}
        </div>

        {/* ══ OVERVIEW ════════════════════════════════════════════════ */}
        {tab === 'overview' && (
          <>
            <div className="chart-grid" style={{ marginBottom: 20 }}>
              <div className="panel">
                <div className="panel-header">
                  <div><div className="panel-title">Category-wise Monthly Budget</div><div className="panel-sub">From consumption norms × location fixtures</div></div>
                </div>
                <div className="panel-body" style={{ height: 260 }}>
                  {catSummary.filter(c => c.monthly > 0).length === 0 ? (
                    <div style={{ display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', height:'100%', gap:8, color:'var(--ink-4)' }}>
                    <span style={{ fontSize:32 }}>📊</span>
                    <span style={{ fontWeight:600, fontSize:13.5, color:'var(--ink-3)' }}>No budget data yet</span>
                    <span style={{ fontSize:12.5, textAlign:'center', maxWidth:260 }}>Add consumption norms and locations, then click Recalculate</span>
                  </div>
                  ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={catSummary.filter(c => c.monthly > 0)} layout="vertical" barSize={14}>
                      <XAxis type="number" tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} tickFormatter={v => `₹${(v/1000).toFixed(0)}k`} />
                      <YAxis type="category" dataKey="category" tick={{ fontSize: 11, fill: '#374151' }} axisLine={false} tickLine={false} width={148} />
                      <Tooltip formatter={v => [fmtCurrency(v), 'Monthly']} contentStyle={{ borderRadius: 10, border: '1px solid #edf0f7', fontSize: 12 }} />
                      <Bar dataKey="monthly" radius={[0,6,6,0]}>
                        {catSummary.map((c, i) => <Cell key={i} fill={CATEGORY_COLORS[c.category] || '#94a3b8'} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                  )}
                </div>
              </div>

              <div className="panel">
                <div className="panel-header"><div className="panel-title">Budget Split</div><div style={{ fontSize: 12, color: '#94a3b8' }}>{fmtCurrency(monthly)}/month total</div></div>
                <div className="panel-body">
                  {catSummary.filter(c => c.monthly > 0).length === 0 ? (
                    <div style={{ textAlign:'center', padding:'40px 16px', color:'var(--ink-4)' }}>
                      <div style={{ fontSize:13 }}>Budget split will appear once norms are configured</div>
                    </div>
                  ) : catSummary.filter(c => c.monthly > 0).map(c => (
                    <div key={c.category} style={{ marginBottom: 12 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, marginBottom: 5 }}>
                        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ width: 8, height: 8, borderRadius: '50%', background: CATEGORY_COLORS[c.category] || '#94a3b8', flexShrink: 0 }} />
                          {c.category}
                        </span>
                        <span>
                          <span style={{ fontFamily: "'Fraunces',serif", fontWeight: 600, fontSize: 13 }}>{fmtCurrency(c.monthly)}</span>
                          <span style={{ fontSize: 10, color: '#94a3b8', marginLeft: 4 }}>{c.pct}%</span>
                        </span>
                      </div>
                      <div className="progress-bar">
                        <div className="progress-fill" style={{ width: `${c.pct}%`, background: CATEGORY_COLORS[c.category] || '#94a3b8' }} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Location spend */}
            <div className="panel" style={{ marginBottom: 20 }}>
              <div className="panel-header"><div><div className="panel-title">Monthly Budget by Location</div><div className="panel-sub">Headcount, area & fixtures per site</div></div></div>
              <div className="panel-body" style={{ height: 220 }}>
                {locSummary.length === 0 ? (
                  <div style={{ display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', height:'100%', gap:8, color:'var(--ink-4)' }}>
                  <span style={{ fontSize:32 }}>🏢</span>
                  <span style={{ fontWeight:600, fontSize:13.5, color:'var(--ink-3)' }}>No location data yet</span>
                  <span style={{ fontSize:12.5 }}>Add locations with headcount and fixture data</span>
                </div>
                ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={locSummary} barSize={22}>
                    <XAxis dataKey="location" tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} tickFormatter={v => `₹${(v/1000).toFixed(0)}k`} />
                    <Tooltip formatter={(v, n, p) => [fmtCurrency(v), p.payload.name]} contentStyle={{ borderRadius: 10, border: '1px solid #edf0f7', fontSize: 12 }} />
                    <Bar dataKey="monthly" fill="#f0a500" radius={[5,5,0,0]} />
                  </BarChart>
                </ResponsiveContainer>
                )}
              </div>
            </div>

            {/* Top items waterfall */}
            <div className="panel" style={{ marginBottom: 20 }}>
              <div className="panel-header"><div className="panel-title">Top Items by Monthly Cost</div></div>
              <div className="panel-body">
                <BudgetWaterfall items={[...(calculated?.items||[])].sort((a,b) => b.total_value - a.total_value)} />
              </div>
            </div>

            <div className="table-wrap">
              <table>
                <thead><tr>
                  <th>Location</th><th style={{ textAlign:'right' }}>Area (sqft)</th><th style={{ textAlign:'right' }}>People</th>
                  <th style={{ textAlign:'right' }}>Monthly ₹</th><th style={{ textAlign:'right' }}>Quarterly ₹</th>
                  <th style={{ textAlign:'right' }}>Yearly ₹</th><th style={{ textAlign:'right' }}>₹/person/mo</th>
                </tr></thead>
                <tbody>
                  {locSummary.map(l => (
                    <tr key={l.location}>
                      <td><div style={{ fontWeight: 500 }}>{l.name}</div><span className="td-code">{l.location}</span></td>
                      <td style={{ textAlign:'right', color:'#64748b' }}>{l.area?.toLocaleString()}</td>
                      <td style={{ textAlign:'right' }}>{l.headcount}</td>
                      <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif", fontWeight:600 }}>{fmtCurrency(l.monthly)}</td>
                      <td style={{ textAlign:'right' }}>{fmtCurrency(l.quarterly)}</td>
                      <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif", fontWeight:600, color:'#16a34a' }}>{fmtCurrency(l.yearly)}</td>
                      <td style={{ textAlign:'right', fontSize:13, color:'#64748b' }}>{l.headcount ? fmtCurrency(Math.round(l.monthly/l.headcount)) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {/* ══ CALCULATOR ═══════════════════════════════════════════════ */}
        {tab === 'calculator' && (
          <>
            <div className="alert-strip info" style={{ marginBottom: 16 }}>
              🧮 <strong>How it works:</strong> Qty = Location Factor (headcount / area / fixtures) × Consumption Norm. Value = Qty × Item Master rate. Edit norms in the Norms tab, then Recalculate.
            </div>
            <div className="table-wrap">
              <div className="table-header"><span className="table-title">{(calculated?.items||[]).length} Items · Monthly Budget by Location</span></div>
              <div style={{ overflowX: 'auto' }}>
                <table>
                  <thead><tr>
                    <th style={{ minWidth: 160 }}>Item</th><th>Category</th><th>Basis</th>
                    <th style={{ textAlign:'right' }}>Norm</th><th style={{ textAlign:'right' }}>Rate</th>
                    {locations.slice(0, 6).map(l => <th key={l.code} style={{ textAlign:'right' }}>{l.code}</th>)}
                    <th style={{ textAlign:'right' }}>Total Qty</th><th style={{ textAlign:'right' }}>Monthly ₹</th>
                  </tr></thead>
                  <tbody>
                    {(calculated?.items||[]).map(row => (
                      <tr key={row.item_code}>
                        <td><div style={{ fontWeight:500, fontSize:13 }}>{row.item_name}</div><span className="td-code">{row.item_code}</span></td>
                        <td style={{ fontSize:12 }}><CategoryDot category={row.category} /></td>
                        <td><span className="norm-badge" style={{ background: (BASIS_COLORS[row.basis]||'#94a3b8')+'22', color: BASIS_COLORS[row.basis]||'#64748b', fontSize:11 }}>{row.basis}</span></td>
                        <td style={{ textAlign:'right', fontSize:13 }}>{row.norm_value} {row.norm_unit}</td>
                        <td style={{ textAlign:'right', fontSize:13 }}>{fmtCurrency(row.rate)}</td>
                        {locations.slice(0,6).map(l => (
                          <td key={l.code} style={{ textAlign:'right', fontSize:13, color:'#64748b' }}>{row.locations?.[l.code]?.qty||0}</td>
                        ))}
                        <td style={{ textAlign:'right', fontWeight:600 }}>{row.total_qty}</td>
                        <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif", fontWeight:700 }}>{fmtCurrency(row.total_value)}</td>
                      </tr>
                    ))}
                    <tr style={{ borderTop:'2px solid #0d0f1a' }}>
                      <td colSpan={7+Math.min(6,locations.length)} style={{ textAlign:'right', fontWeight:700, fontSize:14, paddingRight:16 }}>Norm-calculated monthly total</td>
                      <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif", fontWeight:800, fontSize:18, color:'#0d0f1a' }}>{fmtCurrency(calculated?.norm_calculated_monthly ?? calculated?.total_monthly)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}

        {/* ══ BUDGET VS ACTUAL ════════════════════════════════════════ */}
        {tab === 'variance' && vsActual === null && (
          <div className="panel" style={{ textAlign:'center', padding:'56px 24px', color:'var(--ink-4)' }}>
            <div style={{ fontSize:32, marginBottom:12 }}>⚖️</div>
            <div style={{ fontWeight:600, fontSize:14, color:'var(--ink-3)', marginBottom:6 }}>No variance data for this month</div>
            <div style={{ fontSize:13 }}>Record issuances against budgeted items to see actual vs budget comparison</div>
          </div>
        )}
        {tab === 'variance' && vsActual !== null && (
          <>
            {/* Month picker */}
            <div style={{ display:'flex', alignItems:'center', gap:14, marginBottom:20, background:'white', padding:'14px 20px', borderRadius:12, border:'1px solid #edf0f7' }}>
              <span style={{ fontSize:13, fontWeight:600, color:'#374151', flexShrink:0 }}>Select Month:</span>
              <div style={{ display:'flex', gap:5, flexWrap:'wrap' }}>
                {MONTHS.slice(1).map((m, i) => (
                  <button key={i+1} onClick={() => setSelectedMonth(i+1)} className="btn btn-sm"
                    style={{ background: selectedMonth===i+1?'#0d0f1a':'white', color: selectedMonth===i+1?'white':'#374151', border:'1px solid #dde1ec', minWidth:42, transition:'all 0.15s' }}>{m}</button>
                ))}
              </div>
            </div>

            {!vsActual ? <Spinner /> : (() => {
              const util = (vsActual?.utilization_pct||0)
              const gaugeColor = util > 100 ? '#dc2626' : util > 85 ? '#f59e0b' : '#16a34a'
              return (
                <>
                  {/* ── 4 KPI cards + Gauge ── */}
                  <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr) 180px', gap:14, marginBottom:20 }}>
                    {[
                      { l:`Budget — ${MONTHS[selectedMonth]}`, v:fmtCurrency((vsActual?.budget_total||0)), c:'#3b82f6', sub:'This month target' },
                      { l:'Actual Spend', v:fmtCurrency((vsActual?.actual_total||0)), c:(vsActual?.actual_total||0)>(vsActual?.budget_total||0)?'#dc2626':'#16a34a', sub:(vsActual?.actual_total||0)>(vsActual?.budget_total||0)?'Over budget':'Within budget' },
                      { l:'Variance', v:((vsActual?.variance_total||0)>=0?'+':'')+fmtCurrency((vsActual?.variance_total||0)), c:(vsActual?.variance_total||0)>=0?'#16a34a':'#dc2626', sub:(vsActual?.variance_total||0)>=0?'Saved':'Overspent' },
                      { l:'Items Over Budget', v:(vsActual?.items||[]).filter(i=>i.status==='Over Budget').length, c:'#f59e0b', sub:'Needs attention' },
                    ].map(k => (
                      <div key={k.l} style={{ background:'white', borderRadius:16, padding:18, border:'1px solid #edf0f7' }}>
                        <div style={{ fontSize:11, fontWeight:600, color:'#94a3b8', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:6 }}>{k.l}</div>
                        <div style={{ fontFamily:"'Fraunces',serif", fontWeight:800, fontSize:22, color:k.c, lineHeight:1.1, marginBottom:4 }}>{k.v}</div>
                        <div style={{ fontSize:11, color:'#94a3b8' }}>{k.sub}</div>
                      </div>
                    ))}
                    {/* Gauge card */}
                    <div style={{ background:'white', borderRadius:16, padding:16, border:'1px solid #edf0f7', display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center' }}>
                      <Gauge pct={util} color={gaugeColor} />
                      <div style={{ fontSize:11, fontWeight:600, color:'#64748b', textTransform:'uppercase', letterSpacing:'0.06em', marginTop:4 }}>Utilization</div>
                    </div>
                  </div>

                  {/* Full progress bar */}
                  <div style={{ background:'white', borderRadius:12, padding:'16px 20px', border:'1px solid #edf0f7', marginBottom:20 }}>
                    <div style={{ display:'flex', justifyContent:'space-between', fontSize:12, marginBottom:8 }}>
                      <span style={{ color:'#64748b' }}>Budget utilization — {MONTHS[selectedMonth]}</span>
                      <span style={{ fontWeight:700, color:gaugeColor }}>{util}% used</span>
                    </div>
                    <div style={{ height:10, background:'#f1f3f8', borderRadius:99, overflow:'hidden' }}>
                      <div style={{ height:'100%', width:`${Math.min(util,100)}%`, background:gaugeColor, borderRadius:99, transition:'width 0.8s cubic-bezier(0.22,1,0.36,1)' }} />
                    </div>
                    <div style={{ display:'flex', justifyContent:'space-between', fontSize:11, color:'#94a3b8', marginTop:6 }}>
                      <span>₹0</span><span>{fmtCurrency((vsActual?.budget_total||0))}</span>
                    </div>
                  </div>

                  {/* Bar chart */}
                  <div className="panel" style={{ marginBottom:20 }}>
                    <div className="panel-header"><div className="panel-title">Budget vs Actual — {MONTHS[selectedMonth]}</div></div>
                    <div className="panel-body" style={{ height:220 }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={(vsActual?.items||[]).filter(i=>i.budget_value>0).slice(0,12)} barGap={2} barSize={12}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#f1f3f8" vertical={false} />
                          <XAxis dataKey="item_code" tick={{ fontSize:10, fill:'#94a3b8' }} axisLine={false} tickLine={false} />
                          <YAxis tick={{ fontSize:10, fill:'#94a3b8' }} axisLine={false} tickLine={false} tickFormatter={v=>`₹${(v/1000).toFixed(0)}k`} />
                          <Tooltip formatter={v=>[fmtCurrency(v)]} contentStyle={{ borderRadius:10, border:'1px solid #edf0f7', fontSize:12 }} />
                          <Legend />
                          <Bar dataKey="budget_value" name="Budget" fill="#e2e8f0" radius={[4,4,0,0]} />
                          <Bar dataKey="actual_value" name="Actual" fill="#0d0f1a" radius={[4,4,0,0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>

                  <div className="table-wrap">
                    <table>
                      <thead><tr>
                        <th>Item</th><th>Category</th><th>UOM</th>
                        <th style={{ textAlign:'right' }}>Budget Qty</th><th style={{ textAlign:'right' }}>Actual Qty</th>
                        <th style={{ textAlign:'right' }}>Budget ₹</th><th style={{ textAlign:'right' }}>Actual ₹</th>
                        <th style={{ textAlign:'right' }}>Variance ₹</th><th>Utilization</th><th>Status</th>
                      </tr></thead>
                      <tbody>
                        {(vsActual?.items||[]).map(v => (
                          <tr key={v.item_code}>
                            <td><div style={{ fontWeight:500, fontSize:13 }}>{v.item_name}</div><span className="td-code">{v.item_code}</span></td>
                            <td style={{ fontSize:12, color:'#64748b' }}>{v.category}</td>
                            <td style={{ fontSize:12 }}>{v.uom}</td>
                            <td style={{ textAlign:'right', fontSize:13 }}>{v.budget_qty}</td>
                            <td style={{ textAlign:'right', fontSize:13, fontWeight:v.actual_qty>0?600:400, color:v.actual_qty>v.budget_qty?'#dc2626':'#374151' }}>{v.actual_qty}</td>
                            <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif" }}>{fmtCurrency(v.budget_value)}</td>
                            <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif" }}>{fmtCurrency(v.actual_value)}</td>
                            <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif", fontWeight:600, color:v.variance_value>=0?'#16a34a':'#dc2626' }}>
                              {v.variance_value>=0?'+':''}{fmtCurrency(v.variance_value)}
                            </td>
                            <td>
                              <div style={{ display:'flex', alignItems:'center', gap:6 }}>
                                <div style={{ width:60, height:6, background:'#f1f3f8', borderRadius:99, overflow:'hidden' }}>
                                  <div style={{ height:'100%', width:`${Math.min(v.utilization_pct,100)}%`, background:v.utilization_pct>100?'#ef4444':'#10b981', borderRadius:99 }} />
                                </div>
                                <span style={{ fontSize:11, fontWeight:500 }}>{v.utilization_pct}%</span>
                              </div>
                            </td>
                            <td>
                              <span className="badge" style={{
                                background:v.status==='Over Budget'?'#fef2f2':v.status==='On Budget'?'#f0fdf4':'#eff6ff',
                                color:v.status==='Over Budget'?'#dc2626':v.status==='On Budget'?'#16a34a':'#3b82f6', fontSize:11
                              }}>{v.status}</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )
            })()}
          </>
        )}

        {/* ══ NORMS ════════════════════════════════════════════════════ */}
        {tab === 'norms' && (
          <>
            <div className="alert-strip info" style={{ marginBottom:16 }}>
              📐 <strong>Consumption Norms</strong> drive the budget calculator. Qty Required = Location Factor × Norm. Click any row to edit.
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr>
                  <th>Item</th><th>Category</th><th>Basis</th>
                  <th style={{ textAlign:'right' }}>Norm Value</th><th>Unit</th>
                  <th style={{ textAlign:'right' }}>Rate ₹</th><th style={{ textAlign:'right' }}>Cost/Unit ₹</th>
                  <th>How it's calculated</th><th></th>
                </tr></thead>
                <tbody>
                  {norms.map(n => (
                    <tr key={n.id} style={{ cursor:'pointer' }} onClick={() => { setEditNorm({...n}); setNormSlide(n) }}>
                      <td><div style={{ fontWeight:500, fontSize:13 }}>{n.item_name}</div><span className="td-code">{n.item_code}</span></td>
                      <td style={{ fontSize:12 }}><CategoryDot category={n.category} /></td>
                      <td><span className="norm-badge" style={{ background:(BASIS_COLORS[n.basis]||'#94a3b8')+'22', color:BASIS_COLORS[n.basis]||'#64748b', fontSize:11 }}>{n.basis}</span></td>
                      <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:16 }}>{n.norm_value}</td>
                      <td style={{ fontSize:12, color:'#64748b' }}>{n.norm_unit}</td>
                      <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif", fontWeight:600 }}>{n.current_rate > 0 ? fmtCurrency(n.current_rate) : <span style={{ color:'#94a3b8' }}>No rate</span>}</td>
                      <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif" }}>{n.current_rate > 0 ? fmtCurrency(n.norm_value * n.current_rate) : '—'}</td>
                      <td style={{ maxWidth:240, fontSize:12, color:'#94a3b8', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }} title={n.remarks}>{n.remarks}</td>
                      <td><button className="btn btn-outline btn-sm row-action" onClick={e => { e.stopPropagation(); setEditNorm({...n}); setNormSlide(n) }}>Edit</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {/* ══ FORECAST ════════════════════════════════════════════════ */}
        {tab === 'forecast' && (
          <>
            {/* Inflation selector */}
            <div style={{ display:'flex', alignItems:'center', gap:16, marginBottom:24, background:'white', padding:'16px 20px', borderRadius:12, border:'1px solid #edf0f7' }}>
              <span style={{ fontSize:14, fontWeight:600, color:'#374151' }}>Inflation Rate:</span>
              <div style={{ display:'flex', gap:6, flexWrap:'wrap' }}>
                {[3,5,6,7,8,10,12].map(p => (
                  <button key={p} onClick={() => { setInflation(p); loadForecast(p) }} className="btn btn-sm"
                    style={{ background:inflation===p?'#0d0f1a':'white', color:inflation===p?'white':'#374151', border:'1px solid #dde1ec', minWidth:44, fontWeight:inflation===p?700:400 }}>{p}%</button>
                ))}
              </div>
              <div style={{ display:'flex', alignItems:'center', gap:6, marginLeft:8 }}>
                <span style={{ fontSize:13, color:'#64748b' }}>Custom:</span>
                <input className="input input-sm" type="number" value={inflation} min={0} max={50} step={0.5}
                  onChange={e => { setInflation(Number(e.target.value)); loadForecast(Number(e.target.value)) }}
                  style={{ width:70 }} />
                <span style={{ fontSize:13, color:'#64748b' }}>%</span>
              </div>
            </div>

            {!forecast ? <Spinner /> : (
              <>
                {/* Period forecast cards */}
                <div style={{ display:'grid', gridTemplateColumns:'repeat(5,1fr)', gap:14, marginBottom:24 }}>
                  {forecast.periods.map(p => (
                    <div key={p.period} className="forecast-card"
                      style={{ background:p.type==='forecast'?'linear-gradient(135deg,#0d0f1a,#1e3a5f)':'white', border:p.type==='current'?'1px solid #edf0f7':'none', color:p.type==='forecast'?'white':'#0d0f1a', borderRadius:16, padding:'20px 18px', overflow:'hidden' }}>
                      <div style={{ fontSize:11, opacity:0.6, textTransform:'uppercase', letterSpacing:'0.1em', marginBottom:8 }}>{p.period}</div>
                      <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:24, lineHeight:1 }}>{fmtCurrency(p.value)}</div>
                      {p.type==='forecast' && <div style={{ fontSize:11, opacity:0.5, marginTop:6 }}>+{inflation}% inflation</div>}
                    </div>
                  ))}
                </div>

                {/* Monthly area chart */}
                {monthlyFc && (
                  <div className="panel" style={{ marginBottom:20 }}>
                    <div className="panel-header">
                      <div><div className="panel-title">Monthly Forecast vs Actual</div><div className="panel-sub">Projected at {inflation}% annual inflation</div></div>
                      <div style={{ display:'flex', gap:16, fontSize:12, color:'#94a3b8' }}>
                        <span>Actual: <strong style={{ color:'#3b82f6' }}>{fmtCurrency(monthlyFc.yearly_actual)}</strong></span>
                        <span>Forecast: <strong style={{ color:'#f0a500' }}>{fmtCurrency(monthlyFc.yearly_forecast)}</strong></span>
                        <span>Delta: <strong style={{ color:'#ef4444' }}>+{fmtCurrency(monthlyFc.yearly_forecast - monthlyFc.yearly_actual)}</strong></span>
                      </div>
                    </div>
                    <div className="panel-body" style={{ height:260 }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={monthlyFc.months} margin={{ top:5, right:10, left:0, bottom:0 }}>
                          <defs>
                            <linearGradient id="gradActual" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.15}/>
                              <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                            </linearGradient>
                            <linearGradient id="gradForecast" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="#f0a500" stopOpacity={0.15}/>
                              <stop offset="95%" stopColor="#f0a500" stopOpacity={0}/>
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" stroke="#f1f3f8" vertical={false} />
                          <XAxis dataKey="label" tick={{ fontSize:11, fill:'#94a3b8' }} axisLine={false} tickLine={false} />
                          <YAxis tick={{ fontSize:10, fill:'#94a3b8' }} axisLine={false} tickLine={false} tickFormatter={v=>`₹${(v/1000).toFixed(0)}k`} />
                          <Tooltip formatter={v=>[fmtCurrency(v)]} contentStyle={{ borderRadius:10, border:'1px solid #edf0f7', fontSize:12 }} />
                          <Legend />
                          <Area type="monotone" dataKey="actual" name="Actual Spend" stroke="#3b82f6" strokeWidth={2} fill="url(#gradActual)" dot={{ r:3, fill:'#3b82f6' }} />
                          <Area type="monotone" dataKey="forecast" name={`Forecast (+${inflation}%)`} stroke="#f0a500" strokeWidth={2} strokeDasharray="5 3" fill="url(#gradForecast)" dot={false} />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>

                    {/* Monthly table */}
                    <div style={{ overflowX:'auto', marginTop:8 }}>
                      <table style={{ width:'100%', borderCollapse:'collapse', fontSize:12.5 }}>
                        <thead><tr style={{ borderBottom:'1px solid #edf0f7' }}>
                          <th style={{ padding:'10px 14px', textAlign:'left', color:'#64748b', fontWeight:600, textTransform:'uppercase', fontSize:11 }}>Row</th>
                          {monthlyFc.months.map(m => (
                            <th key={m.month} style={{ padding:'10px 8px', textAlign:'right', color:m.is_current?'#f0a500':'#64748b', fontWeight:m.is_current?700:600, fontSize:11, textTransform:'uppercase' }}>
                              {m.label}{m.is_current?' ●':''}
                            </th>
                          ))}
                          <th style={{ padding:'10px 14px', textAlign:'right', color:'#64748b', fontWeight:600, fontSize:11 }}>TOTAL</th>
                        </tr></thead>
                        <tbody>
                          <tr style={{ borderBottom:'1px solid #f1f3f8' }}>
                            <td style={{ padding:'10px 14px', fontWeight:600, color:'#3b82f6' }}>Actual</td>
                            {monthlyFc.months.map(m => (
                              <td key={m.month} style={{ padding:'10px 8px', textAlign:'right', fontFamily:"'Fraunces',serif", fontWeight:600, color:m.actual>0?'#0d0f1a':'#d1d5db' }}>
                                {m.actual > 0 ? fmtCurrency(m.actual) : '—'}
                              </td>
                            ))}
                            <td style={{ padding:'10px 14px', textAlign:'right', fontFamily:"'Fraunces',serif", fontWeight:700 }}>{fmtCurrency(monthlyFc.yearly_actual)}</td>
                          </tr>
                          <tr style={{ borderBottom:'1px solid #f1f3f8' }}>
                            <td style={{ padding:'10px 14px', fontWeight:600, color:'#f59e0b' }}>Forecast</td>
                            {monthlyFc.months.map(m => (
                              <td key={m.month} style={{ padding:'10px 8px', textAlign:'right', color:'#f59e0b', fontFamily:"'Fraunces',serif", fontWeight:600 }}>
                                {fmtCurrency(m.forecast)}
                              </td>
                            ))}
                            <td style={{ padding:'10px 14px', textAlign:'right', fontFamily:"'Fraunces',serif", fontWeight:700, color:'#f59e0b' }}>{fmtCurrency(monthlyFc.yearly_forecast)}</td>
                          </tr>
                          <tr style={{ background:'#f8f9fc' }}>
                            <td style={{ padding:'10px 14px', fontWeight:600, color:'#64748b' }}>Δ Delta</td>
                            {monthlyFc.months.map(m => (
                              <td key={m.month} style={{ padding:'10px 8px', textAlign:'right', fontSize:11, fontWeight:600, color:m.actual>0?(m.forecast>m.actual?'#ef4444':'#16a34a'):'#d1d5db' }}>
                                {m.actual > 0 ? (m.forecast > m.actual ? '+' : '') + fmtCurrency(m.forecast - m.actual) : '—'}
                              </td>
                            ))}
                            <td style={{ padding:'10px 14px', textAlign:'right', fontSize:11, fontWeight:700, color:'#ef4444' }}>
                              +{fmtCurrency(monthlyFc.yearly_forecast - monthlyFc.yearly_actual)}
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* Category forecast */}
                <div className="panel" style={{ marginBottom:20 }}>
                  <div className="panel-header"><div><div className="panel-title">Category Forecast</div><div className="panel-sub">Current vs next year at {inflation}% inflation</div></div></div>
                  <div className="panel-body" style={{ height:240 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={forecast.category_forecast.filter(c => c.current_year > 0)} barGap={3} barSize={14}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#f1f3f8" vertical={false} />
                        <XAxis dataKey="category" tick={{ fontSize:10, fill:'#94a3b8' }} axisLine={false} tickLine={false} />
                        <YAxis tick={{ fontSize:10, fill:'#94a3b8' }} axisLine={false} tickLine={false} tickFormatter={v=>`₹${(v/1000).toFixed(0)}k`} />
                        <Tooltip formatter={v=>[fmtCurrency(v)]} contentStyle={{ borderRadius:10, border:'1px solid #edf0f7', fontSize:12 }} />
                        <Legend />
                        <Bar dataKey="current_year" name="Current Year" fill="#e2e8f0" radius={[4,4,0,0]} />
                        <Bar dataKey="next_year" name={`Next Year (+${inflation}%)`} fill="#f0a500" radius={[4,4,0,0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                <div className="table-wrap">
                  <table>
                    <thead><tr>
                      <th>Category</th>
                      <th style={{ textAlign:'right' }}>Current Year ₹</th>
                      <th style={{ textAlign:'right' }}>Next Year ₹ (+{inflation}%)</th>
                      <th style={{ textAlign:'right' }}>Increase ₹</th>
                      <th style={{ width:160 }}>Visual</th>
                    </tr></thead>
                    <tbody>
                      {forecast.category_forecast.filter(c => c.current_year > 0).map(c => (
                        <tr key={c.category}>
                          <td><span style={{ display:'flex', alignItems:'center', gap:8 }}><span style={{ width:8, height:8, borderRadius:'50%', background:CATEGORY_COLORS[c.category]||'#94a3b8' }} />{c.category}</span></td>
                          <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif" }}>{fmtCurrency(c.current_year)}</td>
                          <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif", fontWeight:600 }}>{fmtCurrency(c.next_year)}</td>
                          <td style={{ textAlign:'right', color:'#f59e0b', fontWeight:600 }}>+{fmtCurrency(c.increase)}</td>
                          <td>
                            <div style={{ display:'flex', gap:2, height:14, borderRadius:4, overflow:'hidden' }}>
                              <div style={{ flex:c.current_year, background:CATEGORY_COLORS[c.category]||'#94a3b8', opacity:0.4 }} />
                              <div style={{ flex:c.increase, background:CATEGORY_COLORS[c.category]||'#94a3b8' }} />
                            </div>
                          </td>
                        </tr>
                      ))}
                      <tr style={{ borderTop:'2px solid #0d0f1a', fontWeight:700 }}>
                        <td>Total</td>
                        <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif", fontSize:16 }}>{fmtCurrency(forecast.category_forecast.reduce((s,c)=>s+c.current_year,0))}</td>
                        <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif", fontSize:16, color:'#f59e0b' }}>{fmtCurrency(forecast.category_forecast.reduce((s,c)=>s+c.next_year,0))}</td>
                        <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif", color:'#f59e0b' }}>+{fmtCurrency(forecast.category_forecast.reduce((s,c)=>s+c.increase,0))}</td>
                        <td></td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </>
        )}

        {/* Edit Norm SlideOver */}
        <SlideOver open={!!normSlide} onClose={() => setNormSlide(null)} title="Edit Consumption Norm" subtitle={normSlide?.item_name}
          footer={<><button className="btn btn-outline" onClick={() => setNormSlide(null)}>Cancel</button><button className="btn btn-accent" onClick={async () => { await saveNorm(); await recalculate() }}>Save & Recalculate</button></>}>
          {normSlide && (
            <div>
              <div className="alert-strip info" style={{ marginBottom:16 }}>
                💡 Changing this norm updates the Monthly Budget Calculator across all locations.
              </div>
              <div className="info-grid" style={{ marginBottom:20 }}>
                {[['Item Code',normSlide.item_code],['Category',normSlide.category],['Basis',normSlide.basis],['Unit',normSlide.norm_unit]].map(([l,v]) => (
                  <div key={l} className="info-item"><div className="info-label">{l}</div><div className="info-value">{v}</div></div>
                ))}
              </div>
              <div style={{ background:'#fffbeb', borderRadius:10, padding:16, marginBottom:20, fontSize:13, color:'#92400e', lineHeight:1.6 }}>
                <strong>📐 Calculation logic:</strong><br />{normSlide.remarks}
              </div>
              <FormGrid>
                <FormRow label="Norm Value (qty per basis unit per month)">
                  <input className="input" type="number" step="0.01" value={editNorm.norm_value||''} onChange={e => setEditNorm({...editNorm, norm_value:e.target.value})} />
                </FormRow>
                <FormRow label="Override Rate ₹ (0 = use Item Master)">
                  <input className="input" type="number" step="1" value={editNorm.rate||''} onChange={e => setEditNorm({...editNorm, rate:e.target.value})} />
                </FormRow>
              </FormGrid>
              {parseFloat(editNorm.norm_value || "0") > 0 && normSlide.current_rate > 0 && (
                <div style={{ background:'#f0fdf4', borderRadius:8, padding:14, marginTop:8 }}>
                  <div style={{ fontSize:12, color:'#94a3b8', marginBottom:4 }}>New monthly cost per basis unit</div>
                  <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:22, color:'#16a34a' }}>{fmtCurrency( parseFloat(editNorm.norm_value || "0") * (parseFloat(editNorm.rate || "0") || normSlide.current_rate))}</div>
                </div>
              )}
            </div>
          )}
        </SlideOver>
      </div>
    </>
  )
}

function CategoryDot({ category }) {
  const color = CATEGORY_COLORS[category] || '#94a3b8'
  return <span style={{ display:'inline-flex', alignItems:'center', gap:5, fontSize:12 }}><span style={{ width:7,height:7,borderRadius:'50%',background:color,flexShrink:0 }}/>{category}</span>
}
