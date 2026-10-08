import { useState } from 'react'
import useDataFetch from '../lib/useDataFetch'
import { useToast } from '../components/Toast'
import DeleteToolbar, { EditModeToggle, SelectTh, SelectTd } from '../components/DeleteToolbar'
import { useDeleteMode } from '../hooks/useDeleteMode'
import { deleteApi } from '../lib/api'
import { returnsApi as returnApi, grnApi, vendorApi, itemApi, codeApi } from '../lib/api'
import { fmtCurrency, fmtDate } from '../lib/utils'
import { Spinner, SearchInput, FormRow, FormGrid } from '../components/UI'
import SlideOver from '../components/SlideOver'
import Header from '../components/Header'

const num = (v) => {
  const n = Number(v)
  return isNaN(n) ? 0 : n
}

export default function Returns() {
  const toast = useToast()
  const { data: fetchResult, loading, refetch } = useDataFetch(() =>
    Promise.all([returnApi.getAll(), grnApi.getAll(), vendorApi.getAll(), itemApi.getAll()])
  )
  const [returns, grns, vendors, items] = fetchResult || [[], [], [], []]

  const [search, setSearch] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({ return_id:'', return_date: new Date().toISOString().split('T')[0], grn_ref:'', item_code:'', item_name:'', qty_returned:1, uom:'', vendor_code:'', reason:'Damaged in transit', status:'Pending', credit_note:'', remarks:'' })

  const filtered = returns.filter(r => !search || (r.return_id||'').toLowerCase().includes(search.toLowerCase()) || (r.item_name||'').toLowerCase().includes(search.toLowerCase()))

  const selectGRN = (grn_no) => {
    const g = grns.find(x => x.grn_no === grn_no)
    if (g) setForm(f => ({ ...f, grn_ref:grn_no, vendor_code:g.vendor_code, item_code:g.item_code, item_name:g.item_name, uom:g.uom }))
    else setForm(f => ({ ...f, grn_ref:grn_no }))
  }

  const createReturn = async () => {
    if (!form.return_id || !form.grn_ref) return alert('Return ID and GRN Ref are required')
    try {
      await returnApi.create(form); setShowCreate(false); refetch()
      setForm({ return_id:'', return_date:new Date().toISOString().split('T')[0], grn_ref:'', item_code:'', item_name:'', qty_returned:1, uom:'', vendor_code:'', reason:'Damaged in transit', status:'Pending', credit_note:'', remarks:'' })
      toast.success('Return logged!')
    } catch { toast.error('Failed to log return') }
  }

  const REASONS = ['Damaged in transit','Wrong item delivered','Quality not as per spec','Short expiry','Quantity mismatch','Packaging damaged','Duplicate delivery','Other']
  const STATUS_MAP = { Pending:{ bg:'#fffbeb',color:'#92400e' }, 'Credit Received':{ bg:'#f0fdf4',color:'#166534' }, 'Replacement Received':{ bg:'#eff6ff',color:'#1e40af' }, Rejected:{ bg:'#fef2f2',color:'#991b1b' } }
  const vMap = Object.fromEntries(vendors.map(v=>[v.code,v.name]))

  const openCreate = async () => {
    const code = await codeApi.next('return')
    setForm(f => ({ ...f, return_id: code, return_date: new Date().toISOString().split('T')[0] }))
    setShowCreate(true)
  }

  const dm = useDeleteMode(filtered, r => r.return_id, deleteApi.returns, refetch)

  if (loading) return <><Header title="Returns Log" /><div className="page-content"><Spinner /></div></>

  const totalReturned = returns.reduce((s,r)=>s+(num(r.qty_returned||0)),0)
  const creditReceived = returns.filter(r=>r.status==='Credit Received').length

  return (
    <>
      <Header title="Returns Log" subtitle="Track vendor returns, credit notes & replacements"
        actions={<button className="btn btn-accent" onClick={openCreate}>+ Log Return</button>} />
      <div className="page-content">
        <div className="kpi-grid" style={{ gridTemplateColumns:'repeat(4,1fr)', marginBottom:20 }}>
          {[
            { l:'Total Returns', v:returns.length, c:'blue', ic:'↩️' },
            { l:'Units Returned', v:totalReturned, c:'amber', ic:'📦' },
            { l:'Credit Received', v:creditReceived, c:'green', ic:'✅' },
            { l:'Pending', v:returns.filter(r=>r.status==='Pending').length, c:'red', ic:'⏳' },
          ].map(k=>(
            <div key={k.l} className={`kpi-card ${k.c}`}><div className={`kpi-icon ${k.c}`}>{k.ic}</div><div className="kpi-value">{k.v}</div><div className="kpi-label">{k.l}</div></div>
          ))}
        </div>

        <div className="table-wrap">
          <div className="table-header">
            <span className="table-title">{filtered.length} Returns</span>
            <div style={{ display:'flex', alignItems:'center', gap:8 }}>
            <EditModeToggle dm={dm} />
            <SearchInput value={search} onChange={setSearch} placeholder="Search return ID or item…" />
            </div>
          </div>
          <div style={{ overflowX:'auto' }}>
            <table>
              <thead><tr>
                <SelectTh dm={dm} />
                <th style={{minWidth:90,whiteSpace:"nowrap"}}>Return ID</th><th style={{minWidth:90,whiteSpace:"nowrap"}}>Date</th><th style={{minWidth:80,whiteSpace:"nowrap"}}>GRN Ref</th><th style={{minWidth:160}}>Item</th><th style={{minWidth:55,textAlign:"right"}}>Qty</th><th style={{minWidth:140}}>Vendor</th><th style={{minWidth:110}}>Reason</th><th style={{minWidth:90,whiteSpace:"nowrap"}}>Credit Note</th><th style={{minWidth:80}}>Status</th><th style={{minWidth:100}}>Remarks</th>
              </tr></thead>
              <tbody>
                {filtered.length===0 && <tr><td colSpan={10} style={{ textAlign:'center', padding:40, color:'#94a3b8' }}>No returns logged yet</td></tr>}
                {filtered.map(r => {
                  const sc = STATUS_MAP[r.status] || { bg:'#f8fafc', color:'#64748b' }
                  return (
                    <tr key={r.return_id}>
                    <SelectTd dm={dm} id={r.return_id} />
                    <td><span className="td-code">{r.return_id}</span></td>
                      <td style={{ fontSize:13, color:'#64748b' }}>{fmtDate(r.return_date)}</td>
                      <td><span className="td-code" style={{ color:'#3b82f6' }}>{r.grn_ref}</span></td>
                      <td><div style={{ fontWeight:500, fontSize:13.5 }}>{r.item_name}</div><div style={{ fontSize:11, color:'#94a3b8' }}>{r.item_code}</div></td>
                      <td>{r.qty_returned} {r.uom}</td>
                      <td style={{ fontSize:13 }}>{vMap[r.vendor_code] || r.vendor_code}</td>
                      <td style={{ fontSize:12, color:'#64748b', maxWidth:160 }}>{r.reason}</td>
                      <td>{r.credit_note ? <span className="td-code" style={{ color:'#16a34a' }}>{r.credit_note}</span> : <span style={{ color:'#94a3b8', fontSize:12 }}>—</span>}</td>
                      <td><span className="badge" style={{ background:sc.bg, color:sc.color }}>{r.status}</span></td>
                      <td style={{ fontSize:12, color:'#64748b' }}>{r.remarks}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Create Return SlideOver */}
        <SlideOver open={showCreate} onClose={() => setShowCreate(false)} title="Log Vendor Return" subtitle="Record a return against a received GRN"
          footer={<><button className="btn btn-outline" onClick={() => setShowCreate(false)}>Cancel</button><button className="btn btn-accent" onClick={createReturn}>Log Return</button></>}
          wide>
          <div className="alert-strip info" style={{ marginBottom:16 }}>💡 Returns are linked to a GRN. Select the GRN to auto-fill item and vendor details.</div>
          <FormGrid>
            <FormRow label="Return ID" half><input className="input" value={form.return_id} readOnly style={{ background:'#f8f9fc', color:'#64748b' }} /></FormRow>
            <FormRow label="Return Date" half><input className="input" type="date" value={form.return_date} onChange={e=>setForm({...form,return_date:e.target.value})} /></FormRow>
            <FormRow label="GRN Reference (auto-fills item & vendor)">
              <select className="select" value={form.grn_ref} onChange={e=>selectGRN(e.target.value)}>
                <option value="">Select GRN…</option>
                {grns.map(g=><option key={g.grn_no} value={g.grn_no}>{g.grn_no} — {g.item_name} ({fmtDate(g.grn_date)})</option>)}
              </select>
            </FormRow>
            {form.item_code && (
              <div className="alert-strip success" style={{ gridColumn:'1/-1' }}>✅ Item: <strong>{form.item_name}</strong> · Vendor: <strong>{vMap[form.vendor_code] || form.vendor_code}</strong></div>
            )}
            <FormRow label="Qty to Return" half><input className="input" type="number" value={form.qty_returned} onChange={e=>setForm({...form,qty_returned:Number(e.target.value)})} /></FormRow>
            <FormRow label="Reason for Return" half>
              <select className="select" value={form.reason} onChange={e=>setForm({...form,reason:e.target.value})}>
                {REASONS.map(r=><option key={r}>{r}</option>)}
              </select>
            </FormRow>
            <FormRow label="Return Status">
              <select className="select" value={form.status} onChange={e=>setForm({...form,status:e.target.value})}>
                {['Pending','Credit Received','Replacement Received','Rejected'].map(s=><option key={s}>{s}</option>)}
              </select>
            </FormRow>
            <FormRow label="Credit Note Number" half><input className="input" value={form.credit_note} onChange={e=>setForm({...form,credit_note:e.target.value})} placeholder="CN-V8-002" /></FormRow>
            <FormRow label="Remarks"><textarea className="input" rows={2} value={form.remarks} onChange={e=>setForm({...form,remarks:e.target.value})} placeholder="Additional details about the return…" /></FormRow>
          </FormGrid>
        </SlideOver>
      </div>
        <DeleteToolbar dm={dm} label="returns" />
    </>
  )
}
