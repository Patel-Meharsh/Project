import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend } from 'recharts'
import { dashboardApi, budgetCalcApi } from '../lib/api'
import { fmtCurrency, fmtNum, CATEGORY_COLORS } from '../lib/utils'
import { Spinner } from '../components/UI'
import Header from '../components/Header'
import useDataFetch from '../lib/useDataFetch'
import { useToast } from '../components/Toast'

const MONTHS = ['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

export default function Dashboard() {
  const navigate = useNavigate()
  const toast = useToast()
  const [bvA, setBvA] = useState(null)

  const { data: fetchResult, loading } = useDataFetch(async () => {
    const [s, c, ab] = await Promise.all([
      dashboardApi.kpis().catch(err => { toast.error('Failed to load KPIs'); return {} }),
      dashboardApi.spendByCategory().catch(() => []),
      budgetCalcApi.getApproved().catch(() => null),
    ])
    // Compare this calendar month's spend with the approved monthly budget.
    const currentMonth = new Date().getMonth() + 1
    const bv = await budgetCalcApi.getVsActual(currentMonth, new Date().getFullYear()).catch(() => null)
    setBvA(bv)
    return { kpis: s || {}, cats: Array.isArray(c) ? c : [], annualBudget: Array.isArray(ab?.categories) ? ab.categories : [], approvedBudget: ab }
  })

  const data = fetchResult?.kpis || {}
  const cats = fetchResult?.cats || []
  const annualBudget = fetchResult?.annualBudget || []
  const approvedBudget = fetchResult?.approvedBudget || null

  if (loading) return (
    <>
      <Header title="Dashboard" subtitle="Overview of your operations" />
      <div className="page-content"><Spinner /></div>
    </>
  )

  const spendData = (data.monthly_spend||[]).map(m => ({ name: MONTHS[m.month], value: m.value }))
  const catPieData = cats.map(c => ({ name: c.category, label: c.category, value: Number(c.value || 0) }))

  const reorders = data.reorder_alerts || []

  const totalAnnual = approvedBudget?.yearly ?? 720000
  const categoryAnnualTotal = annualBudget.reduce((sum, c) => sum + (c.yearly || 0), 0)
  const unallocatedAnnual = totalAnnual - categoryAnnualTotal

  const annualData = annualBudget
    .sort((a,b) => (b.yearly || 0) - (a.yearly || 0))
    .map(c => ({
      cat: c.category,
      val: c.yearly || 0,
      pct: c.pct || 0,
      color: CATEGORY_COLORS[c.category] || '#94a3b8'
    }))

  return (
    <>
      <Header title="Dashboard" subtitle="Live operational overview — Gateway Group" />
      <div className="page-content">

        {/* Reorder alert banner */}
        {reorders.length > 0 && (
          <div className="alert-strip danger" style={{ marginBottom:20 }}>
            ⚠️ <strong>{reorders.length} item{reorders.length>1?'s':''} below reorder level:</strong>{' '}
            {reorders.slice(0,3).map(r=><span key={r.code} style={{ background:'#fecaca', borderRadius:4, padding:'1px 6px', margin:'0 3px', fontSize:12 }}>{r.name} ({r.closing} left)</span>)}
            {reorders.length > 3 && <span style={{ fontSize:12, opacity:0.7 }}>+{reorders.length-3} more</span>}
            <button className="btn btn-sm btn-danger" style={{ marginLeft:'auto' }} onClick={()=>navigate('/procurement/pr')}>Raise PR →</button>
          </div>
        )}

        {/* KPI Grid */}
        <div className="kpi-grid" style={{ marginBottom:20 }}>
          <div className="kpi-card amber fade-in" style={{ animationDelay:'0.00s', cursor:'pointer' }} onClick={()=>navigate('/procurement/pr')}>
            <div className="kpi-icon amber">🛒</div>
            <div className="kpi-value">{data.pending_prs}</div>
            <div className="kpi-label">Pending Requisitions</div>
            <div className="kpi-sub" style={{ color:'#f59e0b', fontSize:12, marginTop:6 }}>Tap to review →</div>
          </div>
          <div className="kpi-card blue fade-in" style={{ animationDelay:'0.05s', cursor:'pointer' }} onClick={()=>navigate('/procurement/po')}>
            <div className="kpi-icon blue">📋</div>
            <div className="kpi-value">{data.open_pos}</div>
            <div className="kpi-label">Open Purchase Orders</div>
            <div className="kpi-sub">With vendors</div>
          </div>
          <div className="kpi-card red fade-in" style={{ animationDelay:'0.10s', cursor:'pointer' }} onClick={()=>navigate('/inventory')}>
            <div className="kpi-icon red">⚠️</div>
            <div className="kpi-value">{data.below_rol}</div>
            <div className="kpi-label">Below Reorder Level</div>
            <div className="kpi-sub">Needs restocking</div>
          </div>
          <div className="kpi-card green fade-in" style={{ animationDelay:'0.15s' }}>
            <div className="kpi-icon green">💰</div>
            <div className="kpi-value">{fmtCurrency(data.stock_value)}</div>
            <div className="kpi-label">Current Stock Value</div>
            <div className="kpi-sub">{data.total_items} active items</div>
          </div>
        </div>

        {/* Row 2: Spend trend + Budget vs Actual */}
        <div className="chart-grid" style={{ marginBottom:20 }}>
          <div className="panel fade-in">
            <div className="panel-header">
              <div>
                <div className="panel-title">Monthly Spend Trend</div>
                <div className="panel-sub">Issuance value by month ({new Date().getFullYear()})</div>
              </div>
            </div>
            <div className="panel-body" style={{ height:210 }}>
              {spendData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={spendData} barSize={28}>
                    <XAxis dataKey="name" tick={{ fontSize:12, fill:'#94a3b8' }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize:11, fill:'#94a3b8' }} axisLine={false} tickLine={false} tickFormatter={v=>v===0?'':fmtCurrency(v)} />
                    <Tooltip formatter={v=>[fmtCurrency(v),'Spend']} contentStyle={{ borderRadius:10, border:'1px solid #edf0f7', fontSize:12 }} />
                    <Bar dataKey="value" fill="#0d0f1a" radius={[6,6,0,0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div style={{ display:'flex', alignItems:'center', justifyContent:'center', height:'100%', color:'#94a3b8', fontSize:13 }}>
                  No issuance data yet — start issuing items to see trends
                </div>
              )}
            </div>
          </div>

          {/* Budget vs Actual mini widget */}
          {bvA && (
            <div className="panel fade-in" style={{ cursor:'pointer' }} onClick={()=>navigate('/budget/variance')}>
              <div className="panel-header">
                <div>
                  <div className="panel-title">Budget vs Actual — {MONTHS[bvA.month] || MONTHS[new Date().getMonth()+1]}</div>
                  <div className="panel-sub">Click to see full analysis</div>
                </div>
                <span style={{ fontSize:12, color:'#3b82f6', fontWeight:500 }}>View all →</span>
              </div>
              <div className="panel-body">
                <div style={{ display:'flex', gap:16, marginBottom:16 }}>
                  <div style={{ flex:1, background:'#f8f9fc', borderRadius:10, padding:14, textAlign:'center' }}>
                    <div style={{ fontSize:11, color:'#94a3b8', marginBottom:4 }}>Budget</div>
                    <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:20 }}>{fmtCurrency(bvA.budget_total)}</div>
                  </div>
                  <div style={{ flex:1, background:'#f8f9fc', borderRadius:10, padding:14, textAlign:'center' }}>
                    <div style={{ fontSize:11, color:'#94a3b8', marginBottom:4 }}>Actual</div>
                    <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:20, color: bvA.actual_total > bvA.budget_total ? '#dc2626' : '#16a34a' }}>{fmtCurrency(bvA.actual_total)}</div>
                  </div>
                </div>
                <div style={{ display:'flex', justifyContent:'space-between', fontSize:13, marginBottom:8 }}>
                  <span style={{ color:'#64748b' }}>Utilization</span>
                  <span style={{ fontWeight:600, color: bvA.utilization_pct > 100 ? '#dc2626' : '#16a34a' }}>{isNaN(bvA.utilization_pct) ? 0 : bvA.utilization_pct}%</span>
                </div>
                <div className="progress-bar" style={{ height:8, marginBottom:12 }}>
                  <div className="progress-fill" style={{ width:`${Math.min(isNaN(bvA.utilization_pct)?0:bvA.utilization_pct,100)}%`, background: bvA.utilization_pct > 100 ? '#ef4444' : '#10b981' }} />
                </div>
                <div style={{ fontSize:13, textAlign:'center', padding:'8px 0', background: bvA.variance_total >= 0 ? '#f0fdf4' : '#fef2f2', borderRadius:8, fontWeight:600, color: bvA.variance_total >= 0 ? '#16a34a' : '#dc2626' }}>
                  {bvA.variance_total >= 0 ? `💚 ${fmtCurrency(bvA.variance_total)} saved` : `🔴 ${fmtCurrency(Math.abs(bvA.variance_total))} over budget`}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Row 3: Category spend pie + Reorder table */}
        <div className="chart-grid" style={{ marginBottom:20 }}>
          <div className="panel fade-in">
            <div className="panel-header">
              <div>
                <div className="panel-title">Spend by Category</div>
                <div className="panel-sub">From issuance records</div>
              </div>
            </div>
            <div className="panel-body" style={{ height:230 }}>
              {catPieData.some(d => d.value > 0) ? (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={catPieData} dataKey="value" nameKey="label" cx="50%" cy="50%" outerRadius={65} innerRadius={35}>
                      {catPieData.map((e,i) => <Cell key={i} fill={CATEGORY_COLORS[e.label]||'#94a3b8'} />)}
                    </Pie>
                    <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize:11, paddingTop:8 }} formatter={v=><span style={{ fontSize:11 }}>{v}</span>} />
                    <Tooltip formatter={v=>[fmtCurrency(v),'Spend']} contentStyle={{ borderRadius:10, border:'1px solid #edf0f7', fontSize:12 }} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div style={{ display:'flex', alignItems:'center', justifyContent:'center', height:'100%', color:'#94a3b8', fontSize:13 }}>
                  No spend data available — issue items to see category breakdown
                </div>
              )}
            </div>
          </div>

          <div className="panel fade-in">
            <div className="panel-header">
              <div className="panel-title">Reorder Alerts</div>
              <button className="btn btn-outline btn-sm" onClick={()=>navigate('/inventory')}>View Inventory →</button>
            </div>
            <div className="panel-body" style={{ padding:'8px 0' }}>
            {reorders.length === 0 ? (
              <div style={{ textAlign:'center', padding:32, color:'#94a3b8' }}>
                <div style={{ fontSize:32, marginBottom:8 }}>✅</div>
                <div style={{ fontSize:13 }}>All items above reorder level</div>
              </div>
            ) : (
              <>
                {reorders.slice(0, 6).map(r=>(
                  <div key={r.code} style={{ display:'flex', alignItems:'center', gap:12, padding:'10px 20px', borderBottom:'1px solid #f8f9fc' }}>
                    <div style={{ width:36, height:36, borderRadius:8, background:'#fef2f2', display:'flex', alignItems:'center', justifyContent:'center', fontSize:18, flexShrink:0 }}>⚠️</div>
                    <div style={{ flex:1 }}>
                      <div style={{ fontWeight:500, fontSize:13 }}>{r.name}</div>
                      <div style={{ fontSize:11, color:'#94a3b8' }}>{r.code} · {r.location}</div>
                    </div>
                    <div style={{ textAlign:'right' }}>
                      <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:16, color:'#dc2626' }}>{r.closing}</div>
                      <div style={{ fontSize:10, color:'#94a3b8' }}>ROL: {r.rol}</div>
                    </div>
                  </div>
                ))}

                {reorders.length > 6 && (
                  <div style={{ textAlign:'center', padding:12 }}>
                    <button 
                      className="btn btn-outline btn-sm"
                      onClick={()=>navigate('/inventory')}
                    >
                      View all {reorders.length} items →
                    </button>
                  </div>
                )}
              </>
            )}
            </div>
          </div>
        </div>

        {/* Row 4: Quick nav cards + Annual budget */}
        <div className="chart-grid-3">
          <div className="panel fade-in" style={{ gridColumn:'1/3' }}>
            <div className="panel-header"><div className="panel-title">Quick Actions</div><div className="panel-sub">Jump to any module</div></div>
            <div className="panel-body">
              <div style={{ display:'grid', gridTemplateColumns:'repeat(2,1fr)', gap:10 }}>
                {[
                  { label:'New Purchase Request', sub:'Raise a PR for any item', icon:'🛒', color:'#8b5cf6', bg:'#f5f3ff', path:'/procurement/pr' },
                  { label:'Create Purchase Order', sub:'Convert approved PRs to POs', icon:'📋', color:'#3b82f6', bg:'#eff6ff', path:'/procurement/po' },
                  { label:'Record GRN', sub:'Log incoming deliveries', icon:'📦', color:'#10b981', bg:'#f0fdf4', path:'/procurement/grn' },
                  { label:'Issue Items', sub:'Dispatch to departments', icon:'🔄', color:'#f59e0b', bg:'#fffbeb', path:'/issuance' },
                  { label:'View Vendors', sub:`${data.active_vendors || 0} active vendors`, icon:'🏭', color:'#06b6d4', bg:'#ecfeff', path:'/masters/vendors' },
                  { label:'Budget & Analytics', sub:'Forecasts, variance & norms', icon:'📊', color:'#ec4899', bg:'#fdf2f8', path:'/budget' },
                ].map(card => (
                  <div key={card.label} className="dash-nav-card" onClick={() => navigate(card.path)}>
                    <div className="dash-nav-icon" style={{ background: card.bg, color: card.color }}>{card.icon}</div>
                    <div>
                      <div style={{ fontWeight:600, fontSize:13.5, color:'#0d0f1a', marginBottom:2 }}>{card.label}</div>
                      <div style={{ fontSize:11.5, color:'#94a3b8' }}>{card.sub}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="panel fade-in">
            <div className="panel-header">
              <div>
                <div className="panel-title">Annual Budget</div>
                <div className="panel-sub">{fmtCurrency(categoryAnnualTotal)} allocated · {fmtCurrency(unallocatedAnnual)} unallocated</div>
              </div>
              <button className="btn btn-outline btn-sm" onClick={()=>navigate('/budget')}>Details →</button>
            </div>
            <div className="panel-body">

              {
                annualData.length > 0 ? (
                annualData.map(({cat,val,color,pct})=>(
                <div key={cat} style={{ marginBottom:10 }}>
                  <div style={{ display:'flex', justifyContent:'space-between', fontSize:12, marginBottom:4 }}>
                    <span style={{ color:'#374151' }}>{cat}</span>
                    <span style={{ fontFamily:"'Fraunces',serif", fontWeight:600, fontSize:13 }}>{fmtCurrency(val)}</span>
                  </div>
                  <div className="progress-bar">
                    <div className="progress-fill" style={{ width:`${pct}%`, background:color }} />
                  </div>
                </div>
               ))
              ) : (
                <div style={{ textAlign:'center', padding:20, color:'#94a3b8' }}>
                  No annual budget data available
                </div>
              )}

              <div style={{ marginTop:14, paddingTop:12, borderTop:'1px solid #f1f3f8', display:'flex', justifyContent:'space-between' }}>
                <span style={{ fontSize:12, color:'#64748b' }}>Total Annual</span>
                <span style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:16 }}>{fmtCurrency(totalAnnual)}</span>
              </div>
            </div>
          </div>
        </div>

      </div>
    </>
  )
}
