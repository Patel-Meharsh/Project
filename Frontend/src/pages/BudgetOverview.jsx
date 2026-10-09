import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { budgetCalcApi } from '../lib/api'
import { fmtCurrency, CATEGORY_COLORS } from '../lib/utils'
import { Spinner } from '../components/UI'
import Header from '../components/Header'
import { useNavigate } from 'react-router-dom'
import useDataFetch from '../lib/useDataFetch'
import { useToast } from '../components/Toast'

const MONTH_NAMES = ['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
const currentMonth = new Date().getMonth() + 1

export default function BudgetOverview() {
  const navigate = useNavigate()
  const toast = useToast()

  const { data: fetchResult, loading } = useDataFetch(() =>
    Promise.all([
      budgetCalcApi.getApproved().catch(() => null),
      budgetCalcApi.getLocationSummary().catch(() => []),
      budgetCalcApi.getVsActual(currentMonth).catch(() => null),
    ]).catch(err => { toast.error('Failed to load budget data'); return [null, [], null] })
  )
  const [approved, locs, vsActual] = fetchResult || [null, [], null]
  const cats = approved?.categories || []

  if (loading) return (
    <>
      <Header title="Budget Overview" subtitle="Loading…" />
      <div className="page-content"><Spinner /></div>
    </>
  )

  // ── Derived numbers ───────────────────────────────────────────────────────
  const totalMonthly  = approved?.monthly ?? 60100
  const totalQuarterly = approved?.quarterly ?? 180000
  const totalHalfYearly = approved?.half_yearly ?? 360000
  const totalYearly   = approved?.yearly ?? 720000
  const actualSpend   = vsActual?.actual_total  || 0
  const budgetMonth   = vsActual?.budget_total  || totalMonthly
  const variance      = vsActual?.variance_total ?? (budgetMonth - actualSpend)
  const utilPct       = budgetMonth > 0 ? (actualSpend / budgetMonth) * 100 : 0

  const overBudget    = (vsActual?.items || []).filter(i => i.variance_value < 0)
  const underBudget   = (vsActual?.items || []).filter(i => i.variance_value > 0)
  const onBudget      = (vsActual?.items || []).filter(i => i.variance_value === 0)

  const topLocMax     = Math.max(...locs.map(l => l.monthly || 0), 1)

  const utilColor = utilPct > 100 ? '#ef4444' : utilPct > 80 ? '#f59e0b' : '#10b981'
  const varColor  = variance >= 0 ? '#10b981' : '#ef4444'

  return (
    <>
      <Header
        title="Budget Overview"
        subtitle={`${MONTH_NAMES[currentMonth]} snapshot · ${fmtCurrency(totalYearly)} annual budget · ${locs.length} locations · ${cats.length} categories`}
        actions={
          <div style={{ display:'flex', gap:8 }}>
            <button className="btn btn-outline btn-sm" onClick={() => navigate('/budget/norms')}>📐 Norms</button>
            <button className="btn btn-outline btn-sm" onClick={() => navigate('/budget/variance')}>⚖️ vs Actual</button>
            <button className="btn btn-accent btn-sm"  onClick={() => navigate('/budget/forecast')}>🔮 Forecast</button>
          </div>
        }
      />
      <div className="page-content">

        {/* ── KPI STRIP ──────────────────────────────────────────────── */}
        <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:16, marginBottom:24 }}>
          {[
            { label:'Monthly Budget',    value: fmtCurrency(totalMonthly),  sub:'Approved monthly budget',                  c:'blue',   ic:'📅', path:'/budget/calculator' },
            { label:'Annual Budget',     value: fmtCurrency(totalYearly),   sub:'Approved annual budget',                     c:'teal',   ic:'📊', path:'/budget' },
            { label:`${MONTH_NAMES[currentMonth]} Actual Spend`, value: fmtCurrency(actualSpend), sub:`of ${fmtCurrency(budgetMonth)} budget`, c: actualSpend > budgetMonth ? 'red' : 'green', ic:'💸', path:'/budget/variance' },
            { label:'Budget Utilization', value:`${utilPct.toFixed(1)}%`,   sub: variance >= 0 ? `₹${fmtCurrency(variance)} remaining` : `₹${fmtCurrency(Math.abs(variance))} over`, c: utilPct > 100 ? 'red' : utilPct > 80 ? 'amber' : 'green', ic:'📈', path:'/budget/variance' },
          ].map(k => (
            <div key={k.label} className={`kpi-card ${k.c} fade-in`} style={{ cursor:'pointer' }} onClick={() => navigate(k.path)}>
              <div className={`kpi-icon ${k.c}`}>{k.ic}</div>
              <div className="kpi-value">{k.value}</div>
              <div className="kpi-label">{k.label}</div>
              <div style={{ fontSize:11, color:'#94a3b8', marginTop:4 }}>{k.sub}</div>
            </div>
          ))}
        </div>

        {/* ── ROW 1: Budget Health + Alerts + Month Trend ────────────── */}
        <div style={{ display:'grid', gridTemplateColumns:'1.4fr 1fr 1fr', gap:16, marginBottom:20 }}>

          {/* Budget Health */}
          <div className="panel">
            <div className="panel-header">
              <div><div className="panel-title">Budget Health — {MONTH_NAMES[currentMonth]}</div><div className="panel-sub">Actual spend vs monthly budget</div></div>
            </div>
            <div className="panel-body">
              {/* Big gauge */}
              <div style={{ display:'flex', alignItems:'flex-end', gap:20, marginBottom:20 }}>
                <div>
                  <div style={{ fontSize:11, color:'#94a3b8', marginBottom:4 }}>Utilization</div>
                  <div style={{ fontFamily:"'Fraunces',serif", fontWeight:800, fontSize:42, lineHeight:1, color: utilColor }}>{utilPct.toFixed(0)}<span style={{ fontSize:22 }}>%</span></div>
                </div>
                <div style={{ flex:1 }}>
                  <div className="progress-bar" style={{ height:14, marginBottom:8 }}>
                    <div className="progress-fill" style={{ width:`${utilPct}%`, background: utilColor }} />
                  </div>
                  <div style={{ display:'flex', justifyContent:'space-between', fontSize:11, color:'#94a3b8' }}>
                    <span>₹0</span><span>{fmtCurrency(budgetMonth)}</span>
                  </div>
                </div>
              </div>

              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:10 }}>
                {[
                  ['Budget',  fmtCurrency(budgetMonth),  '#0d0f1a'],
                  ['Actual',  fmtCurrency(actualSpend),  actualSpend > budgetMonth ? '#ef4444' : '#f59e0b'],
                  ['Variance',(variance >= 0 ? '+' : '') + fmtCurrency(variance), varColor],
                ].map(([l,v,col]) => (
                  <div key={l} style={{ background:'#f8f9fc', borderRadius:10, padding:'12px 14px' }}>
                    <div style={{ fontSize:11, color:'#94a3b8', marginBottom:4 }}>{l}</div>
                    <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:16, color:col }}>{v}</div>
                  </div>
                ))}
              </div>

              <div style={{ marginTop:16, paddingTop:14, borderTop:'1px solid #f1f3f8' }}>
                <div style={{ fontSize:12, color:'#64748b', marginBottom:10 }}>12-Month Projection</div>
                <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:8 }}>
                  {[
                    ['Quarter', fmtCurrency(totalQuarterly)],
                    ['Half-Year', fmtCurrency(totalHalfYearly)],
                    ['Full Year', fmtCurrency(totalYearly)],
                  ].map(([l,v]) => (
                    <div key={l} style={{ textAlign:'center', background:'#f8f9fc', borderRadius:8, padding:'8px 6px' }}>
                      <div style={{ fontFamily:"'Fraunces',serif", fontWeight:600, fontSize:13 }}>{v}</div>
                      <div style={{ fontSize:10, color:'#94a3b8', marginTop:2 }}>{l}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Status Breakdown */}
          <div className="panel">
            <div className="panel-header"><div className="panel-title">Item Status</div><div className="panel-sub">{MONTH_NAMES[currentMonth]} Budget vs Actual</div></div>
            <div className="panel-body">
              {/* Big status numbers */}
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:10, marginBottom:16 }}>
                {[
                  { label:'Over Budget', count:overBudget.length,  bg:'#fef2f2', color:'#dc2626', ic:'🔴' },
                  { label:'Under Budget',count:underBudget.length, bg:'#f0fdf4', color:'#16a34a', ic:'💚' },
                ].map(s => (
                  <div key={s.label} style={{ background:s.bg, borderRadius:12, padding:16, textAlign:'center', cursor:'pointer' }} onClick={() => navigate('/budget/variance')}>
                    <div style={{ fontSize:28 }}>{s.ic}</div>
                    <div style={{ fontFamily:"'Fraunces',serif", fontWeight:800, fontSize:32, color:s.color, lineHeight:1.1 }}>{s.count}</div>
                    <div style={{ fontSize:11, color:s.color, marginTop:4, fontWeight:500 }}>{s.label}</div>
                  </div>
                ))}
              </div>
              <div style={{ background:'#f8f9fc', borderRadius:10, padding:'12px 14px', textAlign:'center', cursor:'pointer' }} onClick={() => navigate('/budget/variance')}>
                <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:22, color:'#0d0f1a' }}>{(vsActual?.items||[]).length}</div>
                <div style={{ fontSize:11, color:'#94a3b8', marginTop:2 }}>Total Items Tracked</div>
              </div>

              {/* Mini over-budget list */}
              {overBudget.length > 0 && (
                <div style={{ marginTop:14 }}>
                  <div style={{ fontSize:11, color:'#94a3b8', fontWeight:500, textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:8 }}>Over Budget</div>
                  {overBudget.slice(0,3).map(i => (
                    <div key={i.item_code} style={{ display:'flex', justifyContent:'space-between', alignItems:'center', padding:'6px 0', borderBottom:'1px solid #f8f9fc', fontSize:12 }}>
                      <span style={{ color:'#374151' }}>{i.item_name}</span>
                      <span style={{ color:'#ef4444', fontWeight:600 }}>+{fmtCurrency(Math.abs(i.variance_value))}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Monthly Trend (top 5 by budget value) */}
          <div className="panel">
            <div className="panel-header"><div className="panel-title">Top Items by Budget</div><div className="panel-sub">Monthly allocation</div></div>
            <div className="panel-body" style={{ padding:'14px 18px 18px' }}>
              {(vsActual?.items || []).filter(i => i.budget_value > 0).sort((a,b) => b.budget_value - a.budget_value).slice(0,6).map((item, i) => (
                <div key={item.item_code} style={{ marginBottom:12 }}>
                  <div style={{ display:'flex', justifyContent:'space-between', fontSize:12, marginBottom:4 }}>
                    <span style={{ color:'#374151', flex:1, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', marginRight:8 }}>{item.item_name}</span>
                    <span style={{ fontFamily:"'Fraunces',serif", fontWeight:600, fontSize:13, flexShrink:0 }}>{fmtCurrency(item.budget_value)}</span>
                  </div>
                  <div style={{ position:'relative', height:6, background:'#f1f3f8', borderRadius:99, overflow:'hidden' }}>
                    {/* Budget bar (light) */}
                    <div style={{ position:'absolute', top:0, left:0, height:'100%', width:'100%', background:'#e2e8f0', borderRadius:99 }} />
                    {/* Actual bar */}
                    <div style={{ position:'absolute', top:0, left:0, height:'100%', borderRadius:99, background: item.utilization_pct > 100 ? '#ef4444' : '#0d0f1a', width:`${Math.min(item.utilization_pct || 0, 100)}%` }} />
                  </div>
                  <div style={{ fontSize:10, color:'#94a3b8', marginTop:2 }}>Actual: {fmtCurrency(item.actual_value)} · {item.utilization_pct || 0}% used</div>
                </div>
              ))}
              {(vsActual?.items||[]).length === 0 && (
                <div style={{ textAlign:'center', padding:24, color:'#94a3b8', fontSize:13 }}>No issuance data for {MONTH_NAMES[currentMonth]} yet</div>
              )}
            </div>
          </div>
        </div>

        {/* ── ROW 2: Category bar chart + Category table ─────────────── */}
        <div className="chart-grid" style={{ marginBottom:20 }}>
          <div className="panel">
            <div className="panel-header">
              <div><div className="panel-title">Category Budget — Monthly</div><div className="panel-sub">Calculated from consumption norms × location fixtures</div></div>
              <button className="btn btn-outline btn-sm" onClick={() => navigate('/budget/calculator')}>View Calculator →</button>
            </div>
            <div className="panel-body" style={{ height:240 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={cats.filter(c => c.monthly > 0)} layout="vertical" barSize={16} margin={{ left:12 }}>
                  <XAxis type="number" tick={{ fontSize:11, fill:'#94a3b8' }} axisLine={false} tickLine={false} tickFormatter={v=>`₹${(v/1000).toFixed(0)}k`} />
                  <YAxis type="category" dataKey="category" tick={{ fontSize:11, fill:'#374151' }} axisLine={false} tickLine={false} width={155} />
                  <Tooltip formatter={v=>[fmtCurrency(v),'Monthly']} contentStyle={{ borderRadius:10, border:'1px solid #edf0f7', fontSize:12 }} />
                  <Bar dataKey="monthly" radius={[0,6,6,0]}>
                    {cats.map((c,i) => <Cell key={i} fill={CATEGORY_COLORS[c.category] || '#94a3b8'} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="panel">
            <div className="panel-header"><div className="panel-title">Annual Split</div><div className="panel-sub">₹{fmtCurrency(totalYearly)} total</div></div>
            <div className="panel-body">
              {cats.filter(c => c.yearly > 0).map(c => (
                <div key={c.category} style={{ marginBottom:12 }}>
                  <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:5, fontSize:12.5 }}>
                    <span style={{ display:'flex', alignItems:'center', gap:6 }}>
                      <span style={{ width:8, height:8, borderRadius:'50%', background: CATEGORY_COLORS[c.category]||'#94a3b8', flexShrink:0 }} />
                      {c.category}
                    </span>
                    <span style={{ fontFamily:"'Fraunces',serif", fontWeight:600 }}>
                      {fmtCurrency(c.yearly)}
                      <span style={{ fontFamily:'inherit', fontWeight:400, fontSize:11, color:'#94a3b8', marginLeft:5 }}>{c.pct}%</span>
                    </span>
                  </div>
                  <div className="progress-bar">
                    <div className="progress-fill" style={{ width:`${c.pct}%`, background: CATEGORY_COLORS[c.category]||'#94a3b8' }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── ROW 3: Location bar chart + Location table ─────────────── */}
        <div className="panel" style={{ marginBottom:20 }}>
          <div className="panel-header">
            <div><div className="panel-title">Monthly Budget by Location</div><div className="panel-sub">Derived from headcount, area & fixture counts per site</div></div>
            <button className="btn btn-outline btn-sm" onClick={() => navigate('/locations')}>Manage Locations →</button>
          </div>
          <div style={{ display:'grid', gridTemplateColumns:'1.8fr 1fr', gap:0 }}>
            <div className="panel-body" style={{ height:230, paddingRight:0 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={locs} barSize={22} margin={{ right:20 }}>
                  <XAxis dataKey="location" tick={{ fontSize:11, fill:'#94a3b8' }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize:11, fill:'#94a3b8' }} axisLine={false} tickLine={false} tickFormatter={v=>`₹${(v/1000).toFixed(0)}k`} />
                  <Tooltip formatter={(v,_,p) => [fmtCurrency(v), p.payload.name]} contentStyle={{ borderRadius:10, border:'1px solid #edf0f7', fontSize:12 }} />
                  <Bar dataKey="monthly" fill="#f0a500" radius={[5,5,0,0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div style={{ borderLeft:'1px solid #f1f3f8', padding:'16px 20px', overflowY:'auto', maxHeight:260 }}>
              {locs.map(l => (
                <div key={l.location} style={{ display:'flex', justifyContent:'space-between', alignItems:'center', padding:'8px 0', borderBottom:'1px solid #f8f9fc', fontSize:12.5 }}>
                  <div>
                    <div style={{ fontWeight:500, color:'#0d0f1a' }}>{l.name}</div>
                    <div style={{ fontSize:11, color:'#94a3b8' }}>{l.headcount} ppl · {(l.area||0).toLocaleString()} sqft</div>
                  </div>
                  <div style={{ textAlign:'right' }}>
                    <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700 }}>{fmtCurrency(l.monthly)}</div>
                    <div style={{ fontSize:11, color:'#94a3b8' }}>{fmtCurrency(l.yearly)}/yr</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── ROW 4: Quick actions / navigation cards ─────────────────── */}
        <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:14 }}>
          {[
            { title:'Budget Calculator',  sub:'Norm × location formula',       ic:'🧮', path:'/budget/calculator', bg:'#eff6ff', color:'#1e40af' },
            { title:'Budget vs Actual',   sub:`${MONTH_NAMES[currentMonth]} variance analysis`, ic:'⚖️', path:'/budget/variance',   bg:'#fef9c3', color:'#854d0e' },
            { title:'Consumption Norms',  sub:'Adjust usage benchmarks',        ic:'📐', path:'/budget/norms',     bg:'#f0fdf4', color:'#166534' },
            { title:'Forecasting',        sub:'Inflation-adjusted projections', ic:'🔮', path:'/budget/forecast',  bg:'#fdf4ff', color:'#7e22ce' },
          ].map(c => (
            <div key={c.title} style={{ background:c.bg, borderRadius:14, padding:'18px 20px', cursor:'pointer', border:`1px solid ${c.bg}`, transition:'all 0.15s' }}
              onClick={() => navigate(c.path)}
              onMouseEnter={e => e.currentTarget.style.transform='translateY(-2px)'}
              onMouseLeave={e => e.currentTarget.style.transform='translateY(0)'}>
              <div style={{ fontSize:28, marginBottom:10 }}>{c.ic}</div>
              <div style={{ fontFamily:"'Fraunces',serif", fontWeight:600, fontSize:15, color:c.color, marginBottom:4 }}>{c.title}</div>
              <div style={{ fontSize:12, color:c.color, opacity:0.7 }}>{c.sub}</div>
            </div>
          ))}
        </div>

      </div>
    </>
  )
}
