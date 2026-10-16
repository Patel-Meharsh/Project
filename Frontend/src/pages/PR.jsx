import { useState } from 'react'
import DeleteToolbar, { EditModeToggle, SelectTh, SelectTd } from '../components/DeleteToolbar'
import { useDeleteMode } from '../hooks/useDeleteMode'
import { deleteApi, prApi, poApi, itemApi, locationApi, codeApi } from '../lib/api'
import { fmtCurrency, fmtDate } from '../lib/utils'
import { StatusBadge, PriorityBadge, Spinner, FormRow, FormGrid, SearchInput } from '../components/UI'
import SlideOver from '../components/SlideOver'
import Header from '../components/Header'
import { useAuth } from '../lib/AuthContext'
import { canDo } from '../lib/auth'
import useDataFetch from '../lib/useDataFetch'
import { useToast } from '../components/Toast'

const DEPTS = ['Admin','Housekeeping','Maintenance','Finance','HR','Operations','Security','Pantry','IT']
const PRIORITIES = ['Urgent','High','Normal','Low']
const EMPTY = { pr_no:'', item_code:'', req_qty:1, location_code:'', department:'Admin', requested_by:'', priority:'Normal', required_date:'', justification:'', status:'Draft' }
const emptyLine = () => ({ id: Date.now() + Math.random(), item_code: '', qty: 1, uom: '', rate: 0 })

const num = v => {
  if (typeof v === 'number') return Number.isFinite(v) ? v : 0
  const parsed = Number(String(v ?? '').replace(/[,₹\\s]/g, ''))
  return Number.isFinite(parsed) ? parsed : 0
}
const calculateLineTotal = lines => Math.round((lines || []).reduce((sum, li) => sum + num(li.qty) * num(li.rate), 0) * 100) / 100

export default function PR() {
  const toast = useToast()
  const { user } = useAuth()
  const isAdmin = canDo(user?.role, 'admin')
  const { data: fetchResult, loading, refetch } = useDataFetch(() =>
    Promise.all([prApi.getAll(), itemApi.getAll(), locationApi.getAll()])
  )
  const [prs, items, locs] = fetchResult || [[], [], []]

  const [search, setSearch]       = useState('')
  const [filter, setFilter]       = useState('All')
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm]           = useState(EMPTY)
  const [saving, setSaving]       = useState(false)
  const [lineItems, setLineItems] = useState([emptyLine()])

  // View / Edit existing PR
  const [viewPR, setViewPR]       = useState(null)
  const [editForm, setEditForm]   = useState(EMPTY)
  const [editLines, setEditLines] = useState([])
  const [editSaving, setEditSaving] = useState(false)

  const f = (field, val) => setForm(p => ({ ...p, [field]: val }))
  const ef = (field, val) => setEditForm(p => ({ ...p, [field]: val }))

  // ── Create helpers ──────────────────────────────────────────────────────────
  const openCreate = async () => {
    const code = await codeApi.next('pr')
    setForm({ ...EMPTY, pr_no: code })
    setLineItems([emptyLine()])
    setShowCreate(true)
  }

  const updateLine = (id, field, value) => {
    setLineItems(prev => prev.map(li => {
      if (li.id !== id) return li
      const updated = { ...li, [field]: value }
      if (field === 'item_code') {
        const it = items.find(i => i.code === value)
        updated.uom = it?.uom || ''; updated.rate = num(it?.rate)
      }
      return updated
    }))
  }
  const addLine = () => setLineItems(prev => [...prev, emptyLine()])
  const removeLine = (id) => setLineItems(prev => prev.length <= 1 ? prev : prev.filter(li => li.id !== id))
  const lineTotal = calculateLineTotal(lineItems)

  const save = async () => {
    const validLines = lineItems.filter(li => li.item_code)
    if (validLines.length === 0) return alert('Please select at least one item')
    if (!form.location_code) return alert('Please select a location')
    setSaving(true)
    try {
      await prApi.create({
        ...form,
        item_code: validLines[0].item_code,
        req_qty: validLines.reduce((s, li) => s + num(li.qty), 0),
        pr_date: new Date().toISOString().split('T')[0],
        est_value: lineTotal,
        line_items: validLines.map(li => {
          const it = items.find(i => i.code === li.item_code)
          return { item_code: li.item_code, item_name: it?.name || '', qty: num(li.qty), uom: li.uom, rate: num(li.rate) }
        })
      })
      toast.success('Requisition created')
      setShowCreate(false); refetch()
    } catch { toast.error('Failed to create requisition') }
    finally { setSaving(false) }
  }

  // ── View / Edit helpers ─────────────────────────────────────────────────────
  const openPR = (pr) => {
    setEditForm({
      pr_no: pr.pr_no,
      location_code: pr.location_code || '',
      department: pr.department || 'Admin',
      requested_by: pr.requested_by || '',
      priority: pr.priority || 'Normal',
      required_date: pr.required_date || '',
      justification: pr.justification || '',
      status: pr.status,
    })
    // Build line items from PR data
    const lis = Array.isArray(pr.line_items) && pr.line_items.length > 0
      ? pr.line_items.map(li => ({
          id: Date.now() + Math.random(),
          item_code: li.item_code || '',
          qty: num(li.qty),
          uom: li.uom || '',
          rate: num(li.rate),
        }))
      : pr.item_code
        ? [{ id: Date.now(), item_code: pr.item_code, qty: num(pr.req_qty), uom: pr.uom || '', rate: num(pr.rate) }]
        : [emptyLine()]
    setEditLines(lis)
    setViewPR(pr)
  }

  const isDraft = viewPR?.status === 'Draft'

  const updateEditLine = (id, field, value) => {
    setEditLines(prev => prev.map(li => {
      if (li.id !== id) return li
      const updated = { ...li, [field]: value }
      if (field === 'item_code') {
        const it = items.find(i => i.code === value)
        updated.uom = it?.uom || ''; updated.rate = num(it?.rate)
      }
      return updated
    }))
  }
  const addEditLine = () => setEditLines(prev => [...prev, emptyLine()])
  const removeEditLine = (id) => setEditLines(prev => prev.length <= 1 ? prev : prev.filter(li => li.id !== id))
  const editLineTotal = calculateLineTotal(editLines)

  const saveEdit = async () => {
    const validLines = editLines.filter(li => li.item_code)
    if (validLines.length === 0) return alert('At least one item is required')
    if (!editForm.location_code) return alert('Location is required')
    setEditSaving(true)
    try {
      await prApi.update(editForm.pr_no, {
        ...editForm,
        item_code: validLines[0].item_code,
        req_qty: validLines.reduce((s, li) => s + num(li.qty), 0),
        line_items: validLines.map(li => {
          const it = items.find(i => i.code === li.item_code)
          return { item_code: li.item_code, item_name: it?.name || '', qty: num(li.qty), uom: li.uom, rate: num(li.rate) }
        })
      })
      toast.success('Requisition updated')
      setViewPR(null); refetch()
    } catch (err) {
      toast.error('Failed to update: ' + (err?.response?.data?.detail || err.message))
    } finally { setEditSaving(false) }
  }

  // ── Actions ─────────────────────────────────────────────────────────────────
  const approve = async (pr) => { try { await prApi.update(pr.pr_no, { status: 'Approved', approved_by: user?.full_name || 'Admin', approval_date: new Date().toISOString().split('T')[0] }); toast.success('PR approved'); setViewPR(null); refetch() } catch { toast.error('Failed to approve') } }
  const reject  = async (pr) => { try { await prApi.update(pr.pr_no, { status: 'Rejected' }); toast.success('PR rejected'); setViewPR(null); refetch() } catch { toast.error('Failed to reject') } }
  const submit  = async (pr) => { try { await prApi.update(pr.pr_no, { status: 'Submitted' }); toast.success('PR submitted'); setViewPR(null); refetch() } catch { toast.error('Failed to submit') } }
  const convertToPO = async (pr) => { try { const res = await poApi.fromPR(pr.pr_no); toast.success(`PO ${res.po_no} created from ${pr.pr_no}`); setViewPR(null); refetch() } catch { toast.error('Failed to convert PR to PO') } }

  const STATUSES = ['All','Draft','Submitted','Approved','Rejected','Converted to PO']
  const STATUS_COUNTS = STATUSES.slice(1).reduce((a, s) => ({ ...a, [s]: prs.filter(p => p.status === s).length }), {})

  const filtered = prs.filter(p => {
    const q = search.toLowerCase()
    const matchSearch = !search ||
      (p.pr_no||'').toLowerCase().includes(q) ||
      (p.item_name||'').toLowerCase().includes(q) ||
      (p.item_code||'').toLowerCase().includes(q) ||
      (p.department||'').toLowerCase().includes(q) ||
      (p.requested_by||'').toLowerCase().includes(q)
    return matchSearch && (filter === 'All' || p.status === filter)
  })

  const dm = useDeleteMode(filtered, r => r.pr_no, deleteApi.prs, refetch)

  const [sortConfig, setSortConfig] = useState({ key: null, direction: 'asc' })
  const toggleSort = (key) => setSortConfig(prev => ({ key, direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc' }))
  const sortArrow = (key) => sortConfig.key === key ? (sortConfig.direction === 'asc' ? ' ↑' : ' ↓') : ''
  const sorted = [...filtered].sort((a, b) => {
    if (!sortConfig.key) return 0
    const mul = sortConfig.direction === 'asc' ? 1 : -1
    if (sortConfig.key === 'pr_date' || sortConfig.key === 'required_date') return (new Date(a[sortConfig.key]||0) - new Date(b[sortConfig.key]||0)) * mul
    const av = a[sortConfig.key], bv = b[sortConfig.key]
    if (typeof av === 'number' || (av != null && !isNaN(Number(av)))) return (Number(av||0) - Number(bv||0)) * mul
    return String(av||'').localeCompare(String(bv||'')) * mul
  })

  const PRIORITY_COLORS = { Urgent:'#dc2626', High:'#f59e0b', Normal:'#3b82f6', Low:'#94a3b8' }

  // ── Shared line items form renderer ─────────────────────────────────────────
  const renderLineItems = (lines, updateFn, addFn, removeFn, _total, readOnly = false) => {
    const total = calculateLineTotal(lines.filter(li => li.item_code))
    return (
    <div style={{ marginTop: 20 }}>
      <div className="label" style={{ marginBottom: 8 }}>Items</div>
      <div style={{ borderRadius: 12, border: '1px solid #edf0f7', overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#f8f9fc' }}>
                <th style={{ padding:'8px 10px', textAlign:'left', fontWeight:600, fontSize:11, color:'#64748b', textTransform:'uppercase', letterSpacing:'0.04em' }}>Item</th>
                <th style={{ padding:'8px 10px', textAlign:'center', fontWeight:600, fontSize:11, color:'#64748b', width:70 }}>Qty</th>
                <th style={{ padding:'8px 10px', textAlign:'center', fontWeight:600, fontSize:11, color:'#64748b', width:60 }}>UOM</th>
                <th style={{ padding:'8px 10px', textAlign:'right', fontWeight:600, fontSize:11, color:'#64748b', width:90 }}>Rate</th>
                <th style={{ padding:'8px 10px', textAlign:'right', fontWeight:600, fontSize:11, color:'#64748b', width:100 }}>Amount</th>
                {!readOnly && <th style={{ width:36 }} />}
              </tr>
            </thead>
            <tbody>
              {lines.map(li => (
                <tr key={li.id} style={{ borderTop:'1px solid #f1f3f8' }}>
                  <td style={{ padding:'6px 10px' }}>
                    {readOnly ? (
                      <span style={{ fontSize:13 }}>{li.item_code}{li.item_name ? ` — ${li.item_name}` : ''}{(() => { const it = items.find(i => i.code === li.item_code); return it ? ` — ${it.name}` : '' })()}</span>
                    ) : (
                      <select className="select" value={li.item_code} onChange={e => updateFn(li.id, 'item_code', e.target.value)} style={{ fontSize:13, minWidth:160 }}>
                        <option value="">-- Select --</option>
                        {items.filter(i => i.status === 'Active').map(i => <option key={i.code} value={i.code}>{i.code} — {i.name}</option>)}
                      </select>
                    )}
                  </td>
                  <td style={{ padding:'6px 6px', textAlign:'center' }}>
                    {readOnly ? <span style={{ fontWeight:600 }}>{li.qty}</span>
                      : <input className="input" type="number" min={1} value={li.qty} onChange={e => updateFn(li.id, 'qty', Number(e.target.value))} style={{ width:64, textAlign:'center', fontSize:13 }} />}
                  </td>
                  <td style={{ padding:'6px 6px', textAlign:'center', color:'#94a3b8', fontSize:12 }}>{li.uom || '—'}</td>
                  <td style={{ padding:'6px 10px', textAlign:'right', fontSize:12, color:'#64748b' }}>{li.rate ? fmtCurrency(li.rate) : '—'}</td>
                  <td style={{ padding:'6px 10px', textAlign:'right', fontWeight:600, fontSize:13 }}>{li.item_code ? fmtCurrency(num(li.qty) * num(li.rate)) : '—'}</td>
                  {!readOnly && (
                    <td style={{ padding:'6px 4px', textAlign:'center' }}>
                      {lines.length > 1 && (
                        <button onClick={() => removeFn(li.id)} style={{ background:'none', border:'none', cursor:'pointer', color:'#dc2626', fontSize:16, lineHeight:1, padding:2 }} title="Remove">×</button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ padding:'8px 10px', borderTop:'1px solid #f1f3f8', display:'flex', justifyContent:'space-between', alignItems:'center' }}>
          {!readOnly ? (
            <button onClick={addFn} style={{ background:'none', border:'none', cursor:'pointer', color:'#3b82f6', fontWeight:600, fontSize:13 }}>+ Add Item</button>
          ) : <span />}
          {total > 0 && (
            <div style={{ display:'flex', alignItems:'center', gap:8 }}>
              <span style={{ fontSize:12, color:'#64748b' }}>Total Estimated Value</span>
              <span style={{ fontFamily:"'Fraunces',serif", fontWeight:800, fontSize:18, color:'#0d0f1a' }}>{fmtCurrency(total)}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
  }

  if (loading) return <><Header title="Purchase Requisitions" /><div className="page-content"><Spinner /></div></>

  return (
    <>
      <Header title="Purchase Requisitions" subtitle="Raise and manage stock requests"
        actions={<button className="btn btn-accent" onClick={openCreate}>+ New Request</button>} />
      <div className="page-content">
        {/* Status tabs */}
        <div className="tabs" style={{ marginBottom: 20 }}>
          {STATUSES.map(s => (
            <button key={s} className={`tab ${filter === s ? 'active' : ''}`} onClick={() => setFilter(s)}>
              {s}
              {s !== 'All' && STATUS_COUNTS[s] > 0 && (
                <span style={{ background: '#e2e8f0', borderRadius: 99, padding: '0 6px', fontSize: 11, marginLeft: 4 }}>{STATUS_COUNTS[s]}</span>
              )}
            </button>
          ))}
        </div>

        <div className="table-wrap">
          <div className="table-header">
            <span className="table-title">{sorted.length} Requisition{sorted.length !== 1 ? 's' : ''}</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <EditModeToggle dm={dm} />
              <SearchInput value={search} onChange={setSearch} placeholder="Search PR, item, dept…" />
            </div>
          </div>
          <div>
            <table>
              <thead><tr>
                <SelectTh dm={dm} />
                {[
                  { key:'pr_no',        label:'PR No',      w:100,    align:'left'  },
                  { key:'pr_date',      label:'Date',       w:95,     align:'left'  },
                  { key:'item_name',    label:'Item',       w:'auto', align:'left'  },
                  { key:'req_qty',      label:'Qty',        w:75,     align:'right' },
                  { key:'est_value',    label:'Est. Value', w:110,    align:'right' },
                  { key:'location_code',label:'Location',   w:95,     align:'left'  },
                  { key:'department',   label:'Dept',       w:100,    align:'left'  },
                  { key:'priority',     label:'Priority',   w:90,     align:'left'  },
                  { key:'status',       label:'Status',     w:115,    align:'left'  },
                ].map(h => (
                  <th key={h.key} style={{ cursor:'pointer', userSelect:'none', whiteSpace:'nowrap', width:h.w, textAlign:h.align }}
                    onClick={() => toggleSort(h.key)}
                    onMouseEnter={e => e.currentTarget.style.color='#0d0f1a'}
                    onMouseLeave={e => e.currentTarget.style.color=''}
                  >{h.label}{sortArrow(h.key)}</th>
                ))}
                <th style={{ width:140, textAlign:'left' }}>Actions</th>
              </tr></thead>
              <tbody>
                {sorted.length === 0 && (
                  <tr><td colSpan={11} style={{ textAlign: 'center', padding: 40, color: '#94a3b8' }}>
                    {search ? `No results for "${search}"` : 'No requisitions found'}
                  </td></tr>
                )}
                {sorted.map(pr => {
                  const codes = (Array.isArray(pr.line_items) ? pr.line_items : []).map(li => li.item_code).filter(Boolean)
                  const itemSummary = codes.length === 0
                    ? (pr.item_code || pr.item_name || '—')
                    : codes.length <= 2
                      ? codes.join(', ')
                      : `${codes.slice(0,2).join(', ')} +${codes.length - 2} more`
                  const itemTitle = codes.length > 2 ? codes.join(', ') : ''
                  return (
                  <tr key={pr.pr_no} onClick={() => openPR(pr)} style={{ cursor:'pointer' }}>
                    <SelectTd dm={dm} id={pr.pr_no} />
                    <td style={{ whiteSpace:'nowrap' }}>
                      <span className="td-code" style={{ color:'#3b82f6', fontWeight:600 }}>{pr.pr_no}</span>
                    </td>
                    <td style={{ color: '#64748b', fontSize: 13, whiteSpace:'nowrap' }}>{fmtDate(pr.pr_date)}</td>
                    <td title={itemTitle}>
                      <div className="clamp-1" style={{ fontFamily:'monospace', fontSize:12.5, fontWeight:500 }}>{itemSummary}</div>
                    </td>
                    <td style={{ textAlign:'right', whiteSpace:'nowrap' }}>{pr.req_qty} <span style={{ color: '#94a3b8', fontSize: 11 }}>{pr.uom}</span></td>
                    <td style={{ textAlign:'right', whiteSpace:'nowrap', fontFamily: "'Fraunces',serif", fontWeight: 600 }}>{fmtCurrency(pr.est_value)}</td>
                    <td style={{ whiteSpace:'nowrap' }}><span className="td-code">{pr.location_code}</span></td>
                    <td style={{ fontSize: 13, whiteSpace:'nowrap' }}><div className="clamp-1">{pr.department}</div></td>
                    <td style={{ whiteSpace:'nowrap' }}><PriorityBadge priority={pr.priority} /></td>
                    <td style={{ whiteSpace:'nowrap' }}><StatusBadge status={pr.status} /></td>
                    <td onClick={e => e.stopPropagation()}>
                      <div style={{ display: 'flex', gap: 6, flexWrap:'wrap' }}>
                        {pr.status === 'Draft' && <button className="btn btn-outline btn-sm row-action" onClick={() => submit(pr)}>Submit</button>}
                        {pr.status === 'Submitted' && isAdmin && <>
                          <button className="btn btn-success btn-sm row-action" onClick={() => approve(pr)}>Approve</button>
                          <button className="btn btn-danger btn-sm row-action" onClick={() => reject(pr)}>Reject</button>
                        </>}
                        {pr.status === 'Approved' && isAdmin && (
                          <button className="btn btn-accent btn-sm" onClick={() => convertToPO(pr)}>→ PO</button>
                        )}
                        {pr.po_ref && <span className="td-code" style={{ fontSize: 12, color: '#3b82f6' }}>{pr.po_ref}</span>}
                      </div>
                    </td>
                  </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
        <DeleteToolbar dm={dm} label="requisitions" />
      </div>

      {/* ── New PR SlideOver ── */}
      <SlideOver
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title="New Purchase Requisition"
        subtitle="Request stock for a location or department"
        wide
        footer={<>
          <button className="btn btn-outline" onClick={() => setShowCreate(false)}>Cancel</button>
          <button className="btn btn-accent" onClick={save} disabled={saving}>{saving ? 'Creating…' : 'Create Request'}</button>
        </>}
      >
        {/* Priority pill-row */}
        <div style={{ marginBottom: 20 }}>
          <div className="label">Priority</div>
          <div style={{ display: 'flex', gap: 8 }}>
            {PRIORITIES.map(p => (
              <button key={p} onClick={() => f('priority', p)}
                style={{ flex:1, padding:'8px 0', borderRadius:8, border:`2px solid ${form.priority === p ? PRIORITY_COLORS[p] : '#edf0f7'}`,
                  background: form.priority === p ? PRIORITY_COLORS[p] + '15' : 'white',
                  color: form.priority === p ? PRIORITY_COLORS[p] : '#64748b',
                  fontWeight: form.priority === p ? 700 : 500, fontSize:13, cursor:'pointer', transition:'all 0.15s' }}>
                {p}
              </button>
            ))}
          </div>
        </div>
        <FormGrid>
          <FormRow label="PR Number" half>
            <input className="input" value={form.pr_no} readOnly style={{ background:'#f8f9fc', color:'#64748b' }} />
          </FormRow>
          <FormRow label="Required By" half>
            <input className="input" type="date" value={form.required_date} onChange={e => f('required_date', e.target.value)} />
          </FormRow>
          <FormRow label="Location *" half>
            <select className="select" value={form.location_code} onChange={e => f('location_code', e.target.value)}>
              <option value="">— Select location —</option>
              {locs.map(l => <option key={l.code} value={l.code}>{l.code} — {l.name}</option>)}
            </select>
          </FormRow>
          <FormRow label="Department" half>
            <select className="select" value={form.department} onChange={e => f('department', e.target.value)}>
              {DEPTS.map(d => <option key={d}>{d}</option>)}
            </select>
          </FormRow>
          <FormRow label="Requested By" half>
            <input className="input" value={form.requested_by} onChange={e => f('requested_by', e.target.value)} placeholder="Name of requester" />
          </FormRow>
          <FormRow label="Justification">
            <textarea className="input" rows={2} value={form.justification} onChange={e => f('justification', e.target.value)} placeholder="Why is this item needed?" />
          </FormRow>
        </FormGrid>
        {renderLineItems(lineItems, updateLine, addLine, removeLine, lineTotal)}
      </SlideOver>

      {/* ── View / Edit PR SlideOver ── */}
      <SlideOver
        open={!!viewPR}
        onClose={() => setViewPR(null)}
        title={`${viewPR?.pr_no}${isDraft ? ' (Draft)' : ''}`}
        subtitle={isDraft ? 'Edit this draft requisition' : 'Requisition details'}
        wide
        footer={
          <div style={{ display:'flex', gap:8, width:'100%' }}>
            <button className="btn btn-outline" onClick={() => setViewPR(null)}>Close</button>
            <div style={{ flex:1 }} />
            {viewPR?.status === 'Draft' && <>
              <button className="btn btn-accent" onClick={saveEdit} disabled={editSaving}>{editSaving ? 'Saving…' : 'Save Draft'}</button>
              <button className="btn btn-primary" onClick={() => { saveEdit().then(() => submit({ pr_no: editForm.pr_no })) }} style={{ background:'#10b981', borderColor:'#10b981' }}>Save & Submit</button>
            </>}
            {viewPR?.status === 'Submitted' && isAdmin && <>
              <button className="btn btn-success" onClick={() => approve(viewPR)}>Approve</button>
              <button className="btn btn-danger" onClick={() => reject(viewPR)}>Reject</button>
            </>}
            {viewPR?.status === 'Approved' && isAdmin && (
              <button className="btn btn-accent" onClick={() => convertToPO(viewPR)}>Convert to PO</button>
            )}
          </div>
        }
      >
        {viewPR && (() => {
          const isEditable = isDraft

          return (
            <>
              {/* Status banner */}
              {!isEditable && (
                <div style={{ padding:'10px 14px', borderRadius:9, marginBottom:20, fontSize:13, display:'flex', alignItems:'center', gap:10,
                  background: viewPR.status === 'Approved' ? '#f0fdf4' : viewPR.status === 'Rejected' ? '#fef2f2' : '#f8f9fc',
                  border: `1px solid ${viewPR.status === 'Approved' ? '#bbf7d0' : viewPR.status === 'Rejected' ? '#fecaca' : '#edf0f7'}`,
                  color: viewPR.status === 'Approved' ? '#166534' : viewPR.status === 'Rejected' ? '#991b1b' : '#475569' }}>
                  <StatusBadge status={viewPR.status} />
                  {viewPR.approved_by && <span>by {viewPR.approved_by}</span>}
                  {viewPR.approval_date && <span>on {fmtDate(viewPR.approval_date)}</span>}
                  {viewPR.po_ref && <span>→ <span className="td-code" style={{ color:'#3b82f6' }}>{viewPR.po_ref}</span></span>}
                </div>
              )}

              {/* Priority (editable for drafts) */}
              {isEditable ? (
                <div style={{ marginBottom:20 }}>
                  <div className="label">Priority</div>
                  <div style={{ display:'flex', gap:8 }}>
                    {PRIORITIES.map(p => (
                      <button key={p} onClick={() => ef('priority', p)}
                        style={{ flex:1, padding:'8px 0', borderRadius:8, border:`2px solid ${editForm.priority === p ? PRIORITY_COLORS[p] : '#edf0f7'}`,
                          background: editForm.priority === p ? PRIORITY_COLORS[p] + '15' : 'white',
                          color: editForm.priority === p ? PRIORITY_COLORS[p] : '#64748b',
                          fontWeight: editForm.priority === p ? 700 : 500, fontSize:13, cursor:'pointer', transition:'all 0.15s' }}>
                        {p}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div style={{ marginBottom:16 }}>
                  <span style={{ fontSize:11, color:'#94a3b8' }}>Priority</span>
                  <div style={{ marginTop:2 }}><PriorityBadge priority={viewPR.priority} /></div>
                </div>
              )}

              {/* Header info */}
              {isEditable ? (
                <FormGrid>
                  <FormRow label="PR Number" half>
                    <input className="input" value={editForm.pr_no} readOnly style={{ background:'#f8f9fc', color:'#64748b' }} />
                  </FormRow>
                  <FormRow label="Required By" half>
                    <input className="input" type="date" value={editForm.required_date} onChange={e => ef('required_date', e.target.value)} />
                  </FormRow>
                  <FormRow label="Location *" half>
                    <select className="select" value={editForm.location_code} onChange={e => ef('location_code', e.target.value)}>
                      <option value="">— Select —</option>
                      {locs.map(l => <option key={l.code} value={l.code}>{l.code} — {l.name}</option>)}
                    </select>
                  </FormRow>
                  <FormRow label="Department" half>
                    <select className="select" value={editForm.department} onChange={e => ef('department', e.target.value)}>
                      {DEPTS.map(d => <option key={d}>{d}</option>)}
                    </select>
                  </FormRow>
                  <FormRow label="Requested By" half>
                    <input className="input" value={editForm.requested_by} onChange={e => ef('requested_by', e.target.value)} placeholder="Name" />
                  </FormRow>
                  <FormRow label="Justification">
                    <textarea className="input" rows={2} value={editForm.justification} onChange={e => ef('justification', e.target.value)} />
                  </FormRow>
                </FormGrid>
              ) : (
                <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'10px 20px', marginBottom:20 }}>
                  {[
                    { label:'Date', value: fmtDate(viewPR.pr_date) },
                    { label:'Required By', value: viewPR.required_date ? fmtDate(viewPR.required_date) : '—' },
                    { label:'Location', value: viewPR.location_code || '—' },
                    { label:'Department', value: viewPR.department || '—' },
                    { label:'Requested By', value: viewPR.requested_by || '—' },
                    { label:'Category', value: viewPR.category || '—' },
                  ].map(({ label, value }) => (
                    <div key={label}>
                      <div style={{ fontSize:11, color:'#94a3b8', marginBottom:2 }}>{label}</div>
                      <div style={{ fontSize:13.5, fontWeight:500, color:'#0d0f1a' }}>{value}</div>
                    </div>
                  ))}
                  {viewPR.justification && (
                    <div style={{ gridColumn:'1/-1' }}>
                      <div style={{ fontSize:11, color:'#94a3b8', marginBottom:2 }}>Justification</div>
                      <div style={{ fontSize:13, color:'#475569' }}>{viewPR.justification}</div>
                    </div>
                  )}
                </div>
              )}

              {/* Line items */}
              {isEditable
                ? renderLineItems(editLines, updateEditLine, addEditLine, removeEditLine, editLineTotal)
                : renderLineItems(
                    (Array.isArray(viewPR.line_items) && viewPR.line_items.length > 0
                      ? viewPR.line_items.map((li, i) => ({ id: i, ...li }))
                      : viewPR.item_code ? [{ id: 0, item_code: viewPR.item_code, item_name: viewPR.item_name, qty: viewPR.req_qty, uom: viewPR.uom, rate: viewPR.rate }] : []),
                    ()=>{}, ()=>{}, ()=>{},
                    viewPR.est_value || 0,
                    true // readOnly
                  )
              }
            </>
          )
        })()}
      </SlideOver>
    </>
  )
}
