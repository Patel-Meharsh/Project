import { useState } from 'react'
import useDataFetch from '../lib/useDataFetch'
import { useToast } from '../components/Toast'
import DeleteToolbar, { EditModeToggle, SelectTh, SelectTd } from '../components/DeleteToolbar'
import { useDeleteMode } from '../hooks/useDeleteMode'
import { deleteApi, issuanceApi, itemApi, locationApi, codeApi } from '../lib/api'
import { fmtCurrency, fmtDate } from '../lib/utils'
import { Spinner, SearchInput, FormRow, FormGrid, Tooltip } from '../components/UI'
import SlideOver from '../components/SlideOver'
import Header from '../components/Header'

const DEPARTMENTS = ['Housekeeping','Admin','Security','Pantry','Maintenance','IT','Finance','HR','Operations','Other']
const EMPTY = { issue_id:'', date:new Date().toISOString().split('T')[0], item_code:'', qty:1, uom:'', rate:0, location_code:'', issued_to_location:'', department:'Housekeeping', issued_to:'', issued_by:'Store Keeper', remarks:'' }

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

export default function Issuance() {
  const toast = useToast()
  const { data: fetchResult, loading, refetch } = useDataFetch(() =>
    Promise.all([issuanceApi.getAll(), itemApi.getAll(), locationApi.getAll()])
  )
  const [iss, items, locs] = fetchResult || [[], [], []]

  const [search,setSearch]       = useState('')
  const [showAdd,setShowAdd]     = useState(false)
  const [form,setForm]           = useState(EMPTY)
  const [saving,setSaving]       = useState(false)
  const [sortConfig, setSortConfig] = useState({ key: null, direction: 'asc' })

  const toggleSort = (key) => setSortConfig(prev => ({ key, direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc' }))
  const sortArrow = (key) => sortConfig.key === key ? (sortConfig.direction === 'asc' ? ' ↑' : ' ↓') : ''

  const openAdd = async () => {
    const code = await codeApi.next('issuance')
    setForm({ ...EMPTY, issue_id: code, date: new Date().toISOString().split('T')[0] })
    setShowAdd(true)
  }

  const pickItem = (code) => {
    const it = items.find(i => i.code === code)
    setForm(f => ({ ...f, item_code: code, uom: it?.uom||'', rate: it?.rate||0 }))
  }

  const save = async () => {
    if (!form.item_code || !form.location_code) return alert('Item and Location required')
    if (!Number(form.qty) || Number(form.qty) <= 0) return alert('Qty must be greater than 0')
    setSaving(true)
    try {
      const m = new Date(form.date).getMonth() + 1
      const payload = {
        ...form,
        qty: Number(form.qty),
        rate: Number(form.rate) || 0,
        month: m,
        quarter: Math.ceil(m / 3),
      }
      await issuanceApi.create(payload)
      setShowAdd(false); refetch()
      toast.success('Issuance recorded!')
    } catch (err) {
      const detail = err?.response?.data?.detail || 'Failed to record issuance'
      toast.error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    }
    finally { setSaving(false) }
  }



  const filtered = iss.filter(i => !search ||
    (i.issue_id||'').toLowerCase().includes(search.toLowerCase()) ||
    (i.item_code||'').toLowerCase().includes(search.toLowerCase()) ||
    (i.department||'').toLowerCase().includes(search.toLowerCase()))

  const sorted = [...filtered].sort((a, b) => {
    if (!sortConfig.key) return 0
    const mul = sortConfig.direction === 'asc' ? 1 : -1
    if (sortConfig.key === 'value') return ((a.qty||0)*(a.rate||0) - (b.qty||0)*(b.rate||0)) * mul
    if (sortConfig.key === 'date') return (new Date(a.date||0) - new Date(b.date||0)) * mul
    const av = a[sortConfig.key], bv = b[sortConfig.key]
    if (typeof av === 'number' || (av != null && !isNaN(av))) return (Number(av||0) - Number(bv||0)) * mul
    return String(av||'').localeCompare(String(bv||'')) * mul
  })

  const totalValue = iss.reduce((s,i) => s+(num(i.qty)*num(i.rate||0)), 0)
  const todayStr = new Date().toISOString().split('T')[0]
  const todayCount = iss.filter(i => String(i.date||'').startsWith(todayStr)).length

  const dm = useDeleteMode(filtered, r => r.issue_id, deleteApi.issuances, refetch)

  if (loading) return <><Header title="Issuance Log" /><div className="page-content"><Spinner /></div></>

  return (
    <>
      <Header title="Issuance Log" subtitle={`${iss.length} records · ${fmtCurrency(totalValue)} total`}
        actions={<button className="btn btn-accent" onClick={openAdd}>+ Record Issuance</button>} />
      <div className="page-content">
        <div className="kpi-grid" style={{ gridTemplateColumns:'repeat(4,1fr)', marginBottom:20 }}>
          {[
            { l:"Today's Issuances", v:todayCount,                 c:'blue',   ic:'📦' },
            { l:'Total Records',     v:iss.length,                 c:'purple', ic:'📋' },
            { l:'Total Value',       v:fmtCurrency(totalValue),    c:'green',  ic:'💰' },
            { l:'Departments',       v:[...new Set(iss.map(i=>i.department))].filter(Boolean).length, c:'amber', ic:'🏢' },
          ].map(k => (
            <div key={k.l} className={`kpi-card ${k.c}`}>
              <div className={`kpi-icon ${k.c}`}>{k.ic}</div>
              <div className="kpi-value">{k.v}</div>
              <div className="kpi-label">{k.l}</div>
            </div>
          ))}
        </div>

        <div className="table-wrap">
          <div className="table-header">
            <span className="table-title">{sorted.length} Records</span>
            <div style={{ display:'flex', alignItems:'center', gap:8 }}>
              <EditModeToggle dm={dm} />
              <SearchInput value={search} onChange={setSearch} placeholder="Search item, dept, ID…" />
            </div>
          </div>
          <table>
            <thead><tr>
              <SelectTh dm={dm} />
              {[
                { key:'issue_id',    label:'Issue ID' },
                { key:'date',        label:'Date' },
                { key:'item_code',   label:'Item' },
                { key:'qty',         label:'Qty' },
                { key:'rate',        label:'Rate' },
                { key:'value',       label:'Value' },
                { key:'location_code',label:'From Store' },
                { key:'issued_to_location', label:'To Site' },
                { key:'department',  label:'Dept' },
                { key:'issued_to',   label:'Issued To' },
                { key:'remarks',     label:'Remarks' },
              ].map(h => (
                <th key={h.key} style={{ cursor:'pointer', userSelect:'none', whiteSpace:'nowrap' }}
                  onClick={() => toggleSort(h.key)}
                  onMouseEnter={e => e.currentTarget.style.color='#0d0f1a'}
                  onMouseLeave={e => e.currentTarget.style.color=''}
                >{h.label}{sortArrow(h.key)}</th>
              ))}
            </tr></thead>
            <tbody>
              {sorted.length===0 && <tr><td colSpan={12} style={{ textAlign:'center', padding:40, color:'#94a3b8' }}>No records</td></tr>}
              {sorted.map(i => (
                <tr key={i.issue_id}>
                  <SelectTd dm={dm} id={i.issue_id} />
                  <td><span className="td-code">{i.issue_id}</span></td>
                  <td style={{ fontSize:13, color:'#64748b' }}>{fmtDate(i.date)}</td>
                  <td><Tooltip text={items.find(it => it.code === i.item_code)?.name || i.item_code}><span className="td-code" style={{ cursor:'default' }}>{i.item_code}</span></Tooltip></td>
                  <td style={{ fontWeight:500 }}>{i.qty} {i.uom}</td>
                  <td>{fmtCurrency(i.rate)}</td>
                  <td style={{ fontFamily:"'Fraunces',serif", fontWeight:600 }}>{fmtCurrency((i.qty||0)*(i.rate||0))}</td>
                  <td><Tooltip text={locs.find(l => l.code === i.location_code)?.name || i.location_code}><span className="td-code" style={{ cursor:'default' }}>{i.location_code}</span></Tooltip></td>
                  <td style={{ fontSize:13 }}>{i.issued_to_location ? <Tooltip text={locs.find(l => l.code === i.issued_to_location)?.name || i.issued_to_location}><span className="td-code" style={{ cursor:'default' }}>{i.issued_to_location}</span></Tooltip> : '—'}</td>
                  <td style={{ fontSize:13 }}>{i.department}</td>
                  <td style={{ fontSize:13 }}>{i.issued_to}</td>
                  <td style={{ fontSize:12, color:'#94a3b8' }}>{i.remarks}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <DeleteToolbar dm={dm} label="issuances" />
        </div>
      </div>

      <SlideOver open={showAdd} onClose={() => setShowAdd(false)}
        title="Record Issuance" subtitle="Issue stock items to a department or person"
        footer={<>
          <button className="btn btn-outline" onClick={() => setShowAdd(false)}>Cancel</button>
          <button className="btn btn-accent" onClick={save} disabled={saving}>{saving?'Saving…':'Record Issuance'}</button>
        </>}>
        <FormGrid>
          <F form={form} setForm={setForm} label="Issue ID" field="issue_id" half readOnly />
          <F form={form} setForm={setForm} label="Date" field="date" type="date" half />
          <FormRow label="Item *">
            <select className="select" value={form.item_code} onChange={e => pickItem(e.target.value)}>
              <option value="">— Select item —</option>
              {items.filter(it => it.status === 'Active').map(it => <option key={it.code} value={it.code}>{it.code} — {it.name}</option>)}
            </select>
          </FormRow>
          <FormRow label="Issue From (Store Location)" half>
            <select className="select" value={form.location_code} onChange={e => setForm({...form, location_code:e.target.value})}>
              <option value="">— Select —</option>
              {locs.map(l => <option key={l.code} value={l.code}>{l.name}</option>)}
            </select>
            <div style={{fontSize:11, color:'#94a3b8', marginTop:3}}>Select the store this stock is being taken from (usually STORE-CH)</div>
          </FormRow>
          <FormRow label="Issued To Location (Site)" half>
            <select className="select" value={form.issued_to_location} onChange={e => setForm({...form, issued_to_location:e.target.value})}>
              <option value="">— Select site —</option>
              {locs.filter(l => l.loc_type === 'SITE' || !l.loc_type).map(l => <option key={l.code} value={l.code}>{l.name || l.code}</option>)}
            </select>
            <div style={{fontSize:11, color:'#94a3b8', marginTop:3}}>Where are these items going to?</div>
          </FormRow>
          <FormRow label="Department" half>
            <select className="select" value={form.department} onChange={e => setForm({...form, department:e.target.value})}>
              {DEPARTMENTS.map(d => <option key={d}>{d}</option>)}
            </select>
          </FormRow>
          <F form={form} setForm={setForm} label="Qty" field="qty" type="number" half />
          <F form={form} setForm={setForm} label="UOM" field="uom" half />
          <F form={form} setForm={setForm} label="Rate (₹)" field="rate" type="number" half />
          <F form={form} setForm={setForm} label="Issued To" field="issued_to" half />
          <F form={form} setForm={setForm} label="Issued By" field="issued_by" half />
          <FormRow label="Remarks"><textarea className="input" rows={2} value={form.remarks} onChange={e=>setForm({...form,remarks:e.target.value})} /></FormRow>
        </FormGrid>
        {num(form.qty) > 0 && num(form.rate) > 0 && (
          <div style={{ marginTop:20, padding:'14px 18px', background:'#f0fdf4', borderRadius:10, border:'1px solid #bbf7d0', display:'flex', justifyContent:'space-between', alignItems:'center' }}>
            <span style={{ fontSize:13, color:'#166534' }}>Total issuance value</span>
            <span style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:20, color:'#16a34a' }}>{fmtCurrency(num(form.qty) * num(form.rate))}</span>
          </div>
        )}
      </SlideOver>
    </>
  )
}
