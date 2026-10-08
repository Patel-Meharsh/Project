import { useState } from 'react'
import DeleteToolbar, { EditModeToggle, SelectTh, SelectTd } from '../components/DeleteToolbar'
import { useDeleteMode } from '../hooks/useDeleteMode'
import { deleteApi } from '../lib/api'
import { hkApi as hkMasterApi, codeApi } from '../lib/api'
import { fmtCurrency } from '../lib/utils'
import { SearchInput, Spinner, CategoryDot, FormRow, FormGrid } from '../components/UI'
import SlideOver from '../components/SlideOver'
import Header from '../components/Header'
import useDataFetch from '../lib/useDataFetch'
import { useToast } from '../components/Toast'

const CATEGORIES = ['Cleaning Chemicals','Washroom Supplies','Cleaning Tools','Waste Management','Pantry','PPE & Safety','Pest Control','Electrical','Equipment','Others']
const UOMS = ['Liter','Kg','Piece','Roll','Pack','Pair','Meter','Box','Can','Jar','Set','Bundle','Case']
const EMPTY = {
  code:'', name:'', category:'Cleaning Chemicals', sub_category:'', uom:'Liter',
  eco_brand:'', eco_price:0, std_brand:'', std_price:0, prem_brand:'', prem_price:0,
  recommended:'Standard', rate:0, gst_pct:18, vendor_code:'', rol:0, max_stock:0, lead_days:7, status:'Active'
}

const num = (v) => Number(v) || 0

// Inline SVG pencil icon — clean, no external dependency
const PencilIcon = () => (
  <svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4l4 4L6 17H2v-4L11 4z"/>
    <path d="M9.5 6.5l4 4"/>
  </svg>
)

// Defined OUTSIDE the component so it is never recreated on re-render (prevents focus loss)
function F({ label, field, type='text', half, readOnly, children, form, setForm }) {
  return (
    <FormRow label={label} half={half}>
      {children || (
        <input className="input" type={type}
          readOnly={readOnly}
          style={readOnly ? { background:'#f8f9fc', color:'#64748b' } : undefined}
          value={form[field] ?? ''}
          onChange={e => !readOnly && setForm({ ...form, [field]: e.target.value })} />
      )}
    </FormRow>
  )
}

export default function HKMaster() {
  const toast = useToast()
  const { data: rawItems, loading, refetch } = useDataFetch(() => hkMasterApi.getAll())
  const items = rawItems || []

  const [search,  setSearch]  = useState('')
  const [catFilter, setCatFilter] = useState('All')
  const [showForm, setShowForm]   = useState(false)
  const [editMode, setEditMode]   = useState(false)
  const [form,     setForm]       = useState(EMPTY)
  const [saving,   setSaving]     = useState(false)
  const [sortConfig, setSortConfig] = useState({ key: null, direction: 'asc' })

  const toggleSort = (key) => setSortConfig(prev => ({ key, direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc' }))
  const sortArrow = (key) => sortConfig.key === key ? (sortConfig.direction === 'asc' ? ' ↑' : ' ↓') : ''

  const cats = ['All', ...new Set(items.map(i => i.category))]
  const filtered = items.filter(i => {
    const ms = !search ||
      i.code.toLowerCase().includes(search.toLowerCase()) ||
      i.name.toLowerCase().includes(search.toLowerCase()) ||
      (i.sub_category||'').toLowerCase().includes(search.toLowerCase()) ||
      (i.std_brand||'').toLowerCase().includes(search.toLowerCase())
    return ms && (catFilter === 'All' || i.category === catFilter)
  })

  const sorted = [...filtered].sort((a, b) => {
    if (!sortConfig.key) return 0
    const av = a[sortConfig.key], bv = b[sortConfig.key]
    const mul = sortConfig.direction === 'asc' ? 1 : -1
    if (typeof av === 'number' || (av != null && !isNaN(av))) return (Number(av||0) - Number(bv||0)) * mul
    return String(av||'').localeCompare(String(bv||'')) * mul
  })

  const openCreate = async () => {
    const code = await codeApi.next('item')
    setForm({ ...EMPTY, code })
    setEditMode(false); setShowForm(true)
  }
  const openEdit   = (item) => { setForm({...item}); setEditMode(true); setShowForm(true) }

  const save = async () => {
    if (!form.code || !form.name) return alert('Code and Name are required')
    setSaving(true)
    try {
      if (editMode) await hkMasterApi.update(form.code, form)
      else          await hkMasterApi.create(form)
      toast.success(editMode ? 'Item updated' : 'Item added to catalog')
      setShowForm(false); refetch()
    } catch (err) {
      toast.error(editMode ? 'Failed to update item' : 'Failed to add item')
    } finally { setSaving(false) }
  }



  const dm = useDeleteMode(filtered, r => r.code, deleteApi.hkMaster, refetch)

  if (loading) return <><Header title="HK Benchmark Catalog" /><div className="page-content"><Spinner /></div></>

  return (
    <>
      <Header
        title="HK Benchmark Catalog"
        subtitle={`${items.length} items — Economy / Standard / Premium pricing · Ahmedabad market benchmarks`}
        actions={<button className="btn btn-accent" onClick={openCreate}>+ Add Item</button>}
      />
      <div className="page-content">

        {/* Category filter pills */}
        <div style={{ display:'flex', gap:8, flexWrap:'wrap', marginBottom:20 }}>
          {cats.map(c => {
            const count = c === 'All' ? items.length : items.filter(i => i.category === c).length
            return (
              <button key={c} onClick={() => setCatFilter(c === catFilter ? 'All' : c)}
                className="btn btn-sm"
                style={{ background: catFilter === c ? '#0d0f1a' : 'white', color: catFilter === c ? 'white' : '#374151', border:'1px solid #dde1ec' }}>
                {c} <span style={{ opacity:0.5, fontSize:11, marginLeft:3 }}>{count}</span>
              </button>
            )
          })}
        </div>

        <div className="table-wrap">
          <div className="table-header">
            <span className="table-title">{sorted.length} Items {catFilter !== 'All' && `· ${catFilter}`}</span>
            <div style={{ display:'flex', alignItems:'center', gap:8 }}>
            <EditModeToggle dm={dm} />
            <SearchInput value={search} onChange={setSearch} placeholder="Search code, name, brand…" />
            </div>
          </div>
          <div className="table-scroll">
            <table style={{ minWidth: 1100 }}>
              <thead><tr>
                <SelectTh dm={dm} />
                {[
                  { key:'code',        label:'Code',          style:{ minWidth:80,  width:80  }, cls:'col-sticky-1' },
                  { key:'name',        label:'Item Name',     style:{ minWidth:200, width:200 }, cls:'col-sticky-2' },
                  { key:'category',    label:'Category',      style:{ minWidth:140 } },
                  { key:'sub_category',label:'Sub-Category',  style:{ minWidth:120 } },
                  { key:'uom',         label:'UOM',           style:{ minWidth:60  } },
                  { key:'eco_brand',   label:'Economy Brand', style:{ minWidth:120 } },
                  { key:'eco_price',   label:'Eco ₹',        style:{ minWidth:80, textAlign:'right' } },
                  { key:'std_brand',   label:'Standard Brand',style:{ minWidth:120 } },
                  { key:'std_price',   label:'Std ₹',        style:{ minWidth:80, textAlign:'right' } },
                  { key:'prem_brand',  label:'Premium Brand', style:{ minWidth:120 } },
                  { key:'prem_price',  label:'Prem ₹',       style:{ minWidth:80, textAlign:'right' } },
                  { key:'recommended', label:'Recommended',   style:{ minWidth:110 } },
                  { key:'gst_pct',     label:'GST %',         style:{ minWidth:70, textAlign:'right' } },
                  { key:'max_stock',   label:'Max Stock',     style:{ minWidth:80, textAlign:'right' } },
                  { key:'lead_days',   label:'Lead Days',     style:{ minWidth:75, textAlign:'right' } },
                ].map(h => (
                  <th key={h.key} className={h.cls||''} style={{ ...h.style, cursor:'pointer', userSelect:'none', whiteSpace:'nowrap' }}
                    onClick={() => toggleSort(h.key)}
                    onMouseEnter={e => e.currentTarget.style.color='#0d0f1a'}
                    onMouseLeave={e => e.currentTarget.style.color=''}
                  >{h.label}{sortArrow(h.key)}</th>
                ))}
                <th style={{ minWidth:36, width:36 }}></th>
              </tr></thead>
              <tbody>
                {sorted.length === 0 && (
                  <tr><td colSpan={16} style={{ textAlign:'center', padding:48, color:'#94a3b8' }}>
                    {search ? `No items matching "${search}"` : 'No items in this category'}
                  </td></tr>
                )}
                {sorted.map(i => (
                  <tr key={i.code}>
                    <SelectTd dm={dm} id={i.code} />
                    <td className="col-sticky-1"><span className="td-code">{i.code}</span></td>
                    <td className="col-sticky-2" style={{ fontWeight:500, fontSize:13.5 }}>{i.name}</td>
                    <td><CategoryDot category={i.category} /></td>
                    <td style={{ fontSize:12, color:'#64748b' }}>{i.sub_category}</td>
                    <td style={{ fontSize:13 }}>{i.uom}</td>
                    <td style={{ fontSize:12, color:'#64748b' }}>{i.eco_brand || '—'}</td>
                    <td style={{ textAlign:'right', fontSize:13 }}>{i.eco_price > 0 ? fmtCurrency(i.eco_price) : '—'}</td>
                    <td style={{ fontSize:12 }}>{i.std_brand || '—'}</td>
                    <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif", fontWeight:600 }}>{i.std_price > 0 ? fmtCurrency(i.std_price) : '—'}</td>
                    <td style={{ fontSize:12, color:'#64748b' }}>{i.prem_brand || '—'}</td>
                    <td style={{ textAlign:'right', fontSize:13, color:'#7c3aed' }}>{i.prem_price > 0 ? fmtCurrency(i.prem_price) : '—'}</td>
                    <td>
                      <span className="badge" style={{
                        background: i.recommended==='Premium'?'#f5f3ff':i.recommended==='Economy'?'#f1f5f9':'#fefce8',
                        color: i.recommended==='Premium'?'#7c3aed':i.recommended==='Economy'?'#475569':'#854d0e',
                        fontSize:11
                      }}>{i.recommended}</span>
                    </td>
                    <td style={{ textAlign:'right', fontSize:13, color:'#64748b' }}>{i.gst_pct > 0 ? `${i.gst_pct}%` : '—'}</td>
                    <td style={{ textAlign:'right', fontSize:13 }}>{i.max_stock > 0 ? i.max_stock : '—'}</td>
                    <td style={{ textAlign:'right', fontSize:13 }}>{i.lead_days > 0 ? `${i.lead_days}d` : '—'}</td>
                    <td>
                      <button
                        onClick={e => { e.stopPropagation(); openEdit(i) }}
                        title="Edit item"
                        style={{
                          width:28, height:28, borderRadius:6,
                          border:'1px solid #e2e8f0', background:'white',
                          color:'#64748b', cursor:'pointer',
                          display:'flex', alignItems:'center', justifyContent:'center',
                          transition:'all 0.15s',
                        }}
                        onMouseEnter={e => { e.currentTarget.style.background='#f8f9fc'; e.currentTarget.style.color='#0d0f1a'; e.currentTarget.style.borderColor='#c4cad8' }}
                        onMouseLeave={e => { e.currentTarget.style.background='white'; e.currentTarget.style.color='#64748b'; e.currentTarget.style.borderColor='#e2e8f0' }}
                      >
                        <PencilIcon />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ padding:'10px 20px', borderTop:'1px solid #f1f3f8', fontSize:12, color:'#94a3b8' }}>
            Showing {filtered.length} of {items.length} items · Prices are Ahmedabad market benchmarks
          </div>
        </div>

        {/* ── Add / Edit SlideOver ── */}
        <SlideOver
          open={showForm}
          onClose={() => setShowForm(false)}
          title={editMode ? `Edit: ${form.name}` : 'Add to Benchmark Catalog'}
          subtitle={editMode ? form.code : 'Add a new item with Economy / Standard / Premium pricing'}
          wide
          footer={
            <>
              <button className="btn btn-outline" onClick={() => setShowForm(false)}>Cancel</button>
              <button className="btn btn-accent" onClick={save} disabled={saving}>
                {saving ? 'Saving…' : editMode ? 'Save Changes' : 'Add Item'}
              </button>
            </>
          }
        >
          <FormGrid>
            <F label="Item Code" field="code" half readOnly form={form} setForm={setForm} />
            <F label="Status" half>
              <select className="select" value={form.status} onChange={e => setForm({...form, status:e.target.value})}>
                {['Active','Inactive','Discontinued'].map(s => <option key={s}>{s}</option>)}
              </select>
            </F>
            <F label="Item Name" field="name" form={form} setForm={setForm} />
            <F label="Category" half>
              <select className="select" value={form.category} onChange={e => setForm({...form, category:e.target.value})}>
                {CATEGORIES.map(c => <option key={c}>{c}</option>)}
              </select>
            </F>
            <F label="Sub-Category" field="sub_category" half form={form} setForm={setForm} />
            <F label="UOM" half>
              <select className="select" value={form.uom} onChange={e => setForm({...form, uom:e.target.value})}>
                {UOMS.map(u => <option key={u}>{u}</option>)}
              </select>
            </F>
            <F label="Recommended Tier" half>
              <select className="select" value={form.recommended} onChange={e => setForm({...form, recommended:e.target.value})}>
                {['Economy','Standard','Premium'].map(t => <option key={t}>{t}</option>)}
              </select>
            </F>

            <div className="section-divider" style={{ gridColumn:'1/-1' }}>💰 Economy Tier</div>
            <F label="Economy Brand" field="eco_brand" half form={form} setForm={setForm} />
            <F label="Economy Price ₹" field="eco_price" type="number" half form={form} setForm={setForm} />

            <div className="section-divider" style={{ gridColumn:'1/-1' }}>⭐ Standard Tier</div>
            <F label="Standard Brand" field="std_brand" half form={form} setForm={setForm} />
            <F label="Standard Price ₹" field="std_price" type="number" half form={form} setForm={setForm} />

            <div className="section-divider" style={{ gridColumn:'1/-1' }}>💎 Premium Tier</div>
            <F label="Premium Brand" field="prem_brand" half form={form} setForm={setForm} />
            <F label="Premium Price ₹" field="prem_price" type="number" half form={form} setForm={setForm} />

            <div className="section-divider" style={{ gridColumn:'1/-1' }}>📦 Stock Controls</div>
            <F label="Rate ₹ (for Item Master)" field="rate" type="number" half form={form} setForm={setForm} />
            <F label="GST %" half>
              <select className="select" value={form.gst_pct} onChange={e => setForm({...form, gst_pct:e.target.value})}>
                {[0,5,12,18,28].map(g => <option key={g} value={g}>{g}%</option>)}
              </select>
            </F>
            <F label="Reorder Level" field="rol" type="number" half form={form} setForm={setForm} />
            <F label="Max Stock"     field="max_stock" type="number" half form={form} setForm={setForm} />
            <F label="Lead Days"     field="lead_days" type="number" half form={form} setForm={setForm} />
          </FormGrid>

          {/* Price comparison preview */}
          {(num(form.eco_price) > 0 || num(form.std_price) > 0 || num(form.prem_price) > 0) && (
            <div style={{ marginTop:16, background:'#f8f9fc', borderRadius:10, padding:16 }}>
              <div style={{ fontSize:11, color:'#94a3b8', textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:12 }}>Price Preview</div>
              <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:10 }}>
                {[
                  ['Economy', form.eco_price, form.eco_brand, '#f1f5f9','#475569'],
                  ['Standard',form.std_price, form.std_brand, '#fefce8','#854d0e'],
                  ['Premium', form.prem_price,form.prem_brand,'#f5f3ff','#7c3aed'],
                ].map(([tier, price, brand, bg, col]) => price > 0 && (
                  <div key={tier} style={{ background:bg, borderRadius:8, padding:'10px 12px', textAlign:'center' }}>
                    <div style={{ fontSize:11, color:col, fontWeight:500, marginBottom:4 }}>{tier}</div>
                    <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:18, color:col }}>₹{price}</div>
                    {brand && <div style={{ fontSize:11, color:col, opacity:0.7, marginTop:3 }}>{brand}</div>}
                    {tier === form.recommended && <div style={{ fontSize:10, marginTop:4, color:col, fontWeight:600 }}>✓ Recommended</div>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </SlideOver>
      </div>
        <DeleteToolbar dm={dm} label="hkmaster" />
    </>
  )
}
