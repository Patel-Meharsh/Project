import { useState } from 'react'
import DeleteToolbar, { EditModeToggle, SelectTh, SelectTd } from '../components/DeleteToolbar'
import { useDeleteMode } from '../hooks/useDeleteMode'
import { deleteApi, poApi, vendorApi, itemApi, codeApi } from '../lib/api'
import { fmtCurrency, fmtDate } from '../lib/utils'
import { StatusBadge, Spinner, FormRow, FormGrid, SearchInput } from '../components/UI'
import SlideOver from '../components/SlideOver'
import Header from '../components/Header'
import useDataFetch from '../lib/useDataFetch'
import { useToast } from '../components/Toast'

const STATUSES = ['All','Draft','Sent to Vendor','Acknowledged','Partial Received','Fully Received','Closed','Cancelled']
const PO_TYPES = ['Routine', 'AMC', 'One-Time', 'Emergency']
const EMPTY = { po_no:'', pr_ref:'', vendor_code:'', item_code:'', uom:'', qty_ordered:1, rate:0, gst_pct:18, delivery_date:'', delivery_location:'STORE-CH', terms:'Net 30', status:'Draft', po_type:'Routine', subject:'', contact_person:'' }

const num = v => Number(v) || 0

function F({ label, field, type='text', half, readOnly, children, form, setForm }) {
  return (
    <FormRow label={label} half={half}>
      {children || (
        <input className="input" type={type} readOnly={!!readOnly}
          style={readOnly ? { background:'#f8f9fc', color:'#64748b' } : {}}
          value={form[field] ?? ''}
          onChange={e => !readOnly && setForm({ ...form, [field]: e.target.value })}
        />
      )}
    </FormRow>
  )
}

export default function PO() {
  const toast = useToast()
  const { data: fetchResult, loading, refetch } = useDataFetch(() =>
    Promise.all([poApi.getAll(), vendorApi.getAll(), itemApi.getAll()])
  )
  const [pos, vendors, items] = fetchResult || [[], [], []]

  const [search,    setSearch]   = useState('')
  const [filter,    setFilter]   = useState('All')
  const [viewPO,   setViewPO]   = useState(null)       // PO details view
  const [showCreate, setShowCreate] = useState(false)
  const [reorderFrom, setReorderFrom] = useState(null) // PO being re-ordered
  const [form,      setForm]     = useState(EMPTY)
  const [saving,    setSaving]   = useState(false)
  const [sortConfig, setSortConfig] = useState({ key: null, direction: 'asc' })
  const mkRow = (overrides={}) => ({ id: Date.now(), item_code:'', description:'', qty:1, uom:'', rate:0, gst_pct:18, ...overrides })
  const [lineItems, setLineItems] = useState([mkRow()])

  const toggleSort = (key) => setSortConfig(prev => ({ key, direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc' }))
  const sortArrow = (key) => sortConfig.key === key ? (sortConfig.direction === 'asc' ? ' ↑' : ' ↓') : ''

  const openCreate = async () => {
    const code = await codeApi.next('po')
    setForm({ ...EMPTY, po_no: code, delivery_date: '' })
    setLineItems([mkRow()])
    setReorderFrom(null)
    setShowCreate(true)
  }

  const openReorder = async (po) => {
    const code = await codeApi.next('po')
    setForm({
      ...EMPTY,
      po_no:             code,
      vendor_code:       po.vendor_code,
      item_code:         po.item_code,
      uom:               po.uom,
      rate:              po.rate,
      gst_pct:           po.gst_pct,
      qty_ordered:       po.qty_ordered,
      delivery_location: po.delivery_location,
      terms:             po.terms,
      pr_ref:            po.pr_ref || '',
      delivery_date:     '',
      status:            'Draft',
      po_type:           po.po_type || 'Routine',
      subject:           po.subject || '',
      contact_person:    po.contact_person || '',
    })
    // Populate line items from source PO
    if (po.line_items && po.line_items.length > 0) {
      setLineItems(po.line_items.map(li => mkRow({ item_code: li.item_code||'', description: li.description||'', qty: li.qty||1, uom: li.uom||'', rate: li.rate||0, gst_pct: li.gst_pct??18 })))
    } else {
      setLineItems([mkRow({ item_code: po.item_code||'', description: po.item_name||'', qty: po.qty_ordered||1, uom: po.uom||'', rate: po.rate||0, gst_pct: po.gst_pct??18 })])
    }
    setReorderFrom(po)
    setShowCreate(true)
  }

  const updateLineItem = (id, field, value) => {
    setLineItems(prev => prev.map(li => {
      if (li.id !== id) return li
      const updated = { ...li, [field]: value }
      if (field === 'item_code') {
        const it = items.find(i => i.code === value)
        if (it) { updated.description = it.name||''; updated.uom = it.uom||''; updated.rate = it.rate||0 }
      }
      return updated
    }))
  }
  const addLineItem = () => setLineItems(prev => [...prev, mkRow({ id: Date.now() + Math.random() })])
  const removeLineItem = (id) => setLineItems(prev => prev.length <= 1 ? prev : prev.filter(li => li.id !== id))
  const liSubtotal = lineItems.reduce((s, li) => s + num(li.qty) * num(li.rate), 0)
  const liGstTotal = lineItems.reduce((s, li) => s + num(li.qty) * num(li.rate) * num(li.gst_pct) / 100, 0)
  const liGrandTotal = liSubtotal + liGstTotal

  const save = async () => {
    if (!form.po_no || !form.vendor_code) return alert('PO No and Vendor required')
    const validLines = lineItems.filter(li => li.item_code)
    if (validLines.length === 0) return alert('At least one line item with an item is required')
    setSaving(true)
    try {
      const firstLine = validLines[0]
      const amount = liSubtotal
      const total  = liGrandTotal
      const payload = {
        ...form,
        po_date:       new Date().toISOString().split('T')[0],
        delivery_date: form.delivery_date || null,
        // backward compat: top-level fields from first line item
        item_code:     firstLine.item_code,
        uom:           firstLine.uom,
        qty_ordered:   num(firstLine.qty),
        rate:          num(firstLine.rate),
        gst_pct:       num(firstLine.gst_pct),
        amount:        Math.round(amount * 100) / 100,
        total:         Math.round(total  * 100) / 100,
        line_items:    validLines.map(li => ({
          item_code: li.item_code, description: li.description, qty: num(li.qty),
          uom: li.uom, rate: num(li.rate), gst_pct: num(li.gst_pct),
          amount: Math.round(num(li.qty) * num(li.rate) * 100) / 100,
        })),
      }
      await poApi.create(payload)
      toast.success('Purchase order created')
      setShowCreate(false); refetch()
    } catch (err) {
      console.error('PO create failed:', err.response?.data || err.message)
      toast.error('Failed to create PO: ' + (err.response?.data?.detail || err.message))
    } finally { setSaving(false) }
  }

  const filtered = pos.filter(p => {
    const ms = !search || p.po_no.toLowerCase().includes(search.toLowerCase()) || (p.vendor_name||'').toLowerCase().includes(search.toLowerCase()) || (p.item_name||'').toLowerCase().includes(search.toLowerCase())
    const mf = filter==='All' || p.status===filter
    return ms && mf
  })

  const sorted = [...filtered].sort((a, b) => {
    if (!sortConfig.key) return 0
    const mul = sortConfig.direction === 'asc' ? 1 : -1
    if (sortConfig.key === 'po_date' || sortConfig.key === 'delivery_date') return (new Date(a[sortConfig.key]||0) - new Date(b[sortConfig.key]||0)) * mul
    const av = a[sortConfig.key], bv = b[sortConfig.key]
    if (typeof av === 'number' || (av != null && !isNaN(Number(av)))) return (Number(av||0) - Number(bv||0)) * mul
    return String(av||'').localeCompare(String(bv||'')) * mul
  })

  const dm = useDeleteMode(filtered, r => r.po_no, deleteApi.pos, refetch)
  const totalValue = pos.reduce((s,p) => s+(p.total||0), 0)



  if (loading) return <><Header title="Purchase Orders" /><div className="page-content"><Spinner /></div></>

  return (
    <>
      <Header title="Purchase Orders" subtitle="Orders placed with vendors"
        actions={<button className="btn btn-accent" onClick={openCreate}>+ Create PO</button>} />
      <div className="page-content">
        <div className="kpi-grid" style={{ gridTemplateColumns:'repeat(4,1fr)', marginBottom:20 }}>
          {[
            { l:'Total POs',      v:pos.length,                                                                         c:'blue',   ic:'📋' },
            { l:'Total Value',    v:fmtCurrency(totalValue),                                                            c:'green',  ic:'💰' },
            { l:'Open Orders',    v:pos.filter(p=>['Sent to Vendor','Partial Received'].includes(p.status)).length,    c:'amber',  ic:'⏳' },
            { l:'Fully Received', v:pos.filter(p=>p.status==='Fully Received').length,                                  c:'teal',   ic:'✅' },
          ].map(k => (
            <div key={k.l} className={`kpi-card ${k.c}`}>
              <div className={`kpi-icon ${k.c}`}>{k.ic}</div>
              <div className="kpi-value">{k.v}</div>
              <div className="kpi-label">{k.l}</div>
            </div>
          ))}
        </div>

        {/* Filter pills + search */}
        <div style={{ display:'flex', gap:8, marginBottom:14, flexWrap:'wrap', alignItems:'center' }}>
          {STATUSES.map(s => (
            <button key={s} onClick={() => setFilter(s)}
              style={{ padding:'5px 12px', borderRadius:20, border:'1px solid', fontSize:12.5, cursor:'pointer', transition:'all 0.15s',
                borderColor: filter===s ? '#0d0f1a' : '#e2e8f0',
                background: filter===s ? '#0d0f1a' : 'white',
                color: filter===s ? 'white' : '#64748b' }}>
              {s}
            </button>
          ))}
          <div style={{ marginLeft:'auto', display:'flex', alignItems:'center', gap:8 }}>
            <EditModeToggle dm={dm} />
            <SearchInput value={search} onChange={setSearch} placeholder="Search PO, vendor, item…" />
          </div>
        </div>

        <div className="table-wrap">
          <table>
            <thead><tr>
              <SelectTh dm={dm} />
              {[
                { key:'po_no',           label:'PO No' },
                { key:'po_date',         label:'Date' },
                { key:'vendor_name',     label:'Vendor' },
                { key:'item_name',       label:'Item' },
                { key:'qty_ordered',     label:'Qty' },
                { key:'rate',            label:'Rate' },
                { key:'amount',          label:'Amount' },
                { key:'gst_pct',         label:'GST' },
                { key:'total',           label:'Total' },
                { key:'delivery_date',   label:'Delivery' },
                { key:'status',          label:'Status' },
                { key:'po_type',         label:'PO Type' },
              ].map(h => (
                <th key={h.key} style={{ cursor:'pointer', userSelect:'none', whiteSpace:'nowrap' }}
                  onClick={() => toggleSort(h.key)}
                  onMouseEnter={e => e.currentTarget.style.color='#0d0f1a'}
                  onMouseLeave={e => e.currentTarget.style.color=''}
                >{h.label}{sortArrow(h.key)}</th>
              ))}
              <th>Actions</th>
            </tr></thead>
            <tbody>
              {sorted.length===0 && <tr><td colSpan={14} style={{ textAlign:'center', padding:40, color:'#94a3b8' }}>No orders found</td></tr>}
              {sorted.map(po => (
                <tr key={po.po_no}>
                  <SelectTd dm={dm} id={po.po_no} />
                  <td><span className="td-code" style={{ cursor:'pointer', color:'#3b82f6' }} onClick={() => setViewPO(po)}>{po.po_no}</span></td>
                  <td style={{ fontSize:13, color:'#64748b', whiteSpace:'nowrap' }}>{fmtDate(po.po_date)}</td>
                  <td><div style={{ fontWeight:500, fontSize:13.5 }}>{po.vendor_name}</div><div style={{ fontSize:11, color:'#94a3b8' }}>{po.vendor_code}</div></td>
                  <td>{po.line_items && po.line_items.length > 1
                    ? <div style={{ fontSize:13.5, fontWeight:500 }}>{po.line_items.length} items</div>
                    : <><div style={{ fontSize:13.5 }}>{po.item_name}</div><div style={{ fontSize:11, color:'#94a3b8' }}>{po.item_code}</div></>
                  }</td>
                  <td>{po.qty_ordered} {po.uom}</td>
                  <td>{fmtCurrency(po.rate)}</td>
                  <td>{fmtCurrency(po.amount)}</td>
                  <td style={{ fontSize:13, color:'#64748b' }}>{po.gst_pct}%</td>
                  <td style={{ fontFamily:"'Fraunces',serif", fontWeight:600 }}>{fmtCurrency(po.total)}</td>
                  <td style={{ fontSize:13, color:'#64748b', whiteSpace:'nowrap' }}>{fmtDate(po.delivery_date)}</td>
                  <td><StatusBadge status={po.status} /></td>
                  <td style={{ fontSize:13, color:'#64748b' }}>{po.po_type || '—'}</td>
                  <td style={{ display:'flex', gap:4 }}>
                    <button onClick={() => openReorder(po)} title="Re-order with same details"
                      className="btn btn-outline btn-sm row-action">
                      🔄 Re-order
                    </button>
                    <button onClick={async () => {
                      try {
                        const res = await poApi.downloadPdf(po.po_no)
                        const blob = new Blob([res.data], { type: res.headers['content-type'] || 'application/pdf' })
                        const url = URL.createObjectURL(blob)
                        const ext = (res.headers['content-type'] || '').includes('html') ? 'html' : 'pdf'
                        const a = document.createElement('a'); a.href = url; a.download = `${po.po_no}.${ext}`
                        document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
                      } catch (err) { toast.error('PDF download failed: ' + (err.response?.data?.detail || err.message)) }
                    }} title="Download PDF"
                      className="btn btn-outline btn-sm row-action">
                      📄 PDF
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <DeleteToolbar dm={dm} label="purchase orders" />
        </div>
      </div>

      {/* ── CREATE / REORDER SLIDE-OVER ── */}
      <SlideOver open={showCreate} onClose={() => setShowCreate(false)}
        title={reorderFrom ? `Re-order from PO ${reorderFrom.po_no}` : 'Create Purchase Order'}
        subtitle={reorderFrom ? 'Pre-filled from previous order — review and confirm' : 'New order to vendor'}
        footer={<>
          <button className="btn btn-outline" onClick={() => setShowCreate(false)}>Cancel</button>
          <button className="btn btn-accent" onClick={save} disabled={saving}>{saving?'Saving…':'Create PO'}</button>
        </>}>

        {reorderFrom && (
          <div style={{ padding:'10px 14px', background:'#fffbeb', borderRadius:9, border:'1px solid #fde68a', marginBottom:20, fontSize:13, color:'#92400e' }}>
            🔄 Re-ordering from <strong>{reorderFrom.po_no}</strong> — all fields pre-filled. Edit before confirming.
          </div>
        )}

        <FormGrid>
          <F form={form} setForm={setForm} label="PO No" field="po_no" half readOnly />
          <F form={form} setForm={setForm} label="PR Ref" field="pr_ref" half />
          <F form={form} setForm={setForm} label="Subject" field="subject" />
          <FormRow label="Vendor *">
            <select className="select" value={form.vendor_code} onChange={e=>setForm({...form,vendor_code:e.target.value})}>
              <option value="">— Select vendor —</option>
              {vendors.map(v=><option key={v.code} value={v.code}>{v.name}</option>)}
            </select>
          </FormRow>
          <F form={form} setForm={setForm} label="Contact Person" field="contact_person" half />
          <F form={form} setForm={setForm} label="Delivery Date" field="delivery_date" type="date" half />
          <F form={form} setForm={setForm} label="Delivery Location" field="delivery_location" half />
          <FormRow label="Payment Terms" half>
            <select className="select" value={form.terms} onChange={e=>setForm({...form,terms:e.target.value})}>
              {['Advance','Net 7','Net 15','Net 30','Net 45','Net 60'].map(t=><option key={t}>{t}</option>)}
            </select>
          </FormRow>
          <FormRow label="Status" half>
            <select className="select" value={form.status} onChange={e=>setForm({...form,status:e.target.value})}>
              {['Draft','Sent to Vendor','Acknowledged'].map(s=><option key={s}>{s}</option>)}
            </select>
          </FormRow>
          <FormRow label="PO Type" half>
            <select className="select" value={form.po_type} onChange={e=>setForm({...form,po_type:e.target.value})}>
              {PO_TYPES.map(t=><option key={t}>{t}</option>)}
            </select>
          </FormRow>
        </FormGrid>

        {/* Line Items */}
        <div style={{ marginTop:20 }}>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:10 }}>
            <span style={{ fontSize:13, fontWeight:600, color:'#334155', textTransform:'uppercase', letterSpacing:'0.05em' }}>Line Items</span>
            <button className="btn btn-outline btn-sm" type="button" onClick={addLineItem}>+ Add Item</button>
          </div>
          <div style={{ overflowX:'auto' }}>
            <table style={{ width:'100%', fontSize:13 }}>
              <thead><tr>
                <th style={{ minWidth:150 }}>Item *</th>
                <th style={{ minWidth:100 }}>Description</th>
                <th style={{ minWidth:70 }}>Qty</th>
                <th style={{ minWidth:60 }}>UOM</th>
                <th style={{ minWidth:80 }}>Rate</th>
                <th style={{ minWidth:60 }}>GST%</th>
                <th style={{ minWidth:90, textAlign:'right' }}>Amount</th>
                <th style={{ width:32 }}></th>
              </tr></thead>
              <tbody>
                {lineItems.map(li => {
                  const liAmt = num(li.qty) * num(li.rate)
                  return (
                    <tr key={li.id}>
                      <td>
                        <select className="select" value={li.item_code} onChange={e => updateLineItem(li.id, 'item_code', e.target.value)} style={{ fontSize:12.5, minWidth:140 }}>
                          <option value="">— Select —</option>
                          {items.filter(it => it.status === 'Active').map(it=><option key={it.code} value={it.code}>{it.code} — {it.name}</option>)}
                        </select>
                      </td>
                      <td><input className="input" value={li.description} onChange={e => updateLineItem(li.id, 'description', e.target.value)} style={{ fontSize:12.5, minWidth:90 }} /></td>
                      <td><input className="input" type="number" min="1" value={li.qty} onChange={e => updateLineItem(li.id, 'qty', e.target.value)} style={{ fontSize:12.5, width:65, textAlign:'center' }} /></td>
                      <td><input className="input" value={li.uom} onChange={e => updateLineItem(li.id, 'uom', e.target.value)} style={{ fontSize:12.5, width:60 }} /></td>
                      <td><input className="input" type="number" min="0" value={li.rate} onChange={e => updateLineItem(li.id, 'rate', e.target.value)} style={{ fontSize:12.5, width:80 }} /></td>
                      <td><input className="input" type="number" min="0" value={li.gst_pct} onChange={e => updateLineItem(li.id, 'gst_pct', e.target.value)} style={{ fontSize:12.5, width:55 }} /></td>
                      <td style={{ textAlign:'right', fontWeight:500, whiteSpace:'nowrap' }}>{fmtCurrency(liAmt)}</td>
                      <td>
                        {lineItems.length > 1 && (
                          <button type="button" onClick={() => removeLineItem(li.id)}
                            style={{ background:'none', border:'none', cursor:'pointer', color:'#ef4444', fontSize:16, padding:2 }}
                            title="Remove line">&times;</button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Cost preview */}
        {liSubtotal > 0 && (
          <div style={{ marginTop:20, borderRadius:10, border:'1px solid #edf0f7', overflow:'hidden' }}>
            <div style={{ background:'#f8f9fc', padding:'10px 16px', fontSize:12, fontWeight:600, color:'#64748b', textTransform:'uppercase', letterSpacing:'0.06em' }}>Order Summary</div>
            {[['Subtotal', fmtCurrency(liSubtotal)],['Total GST', fmtCurrency(liGstTotal)]].map(([l,v])=>(
              <div key={l} style={{ padding:'10px 16px', display:'flex', justifyContent:'space-between', borderBottom:'1px solid #f1f3f8', fontSize:13, color:'#64748b' }}>
                <span>{l}</span><span>{v}</span>
              </div>
            ))}
            <div style={{ padding:'12px 16px', display:'flex', justifyContent:'space-between', alignItems:'center' }}>
              <span style={{ fontWeight:600 }}>Grand Total</span>
              <span style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:20, color:'#0d0f1a' }}>{fmtCurrency(liGrandTotal)}</span>
            </div>
          </div>
        )}
      </SlideOver>

      {/* ── VIEW PO DETAILS SLIDE-OVER ── */}
      <SlideOver
        open={!!viewPO}
        onClose={() => setViewPO(null)}
        title={`PO ${viewPO?.po_no}`}
        subtitle="Purchase Order Details"
        wide
        footer={
          <div style={{ display:'flex', gap:8 }}>
            <button className="btn btn-outline" onClick={async () => {
              if (!viewPO) return
              try {
                const res = await poApi.downloadPdf(viewPO.po_no)
                const blob = new Blob([res.data], { type: res.headers['content-type'] || 'application/pdf' })
                const url = URL.createObjectURL(blob)
                const a = document.createElement('a'); a.href = url; a.download = `${viewPO.po_no}.pdf`
                document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
              } catch (err) { toast.error('PDF download failed') }
            }}>📄 Download PDF</button>
            <button className="btn btn-accent" onClick={() => { const p = viewPO; setViewPO(null); openReorder(p) }}>🔄 Re-order</button>
          </div>
        }
      >
        {viewPO && (() => {
          const vd = vendors.find(v => v.code === viewPO.vendor_code)
          const poItems = Array.isArray(viewPO.line_items) && viewPO.line_items.length > 0
            ? viewPO.line_items
            : viewPO.item_code ? [{ item_code: viewPO.item_code, description: viewPO.item_name, qty: viewPO.qty_ordered, uom: viewPO.uom, rate: viewPO.rate, gst_pct: viewPO.gst_pct }] : []
          const subtotal = poItems.reduce((s, li) => s + num(li.qty) * num(li.rate), 0)
          const gstTotal = poItems.reduce((s, li) => s + num(li.qty) * num(li.rate) * num(li.gst_pct) / 100, 0)
          const grandTotal = subtotal + gstTotal

          return (
            <>
              {/* Header Info Grid */}
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'10px 20px', marginBottom:20 }}>
                {[
                  { label:'Date',            value: fmtDate(viewPO.po_date) },
                  { label:'Status',          value: <StatusBadge status={viewPO.status} /> },
                  { label:'PO Type',         value: viewPO.po_type || 'Routine' },
                  { label:'PR Reference',    value: viewPO.pr_ref ? <span className="td-code" style={{ color:'#3b82f6' }}>{viewPO.pr_ref}</span> : '—' },
                  { label:'Vendor',          value: <><span style={{ fontWeight:600 }}>{viewPO.vendor_name || viewPO.vendor_code}</span>{vd?.city ? <span style={{ color:'#94a3b8', marginLeft:6 }}>{vd.city}</span> : ''}</> },
                  { label:'Contact Person',  value: viewPO.contact_person || vd?.contact_person || '—' },
                  { label:'Delivery Location', value: viewPO.delivery_location || '—' },
                  { label:'Delivery Date',   value: viewPO.delivery_date ? fmtDate(viewPO.delivery_date) : '—' },
                  { label:'Payment Terms',   value: viewPO.terms || '—' },
                  { label:'Received Qty',    value: `${viewPO.received_qty || 0} / ${viewPO.qty_ordered || 0}` },
                ].map(({ label, value }) => (
                  <div key={label}>
                    <div style={{ fontSize:11, color:'#94a3b8', marginBottom:2 }}>{label}</div>
                    <div style={{ fontSize:13.5, fontWeight:500, color:'#0d0f1a' }}>{value}</div>
                  </div>
                ))}
                {viewPO.subject && (
                  <div style={{ gridColumn:'1/-1' }}>
                    <div style={{ fontSize:11, color:'#94a3b8', marginBottom:2 }}>Subject</div>
                    <div style={{ fontSize:13, color:'#475569' }}>{viewPO.subject}</div>
                  </div>
                )}
              </div>

              {/* Vendor Card (if vendor details available) */}
              {vd && (
                <div style={{ background:'#f8f9fc', borderRadius:10, padding:'12px 16px', marginBottom:16, border:'1px solid #edf0f7' }}>
                  <div style={{ fontSize:11, color:'#94a3b8', marginBottom:6, textTransform:'uppercase', letterSpacing:'0.06em', fontWeight:600 }}>Vendor Details</div>
                  <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'4px 16px', fontSize:12.5 }}>
                    {vd.phone && <div><span style={{ color:'#94a3b8' }}>Phone: </span>{vd.phone}</div>}
                    {vd.email && <div><span style={{ color:'#94a3b8' }}>Email: </span>{vd.email}</div>}
                    {vd.address && <div style={{ gridColumn:'1/-1' }}><span style={{ color:'#94a3b8' }}>Address: </span>{vd.address}</div>}
                    {vd.gst_no && <div><span style={{ color:'#94a3b8' }}>GST: </span>{vd.gst_no}</div>}
                    {vd.pan && <div><span style={{ color:'#94a3b8' }}>PAN: </span>{vd.pan}</div>}
                  </div>
                </div>
              )}

              {/* Totals */}
              <div style={{ display:'flex', gap:20, background:'#eff6ff', borderRadius:10, padding:'12px 16px', marginBottom:16 }}>
                <div>
                  <div style={{ fontSize:11, color:'#94a3b8' }}>Subtotal</div>
                  <div style={{ fontWeight:600, fontSize:15 }}>{fmtCurrency(subtotal)}</div>
                </div>
                <div>
                  <div style={{ fontSize:11, color:'#94a3b8' }}>GST</div>
                  <div style={{ fontWeight:600, fontSize:15 }}>{fmtCurrency(gstTotal)}</div>
                </div>
                <div>
                  <div style={{ fontSize:11, color:'#94a3b8' }}>Grand Total</div>
                  <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:20, color:'#1d4ed8' }}>{fmtCurrency(grandTotal)}</div>
                </div>
              </div>

              {/* Line Items */}
              <div style={{ fontWeight:600, fontSize:13.5, marginBottom:10, color:'#0d0f1a' }}>
                Line Items ({poItems.length})
              </div>
              {poItems.length === 0 && (
                <div style={{ fontSize:13, color:'#94a3b8', padding:'12px 0' }}>No line items.</div>
              )}
              <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
                {poItems.map((li, i) => {
                  const liAmt = num(li.qty) * num(li.rate)
                  const liGst = liAmt * num(li.gst_pct) / 100
                  return (
                    <div key={i} style={{ border:'1px solid #e2e8f0', borderRadius:10, padding:'12px 14px', background:'#fafbfc' }}>
                      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:6 }}>
                        <div>
                          <span style={{ fontFamily:'monospace', fontWeight:700, fontSize:13, color:'#0d0f1a' }}>{li.item_code}</span>
                        </div>
                        <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:14, color:'#1d4ed8' }}>
                          {fmtCurrency(liAmt + liGst)}
                        </div>
                      </div>
                      {(li.description || li.item_name) && <div style={{ fontSize:12, color:'#64748b', marginBottom:8 }}>{li.description || li.item_name}</div>}
                      <div style={{ display:'flex', gap:16, fontSize:12.5 }}>
                        <div><span style={{ color:'#94a3b8' }}>Qty: </span><span style={{ fontWeight:600 }}>{li.qty} {li.uom}</span></div>
                        <div><span style={{ color:'#94a3b8' }}>Rate: </span><span style={{ fontWeight:600 }}>₹{num(li.rate).toLocaleString('en-IN')}</span></div>
                        <div><span style={{ color:'#94a3b8' }}>GST: </span><span style={{ fontWeight:600 }}>{li.gst_pct}%</span></div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </>
          )
        })()}
      </SlideOver>
    </>
  )
}
