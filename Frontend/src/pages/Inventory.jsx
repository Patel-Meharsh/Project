import { useState } from 'react'
import { inventoryApi, locationApi, itemApi, grnApi } from '../lib/api'
import { fmtCurrency, fmtNum } from '../lib/utils'
import { StatusBadge, Spinner, SearchInput } from '../components/UI'
import Header from '../components/Header'
import { useAuth } from '../lib/AuthContext'
import { canDo } from '../lib/auth'
import useDataFetch from '../lib/useDataFetch'
import { useToast } from '../components/Toast'

// ── View toggle pill ──────────────────────────────────────────────────────────
function ViewToggle({ view, onChange }) {
  const btn = (v, label) => (
    <button
      onClick={() => onChange(v)}
      style={{
        padding: '5px 16px', fontSize: 13, fontWeight: 500, cursor: 'pointer',
        border: 'none', borderRadius: 6,
        background: view === v ? '#0d0f1a' : 'transparent',
        color:      view === v ? '#fff'    : '#64748b',
        transition: 'all 0.15s',
      }}
    >{label}</button>
  )
  return (
    <div style={{ display:'inline-flex', background:'#f1f3f8', borderRadius:8, padding:3, gap:2 }}>
      {btn('store', 'Store Stock')}
      {btn('consumption', 'Consumption')}
    </div>
  )
}

export default function Inventory() {
  const { user } = useAuth()
  const isAdmin = canDo(user?.role, 'admin')

  const toast = useToast()

  // ── Data ──────────────────────────────────────────────────────────────────
  const { data: fetchResult, loading, refetch } = useDataFetch(() =>
    Promise.all([
      inventoryApi.getAll(),
      inventoryApi.getConsumption(),
      locationApi.getAll(),
      itemApi.getAll(),
    ]).catch(err => { toast.error('Failed to load inventory data'); return [[], [], [], []] })
  )
  const [inv, consumption, locs, allItemsRaw] = fetchResult || [[], [], [], []]
  const allItems = Array.isArray(allItemsRaw) ? allItemsRaw : []

  // ── UI state ──────────────────────────────────────────────────────────────
  const [view,       setView]       = useState('store')  // 'store' | 'consumption'
  const [search,     setSearch]     = useState('')
  const [locFilter,  setLocFilter]  = useState('All')
  const [catFilter,  setCatFilter]  = useState('All')
  const [sortConfig, setSortConfig] = useState({ key: 'item_code', direction: 'asc' })

  // ── Opening balance editor (store view only) ──────────────────────────────
  const [openingMode,     setOpeningMode]     = useState(false)
  const [editingOpenings, setEditingOpenings] = useState({})
  const [savingId,        setSavingId]        = useState(null)
  const [creatingCode,    setCreatingCode]    = useState(null)
  const [confirmResetId,  setConfirmResetId]  = useState(null)

  const toggleSort = (key) => setSortConfig(prev => ({ key, direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc' }))
  const sortArrow  = (key) => sortConfig.key === key ? (sortConfig.direction === 'asc' ? ' ↑' : ' ↓') : ''

  const reload = () => refetch()

  // Reset filters when switching views
  const switchView = (v) => {
    setView(v)
    setSearch('')
    setLocFilter('All')
    setCatFilter('All')
    if (v !== 'store') { setOpeningMode(false); setEditingOpenings({}) }
  }

  // ── Derived: store view ───────────────────────────────────────────────────
  const storeCategories = ['All', ...new Set(inv.map(i => i.category).filter(Boolean))]
  const storeLocs       = ['All', ...new Set(inv.map(i => i.location_code).filter(Boolean))]

  const storeFiltered = inv.filter(i => {
    const q  = search.toLowerCase()
    const ms = !search ||
      (i.item_code||'').toLowerCase().includes(q) ||
      (i.item_name||'').toLowerCase().includes(q) ||
      (i.category||'').toLowerCase().includes(q) ||
      (i.location_code||'').toLowerCase().includes(q)
    const ml = locFilter === 'All' || i.location_code === locFilter
    const mc = catFilter === 'All' || i.category === catFilter
    return ms && ml && mc
  })

  // ── Derived: consumption view ─────────────────────────────────────────────
  const consumptionCategories = ['All', ...new Set(consumption.map(i => i.category).filter(Boolean))]
  const consumptionLocs       = ['All', ...new Set(consumption.map(i => i.location_code).filter(Boolean))]

  const consumptionFiltered = consumption.filter(i => {
    const q  = search.toLowerCase()
    const ms = !search ||
      (i.item_code||'').toLowerCase().includes(q) ||
      (i.item_name||'').toLowerCase().includes(q) ||
      (i.category||'').toLowerCase().includes(q) ||
      (i.location_code||'').toLowerCase().includes(q)
    const ml = locFilter === 'All' || i.location_code === locFilter
    const mc = catFilter === 'All' || i.category === catFilter
    return ms && ml && mc
  })

  // ── Unified sort ──────────────────────────────────────────────────────────
  const applySort = (rows) => [...rows].sort((a, b) => {
    if (!sortConfig.key) return 0
    const mul = sortConfig.direction === 'asc' ? 1 : -1
    const av  = a[sortConfig.key], bv = b[sortConfig.key]
    if (typeof av === 'number' || (av != null && !isNaN(Number(av)))) return (Number(av||0) - Number(bv||0)) * mul
    return String(av||'').localeCompare(String(bv||''), undefined, { numeric: true, sensitivity: 'base' }) * mul
  })

  const sortedStore       = applySort(storeFiltered)
  const sortedConsumption = applySort(consumptionFiltered)

  // ── KPIs ──────────────────────────────────────────────────────────────────
  const totalStoreValue = inv.reduce((s, i) => s + (i.stock_value || 0), 0)
  const belowROL        = inv.filter(i => i.status === 'Below ROL').length
  const totalConsumed   = consumption.reduce((s, i) => s + (i.consumed_qty   || 0), 0)
  const consumedValue   = consumption.reduce((s, i) => s + (i.consumed_value || 0), 0)
  const uniqueSites     = new Set(consumption.map(i => i.location_code)).size

  // ── Opening balance helpers ───────────────────────────────────────────────
  const storeCHCodes  = new Set(inv.filter(i => i.location_code === 'STORE-CH').map(i => i.item_code))
  const missingStoreCH = allItems.filter(it => it.status === 'Active' && !storeCHCodes.has(it.code))

  const confirmOpening = async (row) => {
    const raw = editingOpenings[row.id]
    if (raw === undefined) return
    const val = parseFloat(raw)
    if (isNaN(val)) return
    setSavingId(row.id)
    try {
      await inventoryApi.update(row.id, { opening_stock: val })
      await reload()
      setEditingOpenings(prev => { const n = {...prev}; delete n[row.id]; return n })
      toast.success('Opening stock updated')
    } catch (err) { toast.error('Failed to update opening stock')
    } finally { setSavingId(null) }
  }

  const resetRow = async (row) => {
    try {
      await inventoryApi.reset(row.id)
      await reload()
      toast.success('Stock IN & OUT reset to zero')
    } catch (err) { toast.error('Failed to reset row')
    } finally { setConfirmResetId(null) }
  }

  const createAtStoreCH = async (item) => {
    setCreatingCode(item.code)
    try {
      await inventoryApi.create({
        item_code: item.code, location_code: 'STORE-CH',
        vendor_code: item.vendor_code || '', rate: item.rate || 0,
        opening_stock: 0, stock_in: 0, stock_out: 0,
      })
      await reload()
      toast.success(`${item.code} added to STORE-CH`)
    } catch (err) { toast.error('Failed to create inventory row')
    } finally { setCreatingCode(null) }
  }

  if (loading) return <><Header title="Stock Register" /><div className="page-content"><Spinner /></div></>

  // ── Shared filter bar ──────────────────────────────────────────────────────
  const categories = view === 'store' ? storeCategories : consumptionCategories
  const filterLocs = view === 'store' ? storeLocs       : consumptionLocs

  return (
    <>
      <Header title="Stock Register" subtitle="Real-time inventory across all locations" />
      <div className="page-content">

        {/* ── KPIs change by view ── */}
        {view === 'store' ? (
          <div className="kpi-grid" style={{ gridTemplateColumns:'repeat(4,1fr)', marginBottom:20 }}>
            {[
              { l:'Total Items',          v:inv.length,              c:'blue',  ic:'📦' },
              { l:'Stock Value',          v:fmtCurrency(totalStoreValue), c:'green', ic:'💰' },
              { l:'Below Reorder Level',  v:belowROL,                c:'red',   ic:'⚠️' },
              { l:'OK Status',            v:inv.length - belowROL,   c:'teal',  ic:'✅' },
            ].map(k => (
              <div key={k.l} className={`kpi-card ${k.c}`}>
                <div className={`kpi-icon ${k.c}`}>{k.ic}</div>
                <div className="kpi-value">{k.v}</div>
                <div className="kpi-label">{k.l}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="kpi-grid" style={{ gridTemplateColumns:'repeat(4,1fr)', marginBottom:20 }}>
            {[
              { l:'Line Items',           v:consumption.length,      c:'blue',  ic:'📋' },
              { l:'Total Consumed',       v:fmtNum(totalConsumed),   c:'amber', ic:'📤' },
              { l:'Consumed Value',       v:fmtCurrency(consumedValue), c:'red', ic:'💸' },
              { l:'Active Sites',         v:uniqueSites,             c:'teal',  ic:'📍' },
            ].map(k => (
              <div key={k.l} className={`kpi-card ${k.c}`}>
                <div className={`kpi-icon ${k.c}`}>{k.ic}</div>
                <div className="kpi-value">{k.v}</div>
                <div className="kpi-label">{k.l}</div>
              </div>
            ))}
          </div>
        )}

        {openingMode && (
          <div style={{ background:'#fffbeb', border:'1px solid #f59e0b', borderRadius:8, padding:'10px 16px', marginBottom:16, display:'flex', alignItems:'center', gap:10 }}>
            <span style={{ fontSize:16 }}>⚠️</span>
            <span style={{ fontSize:13, color:'#92400e', fontWeight:500 }}>Opening Balance Edit Mode is ON — changes take effect immediately. Click ✓ on each row to save.</span>
          </div>
        )}

        <div className="table-wrap">
          <div className="table-header">
            <div style={{ display:'flex', alignItems:'center', gap:12 }}>
              <ViewToggle view={view} onChange={switchView} />
              <span className="table-title" style={{ fontSize:13, color:'#94a3b8' }}>
                {view === 'store' ? `${sortedStore.length} Items` : `${sortedConsumption.length} Entries`}
              </span>
            </div>
            <div className="filter-bar">
              <SearchInput value={search} onChange={setSearch} placeholder="Search item…" />
              <select className="select input-sm" style={{ width:180 }} value={locFilter} onChange={e => setLocFilter(e.target.value)}>
                <option value="All">All Locations</option>
                {filterLocs.filter(l => l !== 'All').map(l => <option key={l} value={l}>{l}</option>)}
              </select>
              <select className="select input-sm" style={{ width:200 }} value={catFilter} onChange={e => setCatFilter(e.target.value)}>
                {categories.map(c => <option key={c}>{c}</option>)}
              </select>
              {isAdmin && view === 'store' && (
                <button
                  className={`btn ${openingMode ? 'btn-accent' : 'btn-outline'}`}
                  style={{ whiteSpace:'nowrap' }}
                  onClick={() => { setOpeningMode(v => !v); setEditingOpenings({}) }}
                >
                  ⚖ {openingMode ? 'Exit Opening Edit' : 'Set Opening Stock'}
                </button>
              )}
            </div>
          </div>

          {/* ── STORE VIEW table ── */}
          {view === 'store' && (
            <>
              <div style={{ overflowX:'auto' }}>
                <table>
                  <thead><tr>
                    {[
                      { key:'item_code',     label:'Item Code' },
                      { key:'item_name',     label:'Item Name' },
                      { key:'category',      label:'Category' },
                      { key:'location_code', label:'Store' },
                      { key:'opening_stock', label:'Opening',  right:true },
                      { key:'stock_in',      label:'In',       right:true },
                      { key:'stock_out',     label:'Out',      right:true },
                      { key:'last_grn_no',   label:'Source' },
                      { key:'closing_stock', label:'Closing',  right:true },
                      { key:'rol',           label:'ROL',      right:true },
                      { key:'stock_value',   label:'Value',    right:true },
                      { key:'status',        label:'Status' },
                    ].map(h => (
                      <th key={h.key} style={{ textAlign: h.right ? 'right' : undefined, cursor:'pointer', userSelect:'none', whiteSpace:'nowrap' }}
                        onClick={() => toggleSort(h.key)}
                        onMouseEnter={e => e.currentTarget.style.color='#0d0f1a'}
                        onMouseLeave={e => e.currentTarget.style.color=''}
                      >{h.label}{sortArrow(h.key)}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {sortedStore.length === 0 && <tr><td colSpan={12} style={{ textAlign:'center', padding:40, color:'#94a3b8' }}>No items found</td></tr>}
                    {sortedStore.map(i => (
                      <tr key={i.id}>
                        <td><span className="td-code">{i.item_code}</span></td>
                        <td style={{ fontWeight:500 }}>{i.item_name}</td>
                        <td style={{ fontSize:13, color:'#64748b' }}>{i.category}</td>
                        <td>
                          <span className="td-code">{i.location_code}</span>
                          <span style={{ marginLeft:6, fontSize:11, background:'#dcfce7', color:'#16a34a', borderRadius:4, padding:'1px 5px' }}>STORE</span>
                        </td>
                        <td style={{ textAlign:'right', color:'#64748b' }}>
                          {openingMode ? (
                            confirmResetId === i.id ? (
                              <span style={{ display:'inline-flex', gap:4, alignItems:'center', justifyContent:'flex-end' }}>
                                <span style={{ fontSize:12, color:'#dc2626', fontWeight:500, whiteSpace:'nowrap' }}>Reset IN & OUT to 0?</span>
                                <button onClick={() => resetRow(i)}
                                  style={{ padding:'2px 8px', fontSize:12, cursor:'pointer', background:'#dc2626', color:'#fff', border:'none', borderRadius:4, fontWeight:600 }}>Yes</button>
                                <button onClick={() => setConfirmResetId(null)}
                                  style={{ padding:'2px 8px', fontSize:12, cursor:'pointer', background:'#e5e7eb', color:'#374151', border:'none', borderRadius:4 }}>Cancel</button>
                              </span>
                            ) : (
                              <span style={{ display:'inline-flex', alignItems:'center', gap:4, justifyContent:'flex-end' }}>
                                <input type="number"
                                  value={editingOpenings[i.id] !== undefined ? editingOpenings[i.id] : (i.opening_stock ?? '')}
                                  onChange={e => setEditingOpenings(prev => ({...prev, [i.id]: e.target.value}))}
                                  onKeyDown={e => { if (e.key === 'Enter') confirmOpening(i) }}
                                  style={{ width:70, textAlign:'right', padding:'2px 4px', fontSize:13, border:'1px solid #d1d5db', borderRadius:4 }}
                                />
                                <button onClick={() => confirmOpening(i)}
                                  disabled={savingId === i.id || editingOpenings[i.id] === undefined}
                                  style={{ padding:'2px 6px', fontSize:12, cursor:'pointer', border:'none', borderRadius:4,
                                    background: editingOpenings[i.id] !== undefined ? '#16a34a' : '#e5e7eb',
                                    color: editingOpenings[i.id] !== undefined ? '#fff' : '#9ca3af' }}
                                >{savingId === i.id ? '…' : '✓'}</button>
                                <button onClick={() => setConfirmResetId(i.id)} title="Reset IN and OUT to zero"
                                  style={{ padding:'2px 6px', fontSize:12, cursor:'pointer', background:'#fee2e2', color:'#dc2626', border:'none', borderRadius:4, fontWeight:700 }}>⊘</button>
                              </span>
                            )
                          ) : fmtNum(i.opening_stock)}
                        </td>
                        <td style={{ textAlign:'right', color:'#16a34a', fontWeight:500 }}>+{fmtNum(i.stock_in)}</td>
                        <td style={{ textAlign:'right', color:'#dc2626', fontWeight:500 }}>-{fmtNum(i.stock_out)}</td>
                        <td>
                          {i.last_grn_no
                            ? <span className="td-code" style={{ cursor:'pointer' }} title={`GRN: ${i.last_grn_no}`} onClick={() => alert(`Last GRN: ${i.last_grn_no}`)}>{i.last_grn_no}</span>
                            : <span style={{ color:'#94a3b8' }}>—</span>}
                        </td>
                        <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif", fontWeight:600, fontSize:15, color: i.closing_stock < 0 ? '#dc2626' : undefined }}>{fmtNum(i.closing_stock)}</td>
                        <td style={{ textAlign:'right', fontSize:13, color:'#94a3b8' }}>{fmtNum(i.rol)}</td>
                        <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif", fontWeight:600 }}>{fmtCurrency(i.stock_value)}</td>
                        <td><StatusBadge status={i.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div style={{ padding:'12px 20px', borderTop:'1px solid #f1f3f8', display:'flex', justifyContent:'flex-end', alignItems:'center', gap:20 }}>
                <span style={{ fontSize:13, color:'#64748b' }}>Total Stock Value</span>
                <span style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:18, color:'#0d0f1a' }}>{fmtCurrency(sortedStore.reduce((s, i) => s + (i.stock_value||0), 0))}</span>
              </div>
            </>
          )}

          {/* ── CONSUMPTION VIEW table ── */}
          {view === 'consumption' && (
            <>
              <div style={{ overflowX:'auto' }}>
                <table>
                  <thead><tr>
                    {[
                      { key:'item_code',       label:'Item Code' },
                      { key:'item_name',       label:'Item Name' },
                      { key:'category',        label:'Category' },
                      { key:'location_code',   label:'Site' },
                      { key:'consumed_qty',    label:'Consumed Qty',   right:true },
                      { key:'consumed_value',  label:'Consumed Value', right:true },
                    ].map(h => (
                      <th key={h.key} style={{ textAlign: h.right ? 'right' : undefined, cursor:'pointer', userSelect:'none', whiteSpace:'nowrap' }}
                        onClick={() => toggleSort(h.key)}
                        onMouseEnter={e => e.currentTarget.style.color='#0d0f1a'}
                        onMouseLeave={e => e.currentTarget.style.color=''}
                      >{h.label}{sortArrow(h.key)}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {sortedConsumption.length === 0 && <tr><td colSpan={6} style={{ textAlign:'center', padding:40, color:'#94a3b8' }}>No consumption recorded yet</td></tr>}
                    {sortedConsumption.map((i, idx) => (
                      <tr key={`${i.item_code}-${i.location_code}-${idx}`}>
                        <td><span className="td-code">{i.item_code}</span></td>
                        <td style={{ fontWeight:500 }}>{i.item_name}</td>
                        <td style={{ fontSize:13, color:'#64748b' }}>{i.category}</td>
                        <td>
                          <span className="td-code">{i.location_code}</span>
                          <span style={{ marginLeft:6, fontSize:11, background:'#f1f5f9', color:'#64748b', borderRadius:4, padding:'1px 5px' }}>SITE</span>
                        </td>
                        <td style={{ textAlign:'right', color:'#dc2626', fontWeight:500 }}>{fmtNum(i.consumed_qty)}</td>
                        <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif", fontWeight:600 }}>{fmtCurrency(i.consumed_value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div style={{ padding:'12px 20px', borderTop:'1px solid #f1f3f8', display:'flex', justifyContent:'flex-end', alignItems:'center', gap:20 }}>
                <span style={{ fontSize:13, color:'#64748b' }}>Total Consumed Value</span>
                <span style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:18, color:'#0d0f1a' }}>{fmtCurrency(sortedConsumption.reduce((s, i) => s + (i.consumed_value||0), 0))}</span>
              </div>
            </>
          )}
        </div>

        {/* ── Opening balance: missing STORE-CH rows ── */}
        {isAdmin && openingMode && view === 'store' && missingStoreCH.length > 0 && (
          <div className="table-wrap" style={{ marginTop:24 }}>
            <div className="table-header">
              <span className="table-title" style={{ color:'#b45309' }}>Items with no STORE-CH record ({missingStoreCH.length})</span>
            </div>
            <div style={{ overflowX:'auto' }}>
              <table>
                <thead><tr>
                  <th>Item Code</th><th>Item Name</th><th>Category</th><th>UOM</th>
                  <th style={{ textAlign:'right' }}>Rate</th><th></th>
                </tr></thead>
                <tbody>
                  {missingStoreCH.map(it => (
                    <tr key={it.code}>
                      <td><span className="td-code">{it.code}</span></td>
                      <td style={{ fontWeight:500 }}>{it.name}</td>
                      <td style={{ fontSize:13, color:'#64748b' }}>{it.category}</td>
                      <td style={{ fontSize:13, color:'#64748b' }}>{it.uom}</td>
                      <td style={{ textAlign:'right' }}>{fmtCurrency(it.rate)}</td>
                      <td style={{ textAlign:'right' }}>
                        <button className="btn btn-outline" style={{ fontSize:12, padding:'4px 10px' }}
                          disabled={creatingCode === it.code} onClick={() => createAtStoreCH(it)}>
                          {creatingCode === it.code ? '…' : '+ Create at STORE-CH'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
