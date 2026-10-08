import { useEffect, useRef, useState } from 'react'
import DeleteToolbar, { SelectTh, SelectTd } from '../components/DeleteToolbar'
import { useDeleteMode } from '../hooks/useDeleteMode'
import { deleteApi } from '../lib/api'
import { grnApi, poApi, vendorApi, itemApi, codeApi, locationApi} from '../lib/api'
import { fmtCurrency, fmtDate } from '../lib/utils'
import { StatusBadge, Spinner, SearchInput, FormRow, FormGrid } from '../components/UI'
import SlideOver from '../components/SlideOver'
import Header from '../components/Header'
import { useAuth } from '../lib/AuthContext'
import { canDo } from '../lib/auth'
import useDataFetch from '../lib/useDataFetch'
import { useToast } from '../components/Toast'

const PencilIcon = () => (
  <svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4l4 4L6 17H2v-4L11 4z"/><path d="M9.5 6.5l4 4"/>
  </svg>
)
const TrashIcon = () => (
  <svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 6 5 6 17 6"/><path d="M8 6V4h4v2"/><path d="M6 6l1 11h6l1-11"/>
  </svg>
)

// Searchable combo input — searches options by code or name, shows two-line suggestions
function ComboSearch({ query, onQueryChange, onSelect, options, placeholder, hasError }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  const q = (query || '').toLowerCase()
  const suggestions = q.length === 0 ? [] : options
    .filter(o => o.code.toLowerCase().includes(q) || o.name.toLowerCase().includes(q))
    .slice(0, 10)

  useEffect(() => {
    const handler = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <input
        className="input"
        value={query}
        placeholder={placeholder}
        style={hasError ? { borderColor: '#dc2626' } : {}}
        onChange={e => { onQueryChange(e.target.value); setOpen(true) }}
        onFocus={() => { if (q.length > 0) setOpen(true) }}
        onKeyDown={e => { if (e.key === 'Escape') setOpen(false) }}
      />
      {open && suggestions.length > 0 && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 400,
          background: 'white', border: '1px solid #e2e8f0', borderRadius: 8,
          boxShadow: '0 6px 20px rgba(0,0,0,0.12)', maxHeight: 200, overflowY: 'auto',
        }}>
          {suggestions.map(o => (
            <div key={o.code}
              style={{ padding: '8px 12px', cursor: 'pointer', borderBottom: '1px solid #f1f5f9' }}
              onMouseEnter={e => e.currentTarget.style.background = '#f8fafc'}
              onMouseLeave={e => e.currentTarget.style.background = ''}
              onMouseDown={e => { e.preventDefault(); onSelect(o); setOpen(false) }}
            >
              <div style={{ fontWeight: 700, fontFamily: 'monospace', fontSize: 12.5, color: '#0d0f1a' }}>{o.code}</div>
              <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 1 }}>{o.name}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function GRN() {
  const toast = useToast()
  const { data: fetchResult, loading, refetch } = useDataFetch(() =>
    Promise.all([
      grnApi.getAll(),
      poApi.getAll(),
      vendorApi.getAll(),
      itemApi.getAll(),
      locationApi.getAll(),
    ]).catch(err => { toast.error('Failed to load GRN data'); return [[], [], [], [], []] })
  )
  const [grns, pos, vendors, items, locs] = fetchResult || [[], [], [], [], []]
  const [search, setSearch] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({ grn_no:'', grn_date: new Date().toISOString().split('T')[0], invoice_no:'', po_no:'', uom:'', rate:0, received_by:'Store Keeper', inspected_by:'', store_location:'STORE-CH', batch_lot:'', status:'Stored', remarks:'' })
  const emptyRow = () => ({
    id: Date.now(),
    item_code: '',
    item_name: '',
    vendor_code: '',
    vendor_name: '',
    recd_qty: 0,
    accepted_qty: 0,
    rate: 0,
  })
  const [lineItems, setLineItems] = useState([emptyRow()])
  const [rowError, setRowError] = useState(false)
  const [editMode, setEditMode] = useState(false)
  const [editTarget, setEditTarget] = useState(null)
  const [viewGrn, setViewGrn] = useState(null)

  const { user } = useAuth()
  const isAdmin = canDo(user?.role, 'admin')

  const load = () => refetch()

  const openEdit = (grn) => {
    setEditTarget(grn)
    setForm({
      grn_no:         grn.grn_no || '',
      grn_date:       grn.grn_date || new Date().toISOString().split('T')[0],
      invoice_no:     grn.invoice_no || '',
      po_no:          grn.po_no || '',
      uom:            grn.uom || '',
      rate:           grn.rate || 0,
      received_by:    grn.received_by || '',
      inspected_by:   grn.inspected_by || '',
      store_location: grn.store_location || '',
      batch_lot:      grn.batch_lot || '',
      status:         grn.status || 'Stored',
      remarks:        grn.remarks || '',
    })
    const rows = Array.isArray(grn.line_items) && grn.line_items.length > 0
      ? grn.line_items.map(r => ({
          ...emptyRow(),
          item_code:    r.item_code    || '',
          item_name:    r.item_name    || '',
          vendor_code:  r.vendor_code  || '',
          vendor_name:  r.vendor_name  || '',
          recd_qty:     r.recd_qty     || 0,
          accepted_qty: r.accepted_qty || 0,
          rate:         r.rate != null ? r.rate : (grn.rate || 0),
        }))
      : [{ ...emptyRow(), item_code: grn.item_code || '', item_name: grn.item_name || '',
           vendor_code: grn.vendor_code || '', rate: grn.rate || 0 }]
    setLineItems(rows)
    setShowCreate(true)
  }

  const closeSlideOver = () => {
    setShowCreate(false)
    setEditTarget(null)
    setRowError(false)
  }

  const openCreate = async () => {
    const code = await codeApi.next('grn')
    setForm(f => ({ ...f, grn_no: code, grn_date: new Date().toISOString().split('T')[0] }))
    setShowCreate(true)
  }

  const [sortConfig, setSortConfig] = useState({ key: 'grn_no', direction: 'asc' })
  const toggleSort = (key) => setSortConfig(prev => ({ key, direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc' }))
  const sortArrow = (key) => sortConfig.key === key ? (sortConfig.direction === 'asc' ? ' ↑' : ' ↓') : ''

  const filtered = grns.filter(g => {
    const q = search.toLowerCase()
    return !search ||
      (g.grn_no||'').toLowerCase().includes(q) ||
      (g.item_name||'').toLowerCase().includes(q) ||
      (g.vendor_name||'').toLowerCase().includes(q) ||
      (g.vendor_code||'').toLowerCase().includes(q) ||
      (g.po_no||'').toLowerCase().includes(q)
  })

  const sorted = [...filtered].sort((a, b) => {
    if (!sortConfig.key) return 0
    const mul = sortConfig.direction === 'asc' ? 1 : -1
    if (sortConfig.key === 'grn_date') return (new Date(a.grn_date||0) - new Date(b.grn_date||0)) * mul
    const av = a[sortConfig.key], bv = b[sortConfig.key]
    if (typeof av === 'number' || (av != null && !isNaN(Number(av)))) return (Number(av||0) - Number(bv||0)) * mul
    return String(av||'').localeCompare(String(bv||''), undefined, { numeric: true, sensitivity: 'base' }) * mul
  })

  // Auto-fill all line items when a PO is selected. Per-line remaining_qty comes
  // from the backend (PO line qty − Σ accepted_qty across prior GRNs for same PO+item),
  // so partial GRNs default to what's actually left on each line.
  const selectPO = async (po_no) => {
    if (!po_no) {
      setForm(f => ({ ...f, po_no: '' }))
      return
    }
    try {
      const data = await poApi.grnPrefill(po_no)
      const firstRate = data.line_items[0]?.rate || 0
      setForm(f => ({
        ...f,
        po_no: data.po_no,
        rate: firstRate,
        store_location: f.store_location || data.delivery_location || 'STORE-CH',
      }))
      if (!data.line_items.length) {
        toast.error('All items on this PO are already fully received')
        setLineItems([emptyRow()])
        return
      }
      setLineItems(data.line_items.map((li, idx) => ({
        id: Date.now() + idx,
        item_code:    li.item_code,
        item_name:    li.item_name,
        vendor_code:  data.vendor_code,
        vendor_name:  data.vendor_name,
        recd_qty:     li.remaining_qty,
        accepted_qty: li.remaining_qty,
        rate:         li.rate,
      })))
    } catch (err) {
      toast.error('Failed to load PO details: ' + (err.response?.data?.detail || err.message))
      setForm(f => ({ ...f, po_no }))
    }
  }

const createGRN = async () => {

  // validation
  if (!form.store_location) return alert('Store Location is required — stock cannot be updated without it.')
  if (lineItems.some(r => !r.item_code.trim())) {
    setRowError(true)
    return alert('Item Code is required for all line items.')
  }
  if (lineItems.some(r => !(Number(r.accepted_qty) > 0))) {
    return alert('Accepted Qty must be greater than 0 for all line items.')
  }

  // NEW payload (this is what you were missing)
  const payload = {
    ...form,
    line_items: lineItems.map(r => ({
      item_code: r.item_code.trim(),
      item_name: r.item_name.trim(),
      vendor_code: r.vendor_code.trim(),
      vendor_name: r.vendor_name.trim(),
      recd_qty: Number(r.recd_qty),
      accepted_qty: Number(r.accepted_qty),
      rate: Number(r.rate || 0),
    }))
  }

  try {
    if (editTarget) {
      await grnApi.update(editTarget.grn_no, payload)
      toast.success('GRN updated')
    } else {
      await grnApi.create(payload)
      toast.success('GRN created')
    }
  } catch (err) {
    toast.error(editTarget ? 'Failed to update GRN' : 'Failed to create GRN')
    return
  }

  closeSlideOver()
  load()

  setForm({
    grn_no:'',
    grn_date: new Date().toISOString().split('T')[0],
    invoice_no:'',
    po_no:'',
    uom:'',
    rate:0,
    received_by:'Store Keeper',
    inspected_by:'',
    store_location:'STORE-CH',
    batch_lot:'',
    status:'Stored',
    remarks:''
  })

  setLineItems([emptyRow()])
}

  const selectedItem = items.find(i => i.code === form.item_code)
  const selectedVendor = vendors.find(v => v.code === form.vendor_code)

  const dm = useDeleteMode(filtered, r => r.grn_no, deleteApi.grns, load)

  if (loading) return <><Header title="Goods Receipt (GRN)" /><div className="page-content"><Spinner /></div></>

  return (
    <>
      <Header title="Goods Receipt Notes" subtitle="Record all incoming deliveries"
        actions={<button className="btn btn-accent" onClick={openCreate}>+ Record GRN</button>} />
      <div className="page-content">
        <div className="kpi-grid" style={{ gridTemplateColumns:'repeat(4,1fr)', marginBottom:20 }}>
          {[{l:'Total GRNs',v:grns.length,c:'blue'},{l:'Accepted Qty',v:grns.reduce((s,g)=>s+(g.accepted_qty||0),0),c:'green'},{l:'Rejected Qty',v:grns.reduce((s,g)=>s+(g.rejected_qty||0),0),c:'red'},{l:'Total Value',v:fmtCurrency(grns.reduce((s,g)=>s+(g.value||0),0)),c:'amber'}].map(k=>(
            <div key={k.l} className={`kpi-card ${k.c}`}><div className="kpi-value">{k.v}</div><div className="kpi-label">{k.l}</div></div>
          ))}
        </div>
        <div className="table-wrap">
          <div className="table-header">
            <span className="table-title">{sorted.length} GRN Records</span>
            <div style={{ display:'flex', alignItems:'center', gap:6 }}>
              {isAdmin && (
                <>
                  <button
                    onClick={() => { setEditMode(m => !m); if (dm.active) dm.toggle() }}
                    title={editMode ? 'Exit edit mode' : 'Edit a GRN'}
                    style={{
                      width:30, height:30, borderRadius:7, cursor:'pointer', flexShrink:0,
                      border: editMode ? '1px solid #3b82f6' : '1px solid #e2e8f0',
                      background: editMode ? '#eff6ff' : 'white',
                      color: editMode ? '#3b82f6' : '#64748b',
                      display:'flex', alignItems:'center', justifyContent:'center', transition:'all 0.15s',
                    }}>
                    <PencilIcon />
                  </button>
                  <button
                    onClick={() => { dm.toggle(); if (editMode) setEditMode(false) }}
                    title={dm.active ? 'Exit delete mode' : 'Select rows to delete'}
                    style={{
                      width:30, height:30, borderRadius:7, cursor:'pointer', flexShrink:0,
                      border: dm.active ? '1px solid #ef4444' : '1px solid #e2e8f0',
                      background: dm.active ? '#fef2f2' : 'white',
                      color: dm.active ? '#ef4444' : '#64748b',
                      display:'flex', alignItems:'center', justifyContent:'center', transition:'all 0.15s',
                    }}>
                    <TrashIcon />
                  </button>
                </>
              )}
              <SearchInput value={search} onChange={setSearch} placeholder="Search GRN, item, vendor…" />
            </div>
          </div>
          <div>
            <table>
              <thead><tr>
                {editMode && <th style={{ width:36 }} />}
                <SelectTh dm={dm} />
                {[
                  { key:'grn_no',        label:'GRN No',   w:100, align:'left'  },
                  { key:'grn_date',      label:'Date',     w:95,  align:'left'  },
                  { key:'po_no',         label:'PO Ref',   w:95,  align:'left'  },
                  { key:'invoice_no',    label:'Invoice',  w:100, align:'left'  },
                  { key:'vendor_name',   label:'Vendor',   w:150, align:'left'  },
                  { key:'item_name',     label:'Item',     w:'auto', align:'left' },
                  { key:'recd_qty',      label:'Recd',     w:65,  align:'right' },
                  { key:'accepted_qty',  label:'Accepted', w:80,  align:'right' },
                  { key:'rate',          label:'Value',    w:105, align:'right' },
                  { key:'store_location',label:'Location', w:100, align:'left'  },
                  { key:'status',        label:'Status',   w:110, align:'left'  },
                ].map(h => (
                  <th key={h.key} style={{ cursor:'pointer', userSelect:'none', whiteSpace:'nowrap', width:h.w, textAlign:h.align }}
                    onClick={() => toggleSort(h.key)}
                    onMouseEnter={e => e.currentTarget.style.color='#0d0f1a'}
                    onMouseLeave={e => e.currentTarget.style.color=''}
                  >{h.label}{sortArrow(h.key)}</th>
                ))}
              </tr></thead>
              <tbody>
                {sorted.length===0 && <tr><td colSpan={12} style={{ textAlign:'center', padding:40, color:'#94a3b8' }}>No GRNs yet</td></tr>}
                {sorted.map(g => {
                  const codes = (Array.isArray(g.line_items) ? g.line_items : []).map(li => li.item_code).filter(Boolean)
                  const itemSummary = codes.length === 0
                    ? (g.item_code || g.item_name || '—')
                    : codes.length <= 2
                      ? codes.join(', ')
                      : `${codes.slice(0,2).join(', ')} +${codes.length - 2} more`
                  const itemTitle = codes.length > 2 ? codes.join(', ') : ''
                  return (
                  <tr key={g.grn_no} onClick={() => setViewGrn(g)} style={{ cursor:'pointer' }}>
                    {editMode && (
                      <td style={{ padding:'8px 4px 8px 10px' }} onClick={e => e.stopPropagation()}>
                        <button
                          onClick={() => openEdit(g)}
                          title={`Edit ${g.grn_no}`}
                          style={{
                            width:26, height:26, borderRadius:6, cursor:'pointer',
                            border:'1px solid #bfdbfe', background:'#eff6ff', color:'#3b82f6',
                            display:'flex', alignItems:'center', justifyContent:'center',
                          }}>
                          <PencilIcon />
                        </button>
                      </td>
                    )}
                    <SelectTd dm={dm} id={g.grn_no} />
                    <td style={{ whiteSpace:'nowrap' }}>
                      <span className="td-code" style={{ color:'#2563eb', fontWeight:600 }}>{g.grn_no}</span>
                    </td>
                    <td style={{ fontSize:13, color:'#64748b', whiteSpace:'nowrap' }}>{fmtDate(g.grn_date)}</td>
                    <td style={{ whiteSpace:'nowrap' }}><span className="td-code" style={{ color:'#3b82f6' }}>{g.po_no}</span></td>
                    <td style={{ whiteSpace:'nowrap' }}><span className="td-code" style={{ color:'#64748b' }}>{g.invoice_no}</span></td>
                    <td style={{ fontSize:13 }}><div className="clamp-2">{g.vendor_name}</div></td>
                    <td title={itemTitle}>
                      <div className="clamp-1" style={{ fontFamily:'monospace', fontSize:12.5, fontWeight:500 }}>{itemSummary}</div>
                    </td>
                    <td style={{ textAlign:'right', whiteSpace:'nowrap' }}>{g.recd_qty}</td>
                    <td style={{ textAlign:'right', whiteSpace:'nowrap' }}><span style={{ color:'#16a34a', fontWeight:600 }}>{g.accepted_qty}</span></td>
                    <td style={{ textAlign:'right', whiteSpace:'nowrap', fontFamily:"'Fraunces',serif", fontWeight:600 }}>{fmtCurrency(g.value ?? (g.accepted_qty * g.rate))}</td>
                    <td style={{ whiteSpace:'nowrap' }}><span className="td-code">{g.store_location}</span></td>
                    <td style={{ whiteSpace:'nowrap' }}><StatusBadge status={g.status} /></td>
                  </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Create GRN SlideOver */}
        <SlideOver
          open={showCreate || !!editTarget}
          onClose={closeSlideOver}
          title={editTarget ? `Edit Goods Receipt — ${editTarget.grn_no}` : 'Record Goods Receipt'}
          subtitle={editTarget ? 'Update the details of this GRN' : 'Record delivery against a Purchase Order'}
          footer={<><button className="btn btn-outline" onClick={closeSlideOver}>Cancel</button><button className="btn btn-accent" onClick={createGRN}>{editTarget ? 'Update GRN' : 'Save GRN'}</button></>}
          wide>
          <FormGrid>
            {/* ── Top fields ── */}
            <FormRow label="GRN Number" half><input className="input" value={form.grn_no} readOnly style={{ background:'#f8f9fc', color:'#64748b' }} /></FormRow>
            <FormRow label="GRN Date" half><input className="input" type="date" value={form.grn_date} onChange={e => setForm({...form, grn_date:e.target.value})} /></FormRow>
            <FormRow label="Purchase Order (auto-fills details)">
              <select className="select" value={form.po_no} onChange={e => selectPO(e.target.value)}>
                <option value="">Select PO…</option>
                {pos.filter(p => !['Fully Received','Closed'].includes(p.status)).map(p => <option key={p.po_no} value={p.po_no}>{p.po_no} — {p.item_name} ({p.status})</option>)}
              </select>
            </FormRow>
            <FormRow label="Invoice Number" half><input className="input" value={form.invoice_no} onChange={e => setForm({...form, invoice_no:e.target.value})} placeholder="INV-V8-2003" /></FormRow>
            <FormRow label="Store Location" half>
              <select className="select" value={form.store_location} onChange={e => setForm({...form, store_location:e.target.value})}>
                <option value=''>— Select location —</option>
                {locs.map(l => <option key={l.code} value={l.code}>{l.code} — {l.name}</option>)}
              </select>
            </FormRow>

            {/* ── Line Items — card layout, internally scrollable ── */}
            <div style={{ gridColumn:'1/-1' }}>
              <div style={{ fontWeight:600, fontSize:13.5, marginBottom:8 }}>Line Items</div>
              <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
                {lineItems.map((row, idx) => (
                  <div key={row.id} style={{
                    border: `1px solid ${rowError && !row.item_code ? '#dc2626' : '#e2e8f0'}`,
                    borderRadius:10, padding:'10px 12px', background:'#fafbfc',
                  }}>
                    {/* Card row 1: Item search + Vendor search + delete */}
                    <div style={{ display:'flex', gap:8, marginBottom:8 }}>
                      <div style={{ flex:1, minWidth:0 }}>
                        <div style={{ fontSize:11, color:'#64748b', marginBottom:3 }}>Item *</div>
                        <ComboSearch
                          query={row.item_code}
                          onQueryChange={val => {
                            const updated = [...lineItems]
                            updated[idx].item_code = val
                            setLineItems(updated)
                          }}
                          onSelect={opt => {
                            const updated = [...lineItems]
                            updated[idx] = {
                              ...updated[idx],
                              item_code: opt.code,
                              item_name: opt.name,
                              rate: Number(opt.rate) || 0,
                            }
                            setLineItems(updated)
                          }}
                          options={items.map(i => ({ code: i.code, name: i.name, rate: i.rate }))}
                          placeholder="HK-003 or item name…"
                          hasError={rowError && !row.item_code}
                        />
                        {row.item_name && <div style={{ fontSize:11, color:'#94a3b8', marginTop:3, paddingLeft:2 }}>{row.item_name}</div>}
                      </div>
                      <div style={{ flex:1, minWidth:0 }}>
                        <div style={{ fontSize:11, color:'#64748b', marginBottom:3 }}>Vendor</div>
                        <ComboSearch
                          query={row.vendor_code}
                          onQueryChange={val => {
                            const updated = [...lineItems]
                            updated[idx].vendor_code = val
                            setLineItems(updated)
                          }}
                          onSelect={opt => {
                            const updated = [...lineItems]
                            updated[idx].vendor_code = opt.code
                            updated[idx].vendor_name = opt.name
                            setLineItems(updated)
                          }}
                          options={vendors.map(v => ({ code: v.code, name: v.name }))}
                          placeholder="V-001 or vendor name…"
                        />
                        {row.vendor_name && <div style={{ fontSize:11, color:'#94a3b8', marginTop:3, paddingLeft:2 }}>{row.vendor_name}</div>}
                      </div>
                      <button
                        className="btn btn-outline"
                        style={{ alignSelf:'flex-start', marginTop:18, flexShrink:0 }}
                        onClick={() => { if (lineItems.length > 1) setLineItems(lineItems.filter((_, i) => i !== idx)) }}
                      >×</button>
                    </div>
                    {/* Card row 2: Qty Recd + Qty Accepted + Rate */}
                    <div style={{ display:'flex', gap:8 }}>
                      <div style={{ flex:1 }}>
                        <div style={{ fontSize:11, color:'#64748b', marginBottom:3 }}>Qty Recd</div>
                        <input className="input" type="number" min="0"
                          value={row.recd_qty ?? ''}
                          onChange={e => {
                            const val = e.target.value
                            const updated = [...lineItems]
                            updated[idx].recd_qty = val === '' ? '' : Number(val)
                            setLineItems(updated)
                          }}
                        />
                      </div>
                      <div style={{ flex:1 }}>
                        <div style={{ fontSize:11, color:'#64748b', marginBottom:3 }}>Qty Accepted *</div>
                        <input className="input" type="number" min="0"
                          value={row.accepted_qty ?? ''}
                          onChange={e => {
                            const val = e.target.value
                            const updated = [...lineItems]
                            updated[idx].accepted_qty = val === '' ? '' : Number(val)
                            setLineItems(updated)
                          }}
                        />
                      </div>
                      <div style={{ flex:1 }}>
                        <div style={{ fontSize:11, color:'#64748b', marginBottom:3 }}>Rate ₹</div>
                        <input className="input" type="number" min="0" step="0.01"
                          value={row.rate ?? ''}
                          onChange={e => {
                            const val = e.target.value
                            const updated = [...lineItems]
                            updated[idx].rate = val === '' ? '' : Number(val)
                            setLineItems(updated)
                          }}
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <button className="btn btn-outline" style={{ marginTop:8 }}
                onClick={() => setLineItems([...lineItems, emptyRow()])}>
                + Add Item
              </button>
            </div>

            {/* ── Bottom fields ── */}
            <FormRow label="Received By" half><input className="input" value={form.received_by} onChange={e => setForm({...form, received_by:e.target.value})} /></FormRow>
            <FormRow label="Inspected By" half><input className="input" value={form.inspected_by} onChange={e => setForm({...form, inspected_by:e.target.value})} /></FormRow>
            <FormRow label="Batch / Lot No" half><input className="input" value={form.batch_lot} onChange={e => setForm({...form, batch_lot:e.target.value})} placeholder="B005" /></FormRow>
            <FormRow label="GRN Status" half>
              <select className="select" value={form.status} onChange={e => setForm({...form, status:e.target.value})}>
                {['Pending Inspection','Inspected - OK','Inspected - Rejected','Partial Accept','Stored','Returned'].map(s => <option key={s}>{s}</option>)}
              </select>
            </FormRow>
            <FormRow label="Remarks"><textarea className="input" rows={2} value={form.remarks} onChange={e => setForm({...form, remarks:e.target.value})} placeholder="Quality notes, damage details, etc." /></FormRow>
          </FormGrid>

          {/* Accepted value summary — uses line item totals */}
          {(() => {
            const totalValue = lineItems.reduce((s, r) => s + Number(r.accepted_qty || 0) * Number(r.rate || 0), 0)
            return totalValue > 0 ? (
              <div style={{ background:'#f0fdf4', borderRadius:10, padding:14, marginTop:8, display:'flex', gap:24 }}>
                <div>
                  <div style={{ fontSize:11, color:'#94a3b8' }}>Accepted Value</div>
                  <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, color:'#16a34a', fontSize:18 }}>{fmtCurrency(totalValue)}</div>
                </div>
              </div>
            ) : null
          })()}
        </SlideOver>
      </div>
        <DeleteToolbar dm={dm} label="grn" />

        {/* ── View GRN SlideOver (read-only) ── */}
        <SlideOver
          open={!!viewGrn}
          onClose={() => setViewGrn(null)}
          title={`GRN ${viewGrn?.grn_no}`}
          subtitle="Goods Receipt Details"
          wide
          footer={
            isAdmin && (
              <button className="btn btn-accent" onClick={() => { const g = viewGrn; setViewGrn(null); openEdit(g) }}>
                Edit GRN
              </button>
            )
          }
        >
          {viewGrn && (() => {
            const items = Array.isArray(viewGrn.line_items) && viewGrn.line_items.length > 0
              ? viewGrn.line_items
              : (() => { try { return JSON.parse(viewGrn.line_items || '[]') } catch { return [] } })()
            const totalAccepted = items.reduce((s, li) => s + Number(li.accepted_qty || 0), 0)
            const totalValue = items.reduce((s, li) => s + Number(li.accepted_qty || 0) * Number(li.rate || 0), 0)

            return (
              <>
                {/* Header Info */}
                <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'10px 20px', marginBottom:20 }}>
                  {[
                    { label:'Date',     value: fmtDate(viewGrn.grn_date) },
                    { label:'Status',   value: <StatusBadge status={viewGrn.status} /> },
                    { label:'Vendor',   value: viewGrn.vendor_name || '—' },
                    { label:'Invoice',  value: viewGrn.invoice_no || '—' },
                    { label:'PO Ref',   value: viewGrn.po_no || '—' },
                    { label:'Location', value: viewGrn.store_location || '—' },
                    { label:'Received By',  value: viewGrn.received_by || '—' },
                    { label:'Inspected By', value: viewGrn.inspected_by || '—' },
                  ].map(({ label, value }) => (
                    <div key={label}>
                      <div style={{ fontSize:11, color:'#94a3b8', marginBottom:2 }}>{label}</div>
                      <div style={{ fontSize:13.5, fontWeight:500, color:'#0d0f1a' }}>{value}</div>
                    </div>
                  ))}
                  {viewGrn.remarks && (
                    <div style={{ gridColumn:'1/-1' }}>
                      <div style={{ fontSize:11, color:'#94a3b8', marginBottom:2 }}>Remarks</div>
                      <div style={{ fontSize:13, color:'#475569' }}>{viewGrn.remarks}</div>
                    </div>
                  )}
                </div>

                {/* Totals */}
                {(totalAccepted > 0 || totalValue > 0) && (
                  <div style={{ display:'flex', gap:20, background:'#f0fdf4', borderRadius:10, padding:'12px 16px', marginBottom:16 }}>
                    <div>
                      <div style={{ fontSize:11, color:'#94a3b8' }}>Total Accepted Qty</div>
                      <div style={{ fontWeight:700, fontSize:18, color:'#16a34a' }}>{totalAccepted}</div>
                    </div>
                    <div>
                      <div style={{ fontSize:11, color:'#94a3b8' }}>Total Value</div>
                      <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:18, color:'#16a34a' }}>{fmtCurrency(totalValue)}</div>
                    </div>
                  </div>
                )}

                {/* Line Items */}
                <div style={{ fontWeight:600, fontSize:13.5, marginBottom:10, color:'#0d0f1a' }}>
                  Line Items ({items.length})
                </div>
                {items.length === 0 && (
                  <div style={{ fontSize:13, color:'#94a3b8', padding:'12px 0' }}>No line items recorded.</div>
                )}
                <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
                  {items.map((li, i) => (
                    <div key={i} style={{
                      border:'1px solid #e2e8f0', borderRadius:10,
                      padding:'12px 14px', background:'#fafbfc',
                    }}>
                      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:6 }}>
                        <div>
                          <span style={{ fontFamily:'monospace', fontWeight:700, fontSize:13, color:'#0d0f1a' }}>{li.item_code}</span>
                          {li.vendor_code && <span style={{ marginLeft:8, fontFamily:'monospace', fontSize:11.5, color:'#94a3b8' }}>{li.vendor_code}</span>}
                        </div>
                        <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:14, color:'#16a34a' }}>
                          {fmtCurrency(Number(li.accepted_qty || 0) * Number(li.rate || 0))}
                        </div>
                      </div>
                      {li.item_name && <div style={{ fontSize:12, color:'#64748b', marginBottom:8 }}>{li.item_name}</div>}
                      <div style={{ display:'flex', gap:16, fontSize:12.5 }}>
                        <div><span style={{ color:'#94a3b8' }}>Received: </span><span style={{ fontWeight:600 }}>{li.recd_qty ?? li.qty_received ?? '—'}</span></div>
                        <div><span style={{ color:'#94a3b8' }}>Accepted: </span><span style={{ fontWeight:600, color:'#16a34a' }}>{li.accepted_qty ?? li.qty_accepted ?? '—'}</span></div>
                        <div><span style={{ color:'#94a3b8' }}>Rate: </span><span style={{ fontWeight:600 }}>₹{li.rate ?? '—'}</span></div>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )
          })()}
        </SlideOver>
    </>
  )
}
