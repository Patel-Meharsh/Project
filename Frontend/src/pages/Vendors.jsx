import { useState, useEffect, useRef } from 'react'
import useDataFetch from '../lib/useDataFetch'
import { useToast } from '../components/Toast'
import DeleteToolbar, { EditModeToggle } from '../components/DeleteToolbar'
import { useDeleteMode } from '../hooks/useDeleteMode'
import { deleteApi, vendorApi, poApi, codeApi, categoryApi, rateCardApi } from '../lib/api'
import { fmtCurrency, fmtDate } from '../lib/utils'
import { Spinner, Stars, SearchInput, FormRow, FormGrid, StatusBadge } from '../components/UI'
import SlideOver from '../components/SlideOver'
import Header from '../components/Header'
import { useAuth } from '../lib/AuthContext'
import { canDo } from '../lib/auth'

// Categories loaded dynamically from API (see useDataFetch below)
const SERVICES = ['Supply of Consumables','Deep Cleaning','Daily Cleaning','Pest Control','Security Services','Housekeeping','Landscaping','Waste Disposal','AC Maintenance','Electrical Maintenance','Plumbing','Catering','Stationery Supply','IT Support','Other']
const EMPTY_V = { code:'', name:'', category:'Cleaning Chemicals', contact_person:'', phone:'', email:'', city:'Ahmedabad', address:'', gst_no:'', pan:'', payment_terms:'Net 30', rating:4.0, status:'Active', services_offered:'', locations_served:'' }

const fmtBytes = (n) => {
  if (!n && n !== 0) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(2)} MB`
}

const ACCEPTED_RATE_CARD_EXTS = ['.pdf', '.docx', '.xlsx', '.jpg', '.jpeg', '.png']
const RATE_CARD_MAX_BYTES = 50 * 1024 * 1024

const extOf = (name='') => {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i).toLowerCase() : ''
}
const isImageExt = (e) => e === '.jpg' || e === '.jpeg' || e === '.png'
const badgeFor = (fileName, mime='') => {
  const e = extOf(fileName)
  if (e === '.pdf')                       return { label:'PDF',  bg:'#fef2f2', fg:'#dc2626' }
  if (e === '.docx')                      return { label:'DOCX', bg:'#eff6ff', fg:'#2563eb' }
  if (e === '.xlsx')                      return { label:'XLSX', bg:'#f0fdf4', fg:'#16a34a' }
  if (isImageExt(e) || mime.startsWith('image/')) return { label:'IMG',  bg:'#fef3c7', fg:'#b45309' }
  return { label: (e.replace('.','').toUpperCase() || 'FILE'), bg:'#f1f5f9', fg:'#475569' }
}

function FileViewerModal({ url, fileName, kind, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div onClick={onClose} style={{
      position:'fixed', inset:0, background:'rgba(13,15,26,0.72)', zIndex:1000,
      display:'flex', alignItems:'center', justifyContent:'center', padding:24,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width:'min(1100px, 96vw)', height:'92vh', background:'#fff', borderRadius:12,
        boxShadow:'0 30px 60px rgba(0,0,0,0.35)', display:'flex', flexDirection:'column', overflow:'hidden',
      }}>
        <div style={{ padding:'12px 18px', borderBottom:'1px solid #edf0f7', display:'flex', alignItems:'center', gap:12 }}>
          <div style={{ fontWeight:600, fontSize:14, color:'#0d0f1a', flex:1, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
            📄 {fileName}
          </div>
          <a href={url} download={fileName} className="btn btn-outline btn-sm">⬇ Download</a>
          <button className="btn btn-outline btn-sm" onClick={onClose}>Close</button>
        </div>
        {kind === 'image' ? (
          <div style={{ flex:1, overflow:'auto', background:'#0d0f1a', display:'flex', alignItems:'center', justifyContent:'center' }}>
            <img src={url} alt={fileName} style={{ maxWidth:'100%', maxHeight:'100%', objectFit:'contain' }} />
          </div>
        ) : (
          <iframe src={url} title={fileName} style={{ flex:1, border:'none', width:'100%' }} />
        )}
      </div>
    </div>
  )
}

function RateCardsTab({ vendorCode, canManage }) {
  const toast = useToast()
  const fileInputRef = useRef(null)
  const [cards, setCards] = useState([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [dragOver, setDragOver] = useState(false)
  const [viewer, setViewer] = useState(null)    // { url, fileName, kind }
  const [deletingId, setDeletingId] = useState(null)

  const load = async () => {
    setLoading(true)
    try { setCards(await rateCardApi.list(vendorCode)) }
    catch { setCards([]) }
    finally { setLoading(false) }
  }

  useEffect(() => {
    load()
    return () => { if (viewer?.url) URL.revokeObjectURL(viewer.url) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vendorCode])

  const handleFile = async (file) => {
    if (!file) return
    const ext = extOf(file.name)
    if (!ACCEPTED_RATE_CARD_EXTS.includes(ext)) {
      toast.error('Allowed types: PDF, DOCX, XLSX, JPG, PNG'); return
    }
    if (file.size > RATE_CARD_MAX_BYTES) { toast.error('File exceeds 50MB limit'); return }
    setUploading(true); setProgress(0)
    try {
      await rateCardApi.upload(vendorCode, file, setProgress)
      toast.success('Rate card uploaded')
      await load()
    } catch (err) {
      const msg = err?.response?.data?.detail || 'Upload failed'
      toast.error(msg)
    } finally {
      setUploading(false); setProgress(0)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const onDrop = (e) => {
    e.preventDefault(); setDragOver(false)
    const f = e.dataTransfer.files?.[0]
    if (f) handleFile(f)
  }

  const view = async (rc) => {
    try {
      const blob = await rateCardApi.fetchBlob(vendorCode, rc.id)
      const url = URL.createObjectURL(blob)
      const ext = extOf(rc.file_name)
      // DOCX/XLSX can't render inline — trigger a download instead.
      if (ext === '.docx' || ext === '.xlsx') {
        const a = document.createElement('a')
        a.href = url; a.download = rc.file_name
        document.body.appendChild(a); a.click(); a.remove()
        setTimeout(() => URL.revokeObjectURL(url), 2000)
        return
      }
      if (viewer?.url) URL.revokeObjectURL(viewer.url)
      setViewer({ url, fileName: rc.file_name, kind: isImageExt(ext) ? 'image' : 'pdf' })
    } catch { toast.error('Failed to open file') }
  }

  const closeViewer = () => {
    if (viewer?.url) URL.revokeObjectURL(viewer.url)
    setViewer(null)
  }

  const del = async (rc) => {
    if (!window.confirm(`Delete "${rc.file_name}"? This cannot be undone.`)) return
    setDeletingId(rc.id)
    try {
      await rateCardApi.delete(vendorCode, rc.id)
      toast.success('Rate card deleted')
      await load()
    } catch { toast.error('Failed to delete') }
    finally { setDeletingId(null) }
  }

  return (
    <div>
      <div className="section-divider">📄 Rate Cards</div>

      {canManage && (
        <div
          role="button"
          tabIndex={0}
          onClick={() => !uploading && fileInputRef.current?.click()}
          onKeyDown={e => {
            if (!uploading && (e.key === 'Enter' || e.key === ' ')) {
              e.preventDefault(); fileInputRef.current?.click()
            }
          }}
          onDragOver={e => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          style={{
            border:`2px dashed ${dragOver ? '#f0a500' : '#dde1ec'}`,
            background: dragOver ? '#fffbeb' : '#f8f9fc',
            borderRadius:10, padding:'22px 18px', textAlign:'center',
            transition:'all 0.15s ease', marginBottom:16,
            cursor: uploading ? 'progress' : 'pointer',
            userSelect:'none',
          }}>
          <div style={{ fontSize:28, marginBottom:6 }}>⬆️</div>
          <div style={{ fontSize:14, fontWeight:500, color:'#0d0f1a', marginBottom:4 }}>
            Click to browse, or drop a file here
          </div>
          <div style={{ fontSize:12, color:'#94a3b8' }}>PDF · DOCX · XLSX · JPG · PNG · Max 50 MB</div>
          <input
            ref={fileInputRef} type="file"
            accept=".pdf,.docx,.xlsx,.jpg,.jpeg,.png,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,image/jpeg,image/png"
            hidden
            onChange={e => handleFile(e.target.files?.[0])}
          />
          {uploading && (
            <div style={{ marginTop:14 }} onClick={e => e.stopPropagation()}>
              <div style={{ height:6, background:'#edf0f7', borderRadius:3, overflow:'hidden' }}>
                <div style={{ width:`${progress}%`, height:'100%', background:'#f0a500', transition:'width 0.2s ease' }} />
              </div>
              <div style={{ fontSize:11, color:'#64748b', marginTop:6 }}>Uploading… {progress}%</div>
            </div>
          )}
        </div>
      )}

      {loading ? (
        <div style={{ textAlign:'center', padding:30 }}><Spinner /></div>
      ) : !cards.length ? (
        <div style={{ textAlign:'center', padding:'40px 20px', color:'#94a3b8' }}>
          <div style={{ fontSize:34, marginBottom:6 }}>📭</div>
          <div style={{ fontSize:14 }}>No rate cards uploaded yet</div>
          {canManage && <div style={{ fontSize:12, marginTop:4 }}>Upload a PDF above to get started</div>}
        </div>
      ) : (
        <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
          {cards.map(rc => {
            const b = badgeFor(rc.file_name, rc.mime_type)
            return (
            <div key={rc.id} style={{
              display:'flex', alignItems:'center', gap:12, padding:'10px 14px',
              background:'#fff', border:'1px solid #edf0f7', borderRadius:10,
            }}>
              <div style={{
                width:38, height:38, borderRadius:8, background:b.bg, color:b.fg,
                display:'flex', alignItems:'center', justifyContent:'center', fontWeight:700, fontSize:11, flexShrink:0,
              }}>{b.label}</div>
              <div style={{ flex:1, minWidth:0 }}>
                <div style={{ fontSize:13.5, fontWeight:500, color:'#0d0f1a',
                              overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
                  {rc.file_name}
                </div>
                <div style={{ fontSize:11.5, color:'#94a3b8', marginTop:2 }}>
                  {fmtBytes(rc.file_size)} · Uploaded {fmtDate(rc.uploaded_at)}
                  {rc.uploaded_by ? ` · ${rc.uploaded_by}` : ''}
                </div>
              </div>
              <button className="btn btn-outline btn-sm" onClick={() => view(rc)}>View</button>
              {canManage && (
                <button
                  className="btn btn-outline btn-sm"
                  disabled={deletingId === rc.id}
                  onClick={() => del(rc)}
                  style={{ color:'#dc2626', borderColor:'#fecaca' }}>
                  {deletingId === rc.id ? '…' : '🗑'}
                </button>
              )}
            </div>
          )})}
        </div>
      )}

      {viewer && (
        <FileViewerModal url={viewer.url} fileName={viewer.fileName} kind={viewer.kind} onClose={closeViewer} />
      )}
    </div>
  )
}

function ReliabilityBar({ score }) {
  const color = score >= 80 ? '#16a34a' : score >= 60 ? '#f59e0b' : '#ef4444'
  return (
    <div style={{ display:'flex', alignItems:'center', gap:10 }}>
      <div style={{ flex:1, height:7, background:'#f1f3f8', borderRadius:4, overflow:'hidden' }}>
        <div style={{ width:`${score}%`, height:'100%', background:color, borderRadius:4, transition:'width 0.5s ease' }} />
      </div>
      <span style={{ fontSize:13, fontWeight:600, color, minWidth:36 }}>{score}%</span>
    </div>
  )
}

export default function Vendors() {
  const toast = useToast()
  const { user } = useAuth()
  const canManageRateCards = canDo(user?.role, 'admin')
  const { data: fetchResult, loading, refetch } = useDataFetch(() =>
    Promise.all([vendorApi.getAll(), categoryApi.getAll().catch(() => [])])
  )
  const [vendors, dbCategories] = fetchResult || [[], []]
  const CATEGORIES = dbCategories.length > 0
    ? [...new Set(dbCategories.map(c => c.name))].sort()
    : ['Cleaning Chemicals','Washroom Supplies','Cleaning Tools','Waste Management','Pantry','Electrical','PPE & Safety','Pest Control','Stationery','IT Consumables','Maintenance','Security','Other']

  const [search,   setSearch]   = useState('')
  const [selected, setSelected] = useState(null)       // vendor card click → profile
  const [profile,  setProfile]  = useState(null)       // enriched profile data
  const [profLoad, setProfLoad] = useState(false)
  const [editing,  setEditing]  = useState(false)
  const [editData, setEditData] = useState({})
  const [showCreate, setShowCreate] = useState(false)
  const [newV,     setNewV]     = useState(EMPTY_V)
  const [activeTab, setActiveTab] = useState('overview')

  const filtered = vendors.filter(v => !search ||
    v.name.toLowerCase().includes(search.toLowerCase()) ||
    v.category.toLowerCase().includes(search.toLowerCase()) ||
    (v.city||'').toLowerCase().includes(search.toLowerCase()))

  const openProfile = async (v) => {
    setSelected(v); setActiveTab('overview'); setProfile(null); setProfLoad(true)
    try {
      const p = await vendorApi.getProfile(v.code)
      setProfile(p)
    } catch { setProfile({ stats:{}, recent_orders:[] }) }
    finally { setProfLoad(false) }
  }

  const save = async () => {
    try {
      await vendorApi.update(editData.code, editData); setEditing(false); openProfile(editData); refetch()
      toast.success('Vendor saved!')
    } catch { toast.error('Failed to save vendor') }
  }

  const create = async () => {
    if (!newV.name) return alert('Name required')
    try {
      const code = await codeApi.next('vendor')
      await vendorApi.create({ ...newV, code })
      setShowCreate(false); refetch()
      toast.success('Vendor created!')
    } catch { toast.error('Failed to create vendor') }
  }

  const deleteSelected = async (code) => {
    if (!window.confirm(`Delete ${code}? This cannot be undone.`)) return
    try {
      await deleteApi.vendors([code]); setSelected(null); refetch()
      toast.success('Vendor deleted!')
    } catch { toast.error('Failed to delete vendor') }
  }

  const dm = useDeleteMode(filtered, r => r.code, deleteApi.vendors, refetch)

  if (loading) return <><Header title="Vendor Directory" /><div className="page-content"><Spinner /></div></>

  const TABS = ['overview','orders','services','rate cards']

  return (
    <>
      <Header title="Vendor Directory" subtitle={`${vendors.length} suppliers`}
        actions={<button className="btn btn-accent" onClick={() => setShowCreate(true)}>+ Add Vendor</button>} />
      <div className="page-content">
        {/* Search + delete toggle */}
        <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:18 }}>
          <EditModeToggle dm={dm} />
          <SearchInput value={search} onChange={setSearch} placeholder="Search vendor, category, city…" style={{ flex:1 }} />
        </div>

        {/* Vendor cards grid */}
        <div style={{ display:'grid', gridTemplateColumns:'repeat(2,1fr)', gap:14 }}>
          {filtered.map(v => (
            <div key={v.code} style={{ position:'relative' }}>
              {dm.active && <input type="checkbox" checked={dm.isSelected(v.code)} onChange={() => dm.toggleRow(v.code)}
                onClick={e=>e.stopPropagation()}
                style={{ position:'absolute', top:14, left:14, width:15, height:15, zIndex:10, accentColor:'#ef4444', cursor:'pointer' }} />}
              <div className="vendor-card" onClick={() => dm.active ? dm.toggleRow(v.code) : openProfile(v)}
                style={{ cursor:'pointer', outline: dm.isSelected(v.code)?'2px solid #ef4444':'none' }}>
                <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:14 }}>
                  <div style={{ display:'flex', gap:12, alignItems:'center' }}>
                    <div style={{ width:44, height:44, borderRadius:10, background:'linear-gradient(135deg,#0d0f1a,#3d4a6e)', display:'flex', alignItems:'center', justifyContent:'center', color:'white', fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:18, flexShrink:0 }}>{v.name.charAt(0)}</div>
                    <div>
                      <div style={{ fontWeight:600, fontSize:14.5, color:'#0d0f1a' }}>{v.name}</div>
                      <div style={{ fontSize:12, color:'#94a3b8', marginTop:2 }}>{v.code} · {v.category}</div>
                    </div>
                  </div>
                  <span className="badge" style={{ background:'#f0fdf4', color:'#16a34a' }}>{v.status}</span>
                </div>
                <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:8, marginBottom:12 }}>
                  {[['City',v.city||'—'],['Terms',v.payment_terms||'—'],['Rating',`${v.rating||0}★`]].map(([l,val])=>(
                    <div key={l} style={{ background:'#f8f9fc', borderRadius:7, padding:'7px 8px', textAlign:'center' }}>
                      <div style={{ fontWeight:600, fontSize:13, color:'#0d0f1a' }}>{val}</div>
                      <div style={{ fontSize:10, color:'#94a3b8', textTransform:'uppercase', letterSpacing:'0.04em' }}>{l}</div>
                    </div>
                  ))}
                </div>
                <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', paddingTop:10, borderTop:'1px solid #f1f3f8' }}>
                  <span style={{ fontSize:12, color:'#94a3b8' }}>📞 {v.phone||'—'}</span>
                  <span style={{ fontSize:12, color:'#94a3b8' }}>✉️ {v.email||'—'}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
        {dm.active && dm.selected.size > 0 && (
          <div style={{ position:'sticky', bottom:0, background:'#fef2f2', borderTop:'1px solid #fecaca', padding:'12px 22px', display:'flex', alignItems:'center', gap:12, marginTop:16 }}>
            <span style={{ fontSize:13, color:'#dc2626' }}><strong>{dm.selected.size}</strong> vendors selected</span>
            <div style={{ marginLeft:'auto', display:'flex', gap:8 }}>
              <button onClick={dm.toggle} style={{ padding:'6px 14px', borderRadius:7, border:'1px solid #dde1ec', background:'white', fontSize:12.5, cursor:'pointer' }}>Cancel</button>
              <button onClick={dm.doDelete} disabled={dm.deleting} style={{ padding:'6px 16px', borderRadius:7, border:'none', background:'#ef4444', color:'white', fontSize:12.5, fontWeight:600, cursor:'pointer' }}>
                🗑 {dm.deleting?'Deleting…':`Delete ${dm.selected.size}`}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── VENDOR PROFILE SLIDE-OVER ── */}
      <SlideOver open={!!selected && !editing} onClose={() => setSelected(null)} wide
        title={selected?.name||''} subtitle={`${selected?.code} · ${selected?.category}`}
        footer={<>
          <button className="btn btn-danger btn-sm" onClick={() => deleteSelected(selected.code)} style={{ marginRight:'auto' }}>🗑 Delete</button>
          <button className="btn btn-outline" onClick={() => setSelected(null)}>Close</button>
          <button className="btn btn-accent" onClick={() => { setEditData({...selected}); setEditing(true) }}>✏️ Edit</button>
        </>}>

        {selected && (
          <div>
            {/* Tab bar */}
            <div style={{ display:'flex', gap:4, marginBottom:22, borderBottom:'1px solid #edf0f7', paddingBottom:0 }}>
              {TABS.map(t => (
                <button key={t} onClick={() => setActiveTab(t)} style={{
                  padding:'8px 16px', border:'none', background:'none', cursor:'pointer',
                  fontSize:13, fontWeight:500, textTransform:'capitalize',
                  color: activeTab===t ? '#0d0f1a' : '#94a3b8',
                  borderBottom: activeTab===t ? '2px solid #f0a500' : '2px solid transparent',
                  marginBottom:-1,
                }}>{t}</button>
              ))}
            </div>

            {/* OVERVIEW TAB */}
            {activeTab==='overview' && (
              <div>
                <div className="section-divider">📋 Contact & Details</div>
                <div className="info-grid" style={{ marginBottom:20 }}>
                  {[['Code',selected.code],['City',selected.city],['Address',selected.address],['Contact',selected.contact_person],['Phone',selected.phone],['Email',selected.email],['GST',selected.gst_no],['PAN',selected.pan],['Payment',selected.payment_terms],['Status',selected.status]].map(([l,v])=>(
                    <div key={l} className="info-item"><div className="info-label">{l}</div><div className="info-value">{v||'—'}</div></div>
                  ))}
                </div>

                {profLoad ? <div style={{ textAlign:'center', padding:30 }}><Spinner /></div> : profile && (
                  <>
                    <div className="section-divider">📊 Performance Stats</div>
                    <div style={{ display:'grid', gridTemplateColumns:'repeat(2,1fr)', gap:12, marginBottom:20 }}>
                      {[
                        { l:'Total POs', v:profile.stats.total_pos||0, ic:'📋' },
                        { l:'Total Ordered', v:fmtCurrency(profile.stats.total_ordered_value||0), ic:'💰' },
                        { l:'On-Time Deliveries', v:profile.stats.on_time_deliveries||0, ic:'🚚' },
                        { l:'Received Value', v:fmtCurrency(profile.stats.total_received_value||0), ic:'✅' },
                      ].map(s => (
                        <div key={s.l} style={{ background:'#f8f9fc', borderRadius:10, padding:'14px 16px', display:'flex', gap:12, alignItems:'center' }}>
                          <span style={{ fontSize:22 }}>{s.ic}</span>
                          <div>
                            <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:18 }}>{s.v}</div>
                            <div style={{ fontSize:12, color:'#94a3b8' }}>{s.l}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="section-divider">🎯 Reliability Score</div>
                    <div style={{ padding:'16px 0 20px' }}>
                      <div style={{ fontSize:12, color:'#64748b', marginBottom:8 }}>Based on POs completed vs total placed</div>
                      <ReliabilityBar score={profile.stats.reliability_score||0} />
                      <div style={{ marginTop:10, fontSize:12, color:'#94a3b8' }}>
                        {profile.stats.reliability_score>=80 ? '✅ Highly reliable vendor' : profile.stats.reliability_score>=60 ? '⚠️ Moderate reliability — monitor closely' : '🔴 Low reliability — consider alternatives'}
                      </div>
                    </div>
                  </>
                )}

                {selected.services_offered && (
                  <>
                    <div className="section-divider">🛠 Services Offered</div>
                    <div style={{ display:'flex', flexWrap:'wrap', gap:8, marginBottom:16 }}>
                      {selected.services_offered.split(',').map(s => s.trim()).filter(Boolean).map(s => (
                        <span key={s} className="badge" style={{ background:'#eff6ff', color:'#3b82f6', fontSize:12 }}>{s}</span>
                      ))}
                    </div>
                  </>
                )}
                {selected.locations_served && (
                  <>
                    <div className="section-divider">📍 Locations Served</div>
                    <div style={{ display:'flex', flexWrap:'wrap', gap:8, marginBottom:16 }}>
                      {selected.locations_served.split(',').map(s => s.trim()).filter(Boolean).map(s => (
                        <span key={s} className="badge" style={{ background:'#f5f3ff', color:'#7c3aed', fontSize:12 }}>{s}</span>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}

            {/* ORDERS TAB */}
            {activeTab==='orders' && (
              <div>
                <div className="section-divider">🛒 Recent Purchase Orders</div>
                {profLoad ? <Spinner /> : !profile?.recent_orders?.length ? (
                  <div style={{ textAlign:'center', padding:40, color:'#94a3b8', fontSize:14 }}>No purchase orders yet</div>
                ) : (
                  <table style={{ width:'100%', borderCollapse:'collapse', fontSize:13 }}>
                    <thead><tr style={{ borderBottom:'2px solid #edf0f7' }}>
                      <th style={{ padding:'8px 12px', textAlign:'left', color:'#64748b', fontWeight:600, fontSize:11, textTransform:'uppercase' }}>PO No</th>
                      <th style={{ padding:'8px 12px', textAlign:'left', color:'#64748b', fontWeight:600, fontSize:11, textTransform:'uppercase' }}>Date</th>
                      <th style={{ padding:'8px 12px', textAlign:'left', color:'#64748b', fontWeight:600, fontSize:11, textTransform:'uppercase' }}>Item</th>
                      <th style={{ padding:'8px 12px', textAlign:'right', color:'#64748b', fontWeight:600, fontSize:11, textTransform:'uppercase' }}>Value</th>
                      <th style={{ padding:'8px 12px', textAlign:'center', color:'#64748b', fontWeight:600, fontSize:11, textTransform:'uppercase' }}>Status</th>
                    </tr></thead>
                    <tbody>
                      {profile.recent_orders.map(o => (
                        <tr key={o.po_no} style={{ borderBottom:'1px solid #f1f3f8' }}>
                          <td style={{ padding:'10px 12px' }}><span className="td-code">{o.po_no}</span></td>
                          <td style={{ padding:'10px 12px', color:'#64748b' }}>{fmtDate(o.po_date)}</td>
                          <td style={{ padding:'10px 12px' }}>{o.item_code}</td>
                          <td style={{ padding:'10px 12px', textAlign:'right', fontFamily:"'Fraunces',serif", fontWeight:600 }}>{fmtCurrency(o.total||0)}</td>
                          <td style={{ padding:'10px 12px', textAlign:'center' }}><StatusBadge status={o.status} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}

            {/* RATE CARDS TAB */}
            {activeTab==='rate cards' && (
              <RateCardsTab vendorCode={selected.code} canManage={canManageRateCards} />
            )}

            {/* SERVICES TAB */}
            {activeTab==='services' && (
              <div>
                <div className="section-divider">🛠 Services & Locations</div>
                <div style={{ padding:'16px', background:'#f8f9fc', borderRadius:10, marginBottom:16 }}>
                  <div style={{ fontSize:13, fontWeight:500, marginBottom:8 }}>Services Offered</div>
                  <div style={{ display:'flex', flexWrap:'wrap', gap:8 }}>
                    {(selected.services_offered||'').split(',').map(s=>s.trim()).filter(Boolean).map(s => (
                      <span key={s} className="badge" style={{ background:'#eff6ff', color:'#3b82f6' }}>{s}</span>
                    ))}
                    {!(selected.services_offered) && <span style={{ color:'#94a3b8', fontSize:13 }}>No services listed — edit vendor to add</span>}
                  </div>
                </div>
                <div style={{ padding:'16px', background:'#f8f9fc', borderRadius:10 }}>
                  <div style={{ fontSize:13, fontWeight:500, marginBottom:8 }}>Locations Served</div>
                  <div style={{ display:'flex', flexWrap:'wrap', gap:8 }}>
                    {(selected.locations_served||'').split(',').map(s=>s.trim()).filter(Boolean).map(s => (
                      <span key={s} className="badge" style={{ background:'#f5f3ff', color:'#7c3aed' }}>{s}</span>
                    ))}
                    {!(selected.locations_served) && <span style={{ color:'#94a3b8', fontSize:13 }}>No locations listed — edit vendor to add</span>}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </SlideOver>

      {/* ── EDIT SLIDE-OVER ── */}
      <SlideOver open={editing} onClose={() => setEditing(false)} title={`Edit: ${editData.name||''}`}
        footer={<>
          <button className="btn btn-outline" onClick={() => setEditing(false)}>Cancel</button>
          <button className="btn btn-accent" onClick={save}>Save Changes</button>
        </>}>
        <FormGrid>
          {[['Code','code',true],['Name','name'],['City','city',false,true],['Contact Person','contact_person',false,true],['Phone','phone',false,true],['Email','email',false,true],['GST No','gst_no',false,true],['PAN','pan',false,true]].map(([label,field,ro,half])=>(
            <FormRow key={field} label={label} half={half}>
              <input className="input" readOnly={!!ro} style={ro?{background:'#f8f9fc',color:'#64748b'}:{}}
                value={editData[field]||''} onChange={e => !ro && setEditData({...editData,[field]:e.target.value})} />
            </FormRow>
          ))}
          <FormRow label="Address">
            <textarea className="input" rows={2} value={editData.address||''} onChange={e => setEditData({...editData, address:e.target.value})} placeholder="Full street address" />
          </FormRow>
          <FormRow label="Category">
            <select className="select" value={editData.category||''} onChange={e=>setEditData({...editData,category:e.target.value})}>
              {CATEGORIES.map(c=><option key={c}>{c}</option>)}
            </select>
          </FormRow>
          <FormRow label="Payment Terms" half>
            <select className="select" value={editData.payment_terms||'Net 30'} onChange={e=>setEditData({...editData,payment_terms:e.target.value})}>
              {['Advance','Net 7','Net 15','Net 30','Net 45','Net 60'].map(t=><option key={t}>{t}</option>)}
            </select>
          </FormRow>
          <FormRow label="Status" half>
            <select className="select" value={editData.status||'Active'} onChange={e=>setEditData({...editData,status:e.target.value})}>
              {['Active','Inactive','Blacklisted'].map(s=><option key={s}>{s}</option>)}
            </select>
          </FormRow>
          <FormRow label="Services Offered (comma separated)">
            <textarea className="input" rows={2} value={editData.services_offered||''} onChange={e=>setEditData({...editData,services_offered:e.target.value})}
              placeholder="e.g. Supply of Consumables, Deep Cleaning, Pest Control" />
          </FormRow>
          <FormRow label="Locations Served (comma separated)">
            <input className="input" value={editData.locations_served||''} onChange={e=>setEditData({...editData,locations_served:e.target.value})}
              placeholder="e.g. MS, CH-1B, STORE-CH" />
          </FormRow>
          <FormRow label="Rating" half>
            <input className="input" type="number" min={0} max={5} step={0.5} value={editData.rating||0} onChange={e=>setEditData({...editData,rating:Number(e.target.value)})} />
          </FormRow>
        </FormGrid>
      </SlideOver>

      {/* ── CREATE SLIDE-OVER ── */}
      <SlideOver open={showCreate} onClose={() => setShowCreate(false)} title="Add New Vendor"
        footer={<>
          <button className="btn btn-outline" onClick={() => setShowCreate(false)}>Cancel</button>
          <button className="btn btn-accent" onClick={create}>Create Vendor</button>
        </>}>
        <FormGrid>
          <FormRow label="Name *">
            <input className="input" value={newV.name} onChange={e=>setNewV({...newV,name:e.target.value})} placeholder="Vendor name" />
          </FormRow>
          <FormRow label="Category">
            <select className="select" value={newV.category} onChange={e=>setNewV({...newV,category:e.target.value})}>
              {CATEGORIES.map(c=><option key={c}>{c}</option>)}
            </select>
          </FormRow>
          {[['Contact Person','contact_person',false,true],['Phone','phone',false,true],['Email','email',false,true],['City','city',false,true],['GST No','gst_no',false,true],['PAN','pan',false,true]].map(([label,field,ro,half])=>(
            <FormRow key={field} label={label} half={half}>
              <input className="input" value={newV[field]||''} onChange={e=>setNewV({...newV,[field]:e.target.value})} />
            </FormRow>
          ))}
          <FormRow label="Address">
            <textarea className="input" rows={2} value={newV.address||''} onChange={e=>setNewV({...newV, address:e.target.value})} placeholder="Full street address" />
          </FormRow>
          <FormRow label="Payment Terms" half>
            <select className="select" value={newV.payment_terms} onChange={e=>setNewV({...newV,payment_terms:e.target.value})}>
              {['Advance','Net 7','Net 15','Net 30','Net 45','Net 60'].map(t=><option key={t}>{t}</option>)}
            </select>
          </FormRow>
          <FormRow label="Services Offered">
            <textarea className="input" rows={2} value={newV.services_offered||''} onChange={e=>setNewV({...newV,services_offered:e.target.value})}
              placeholder="Supply of Consumables, Deep Cleaning, Pest Control…" />
          </FormRow>
          <FormRow label="Locations Served">
            <input className="input" value={newV.locations_served||''} onChange={e=>setNewV({...newV,locations_served:e.target.value})}
              placeholder="MS, CH-1B, STORE-CH…" />
          </FormRow>
        </FormGrid>
      </SlideOver>
    </>
  )
}
