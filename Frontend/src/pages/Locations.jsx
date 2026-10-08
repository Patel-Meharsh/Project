import { useState } from 'react'
import useDataFetch from '../lib/useDataFetch'
import { useToast } from '../components/Toast'
import DeleteToolbar, { EditModeToggle, SelectTh, SelectTd } from '../components/DeleteToolbar'
import { useDeleteMode } from '../hooks/useDeleteMode'
import { deleteApi } from '../lib/api'
import { locationApi } from '../lib/api'
import { Spinner, FormRow, FormGrid, SearchInput } from '../components/UI'
import SlideOver from '../components/SlideOver'
import Header from '../components/Header'
import { fmtNum, fmtCurrency } from '../lib/utils'

const SERVICE_TYPES = ['Deep Cleaning','Daily Cleaning','Pest Control','Security','Housekeeping','Landscaping','Waste Disposal','AC Maintenance','Electrical Maintenance','Other']

export default function Locations() {
  const toast = useToast()
  const { data: fetchedLocs, loading, refetch } = useDataFetch(() => locationApi.getAll())
  const locs = fetchedLocs || []

  const [selected, setSelected] = useState(null)
  const [editing, setEditing] = useState(false)
  const [editData, setEditData] = useState({})
  const [showCreate, setShowCreate] = useState(false)
  const [showAddService, setShowAddService] = useState(false)
  const [svcForm, setSvcForm] = useState({ service_type:'Deep Cleaning', vendor_name:'', vendor_contact:'', monthly_cost:0, scope:'', contract_start:'', contract_end:'', status:'Active' })
  const [newLoc, setNewLoc] = useState({ code:'', name:'', city:'', type:'Office', loc_type:'SITE', parent_store:'', contact_person:'', phone:'', area_sqft:0, headcount:0, num_washrooms:0, num_urinals:0, num_wcs:0, num_wash_basins:0, num_pantries:0, num_meeting_rooms:0, num_ac_units:0, num_fans:0, status:'Active' })

  const deleteSelected = async (code) => {
    if (!window.confirm(`Delete ${code}? This cannot be undone.`)) return
    try {
      await deleteApi.locations([code])
      setSelected(null); refetch()
      toast.success('Location deleted!')
    } catch { toast.error('Failed to delete location') }
  }

  const startEdit = (loc) => { setEditData({...loc}); setEditing(true) }
  const saveEdit = async () => {
    try {
      await locationApi.update(editData.code, editData)
      setEditing(false); setSelected({...editData}); refetch()
      toast.success('Location saved!')
    } catch { toast.error('Failed to save location') }
  }
  const createLoc = async () => {
    if (!newLoc.code || !newLoc.name) return alert('Code and Name required')
    try {
      await locationApi.create(newLoc)
      setShowCreate(false); refetch()
      toast.success('Location created!')
    } catch { toast.error('Failed to create location') }
  }
  const addService = async () => {
    if (!selected) return
    try {
      await locationApi.addService(selected.code, svcForm)
      const updated = await locationApi.get(selected.code)
      setSelected(updated); refetch()
      setShowAddService(false)
      setSvcForm({ service_type:'Deep Cleaning', vendor_name:'', vendor_contact:'', monthly_cost:0, scope:'', contract_start:'', contract_end:'', status:'Active' })
      toast.success('Service added!')
    } catch { toast.error('Failed to add service') }
  }
  const totalArea = locs.reduce((s,l) => s+(l.area_sqft||0), 0)
  const totalHead = locs.reduce((s,l) => s+(l.headcount||0), 0)

  const filtered_locs = locs.filter(l => !l._search || true) // all locs for delete selection
  const dm = useDeleteMode(locs, r => r.code, deleteApi.locations, refetch)

  if (loading) return <><Header title="Locations" /><div className="page-content"><Spinner /></div></>

  const F = ({ label, field, type='text', half }) => (
    <FormRow label={label} half={half}>
      <input className="input" type={type} value={editData[field]||''} onChange={e => setEditData({...editData, [field]: type==='number'?Number(e.target.value):e.target.value})} />
    </FormRow>
  )

  return (
    <>
      <Header title="Locations" subtitle={`${locs.length} active sites · ${fmtNum(totalArea)} sq ft · ${fmtNum(totalHead)} people`}
        actions={<button className="btn btn-accent" onClick={() => setShowCreate(true)}>+ Add Location</button>} />
      <div className="page-content">
        {/* KPIs */}
        <div className="kpi-grid" style={{ gridTemplateColumns:'repeat(4,1fr)', marginBottom:24 }}>
          {[{l:'Total Sites',v:locs.length,c:'blue',ic:'📍'},{l:'Total Area',v:`${fmtNum(totalArea)} sqft`,c:'green',ic:'🏢'},{l:'Headcount',v:fmtNum(totalHead),c:'purple',ic:'👥'},{l:'Monthly Budget',v:'₹0',c:'amber',ic:'💰'}].map(k=>(
            <div key={k.l} className={`kpi-card ${k.c}`}><div className={`kpi-icon ${k.c}`}>{k.ic}</div><div className="kpi-value">{k.v}</div><div className="kpi-label">{k.l}</div></div>
          ))}
        </div>
        {/* Location Cards */}
        <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:16 }}>
          {locs.map(loc => {
            const svcCost = (loc.third_party_services||[]).reduce((s,sv)=>s+(sv.monthly_cost||0),0)
            return (
              <div key={loc.code} style={{ position:'relative' }}>
                {dm.active && <input type="checkbox" checked={dm.isSelected(loc.code)} onChange={() => dm.toggleRow(loc.code)}
                  onClick={e=>e.stopPropagation()}
                  style={{ position:'absolute', top:12, left:12, width:15, height:15, zIndex:10, accentColor:'#ef4444', cursor:'pointer' }} />}
              <div className="location-card fade-in" onClick={() => dm.active ? dm.toggleRow(loc.code) : setSelected(loc)}
                style={{ outline: dm.isSelected(loc.code)?'2px solid #ef4444':'none' }}>
                <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:14 }}>
                  <div>
                    <div style={{ fontFamily:"'Fraunces',serif", fontSize:16, fontWeight:600, color:'#0d0f1a' }}>{loc.name}</div>
                    <div style={{ fontSize:12, color:'#94a3b8', marginTop:2 }}>{loc.city} · {loc.type}</div>
                  </div>
                  <div style={{ display:'flex', flexDirection:'column', alignItems:'flex-end', gap:4 }}>
                    <span className="badge" style={{ background:loc.type==='Store'?'#fefce8':loc.type==='Branch'?'#eff6ff':'#f0fdf4', color:loc.type==='Store'?'#d97706':loc.type==='Branch'?'#3b82f6':'#16a34a' }}>{loc.type}</span>
                    <span style={{ fontSize:10, fontWeight:600, borderRadius:4, padding:'2px 7px',
                      background: loc.loc_type==='STORE' ? '#dcfce7' : '#f1f5f9',
                      color:      loc.loc_type==='STORE' ? '#16a34a' : '#64748b',
                    }}>{loc.loc_type || 'SITE'}</span>
                  </div>
                </div>
                <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:8, marginBottom:12 }}>
                  {[['Area',`${fmtNum(loc.area_sqft)}`,'+sqft'],['People',loc.headcount,'👥'],['Washrooms',loc.num_washrooms,'🚿'],['ACs',loc.num_ac_units,'❄️'],['Fans',loc.num_fans,'💨'],['Pantries',loc.num_pantries,'☕']].map(([l,v,ic])=>(
                    <div key={l} style={{ background:'#f8f9fc', borderRadius:7, padding:'8px 6px', textAlign:'center' }}>
                      <div style={{ fontFamily:"'Fraunces',serif", fontWeight:600, fontSize:14, color:'#0d0f1a' }}>{v}</div>
                      <div style={{ fontSize:10, color:'#94a3b8', textTransform:'uppercase', letterSpacing:'0.04em' }}>{l}</div>
                    </div>
                  ))}
                </div>
                {(loc.third_party_services||[]).length > 0 && (
                  <div style={{ display:'flex', gap:6, flexWrap:'wrap', marginBottom:10 }}>
                    {loc.third_party_services.map((s,i) => <span key={i} className="badge" style={{ background:'#f5f3ff', color:'#7c3aed', fontSize:11 }}>{s.service_type}</span>)}
                  </div>
                )}
                <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', paddingTop:10, borderTop:'1px solid #f1f3f8' }}>
                  <span style={{ fontSize:12, color:'#94a3b8' }}>📞 {loc.phone ? String(loc.phone).replace(/\.0$/, '') : ''}</span>
                  {svcCost > 0 && <span style={{ fontSize:12, color:'#7c3aed' }}>🤝 {fmtCurrency(svcCost)}/mo</span>}
                </div>
              </div>
              </div>
            )
          })}
        </div>

        {/* ── Detail/Edit SlideOver ── */}
        <SlideOver open={!!selected && !editing} onClose={() => setSelected(null)} title={selected?.name} subtitle={`${selected?.city} · ${selected?.type}`}
          footer={<><button className="btn btn-danger btn-sm" onClick={() => deleteSelected(selected.code)} style={{marginRight:'auto'}}>🗑 Delete</button><button className="btn btn-outline" onClick={() => setSelected(null)}>Close</button><button className="btn btn-accent" onClick={() => startEdit(selected)}>✏️ Edit</button></>}
          wide>
          {selected && (
            <div>
              <div className="section-divider">📍 Location Details</div>
              <div className="info-grid" style={{ marginBottom:20 }}>
                {[['Code',selected.code],['Type',selected.type],['City',selected.city],['Contact',selected.contact_person],['Phone', selected.phone ? String(selected.phone).replace(/\.0$/, '') : '—'],['Status',selected.status]].map(([l,v])=>(
                  <div key={l} className="info-item"><div className="info-label">{l}</div><div className="info-value">{v||'—'}</div></div>
                ))}
              </div>
              <div className="section-divider">📐 Area & Headcount</div>
              <div style={{ display:'grid', gridTemplateColumns:'repeat(2,1fr)', gap:10, marginBottom:20 }}>
                {[['Area (sqft)',fmtNum(selected.area_sqft)],['Headcount',selected.headcount]].map(([l,v])=>(
                  <div key={l} className="info-item"><div className="info-label">{l}</div><div className="info-value" style={{ fontFamily:"'Fraunces',serif", fontSize:20, fontWeight:600 }}>{v}</div></div>
                ))}
              </div>
              <div className="section-divider">🏗️ Fixtures</div>
              <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:10, marginBottom:20 }}>
                {[['Washrooms',selected.num_washrooms],['Urinals',selected.num_urinals],['WCs',selected.num_wcs],['Basins',selected.num_wash_basins],['Pantries',selected.num_pantries],['Meeting Rooms',selected.num_meeting_rooms],['AC Units',selected.num_ac_units],['Fans',selected.num_fans]].map(([l,v])=>(
                  <div key={l} style={{ background:'#f8f9fc', borderRadius:8, padding:12, textAlign:'center' }}>
                    <div style={{ fontFamily:"'Fraunces',serif", fontSize:22, fontWeight:600, color:'#0d0f1a' }}>{v}</div>
                    <div style={{ fontSize:11, color:'#94a3b8', marginTop:2 }}>{l}</div>
                  </div>
                ))}
              </div>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:12 }}>
                <div className="section-divider" style={{ margin:0 }}>🤝 Third-Party Services</div>
                <button className="btn btn-outline btn-sm" onClick={() => setShowAddService(true)}>+ Add Service</button>
              </div>
              {(selected.third_party_services||[]).length === 0 ? (
                <div style={{ textAlign:'center', padding:24, color:'#94a3b8', fontSize:13, background:'#f8f9fc', borderRadius:10 }}>No third-party services. Click "Add Service" to add cleaning, security etc.</div>
              ) : (
                (selected.third_party_services||[]).map((svc,i) => (
                  <div key={i} style={{ border:'1px solid #edf0f7', borderRadius:10, padding:14, marginBottom:10 }}>
                    <div style={{ display:'flex', justifyContent:'space-between', marginBottom:8 }}>
                      <span style={{ fontWeight:600, fontSize:14 }}>{svc.service_type}</span>
                      <span className="badge" style={{ background:'#f5f3ff', color:'#7c3aed' }}>{fmtCurrency(svc.monthly_cost)}/mo</span>
                    </div>
                    <div style={{ fontSize:13, color:'#64748b' }}>{svc.vendor_name} · {svc.vendor_contact}</div>
                    {svc.scope && <div style={{ fontSize:12, color:'#94a3b8', marginTop:6 }}>{svc.scope}</div>}
                  </div>
                ))
              )}
            </div>
          )}
        </SlideOver>

        {/* ── Edit SlideOver ── */}
        <SlideOver open={editing} onClose={() => setEditing(false)} title={`Edit: ${editData.name||''}`}
          footer={<><button className="btn btn-outline" onClick={() => setEditing(false)}>Cancel</button><button className="btn btn-accent" onClick={saveEdit}>Save Changes</button></>}
          wide>
          <FormGrid>
            <FormRow label="Location Name"><input className="input" value={editData.name||''} onChange={e => setEditData({...editData, name:e.target.value})} /></FormRow>
            <FormRow label="City" half><input className="input" value={editData.city||''} onChange={e => setEditData({...editData, city:e.target.value})} /></FormRow>
            <FormRow label="Type" half><select className="select" value={editData.type||'Office'} onChange={e => setEditData({...editData, type:e.target.value})}>{['Office','Branch','Store','Warehouse'].map(t=><option key={t}>{t}</option>)}</select></FormRow>
            <FormRow label="Inventory Role" half>
              <select className="select" value={editData.loc_type||'SITE'} onChange={e => setEditData({...editData, loc_type:e.target.value, parent_store: e.target.value==='STORE' ? '' : (editData.parent_store||'')})}>
                <option value="SITE">SITE (consumption)</option>
                <option value="STORE">STORE (holds stock)</option>
              </select>
            </FormRow>
            {(editData.loc_type||'SITE') === 'SITE' && (
              <FormRow label="Parent Store" half>
                <select className="select" value={editData.parent_store||''} onChange={e => setEditData({...editData, parent_store:e.target.value})}>
                  <option value="">— Select store —</option>
                  {locs.filter(l => l.loc_type==='STORE').map(l => <option key={l.code} value={l.code}>{l.code} — {l.name}</option>)}
                </select>
              </FormRow>
            )}
            <FormRow label="Contact Person" half><input className="input" value={editData.contact_person||''} onChange={e => setEditData({...editData, contact_person:e.target.value})} /></FormRow>
            <FormRow label="Phone" half><input className="input" value={editData.phone||''} onChange={e => setEditData({...editData, phone:e.target.value})} /></FormRow>
            <div className="section-divider" style={{ width:'100%' }}>Area & Headcount</div>
            <FormRow label="Area (sq ft)" half><input className="input" type="number" value={editData.area_sqft||0} onChange={e => setEditData({...editData, area_sqft:Number(e.target.value)})} /></FormRow>
            <FormRow label="Headcount" half><input className="input" type="number" value={editData.headcount||0} onChange={e => setEditData({...editData, headcount:Number(e.target.value)})} /></FormRow>
            <div className="section-divider" style={{ width:'100%' }}>Fixtures (affects budget calculation)</div>
            {[['Washrooms','num_washrooms'],['Urinals','num_urinals'],['WCs','num_wcs'],['Basins','num_wash_basins'],['Pantries','num_pantries'],['Meeting Rooms','num_meeting_rooms'],['AC Units','num_ac_units'],['Fans','num_fans']].map(([l,f])=>(
              <FormRow key={f} label={l} half><input className="input" type="number" value={editData[f]||0} onChange={e => setEditData({...editData, [f]:Number(e.target.value)})} /></FormRow>
            ))}
          </FormGrid>
        </SlideOver>

        {/* ── Create Location ── */}
        <SlideOver open={showCreate} onClose={() => setShowCreate(false)} title="Add New Location"
          footer={<><button className="btn btn-outline" onClick={() => setShowCreate(false)}>Cancel</button><button className="btn btn-accent" onClick={createLoc}>Create Location</button></>}
          wide>
          <FormGrid>
            <FormRow label="Location Code" half><input className="input" value={newLoc.code} onChange={e => setNewLoc({...newLoc, code:e.target.value.toUpperCase()})} placeholder="e.g. HYD-1A" /></FormRow>
            <FormRow label="Type" half><select className="select" value={newLoc.type} onChange={e => setNewLoc({...newLoc, type:e.target.value})}>{['Office','Branch','Store','Warehouse'].map(t=><option key={t}>{t}</option>)}</select></FormRow>
            <FormRow label="Inventory Role" half>
              <select className="select" value={newLoc.loc_type} onChange={e => setNewLoc({...newLoc, loc_type:e.target.value, parent_store: e.target.value==='STORE' ? '' : newLoc.parent_store})}>
                <option value="SITE">SITE (consumption)</option>
                <option value="STORE">STORE (holds stock)</option>
              </select>
            </FormRow>
            {newLoc.loc_type === 'SITE' && (
              <FormRow label="Parent Store" half>
                <select className="select" value={newLoc.parent_store} onChange={e => setNewLoc({...newLoc, parent_store:e.target.value})}>
                  <option value="">— Select store —</option>
                  {locs.filter(l => l.loc_type==='STORE').map(l => <option key={l.code} value={l.code}>{l.code} — {l.name}</option>)}
                </select>
              </FormRow>
            )}
            <FormRow label="Location Name"><input className="input" value={newLoc.name} onChange={e => setNewLoc({...newLoc, name:e.target.value})} placeholder="e.g. Hyderabad Office 1A" /></FormRow>
            <FormRow label="City" half><input className="input" value={newLoc.city} onChange={e => setNewLoc({...newLoc, city:e.target.value})} /></FormRow>
            <FormRow label="Phone" half><input className="input" value={newLoc.phone} onChange={e => setNewLoc({...newLoc, phone:e.target.value})} /></FormRow>
            <FormRow label="Contact Person"><input className="input" value={newLoc.contact_person} onChange={e => setNewLoc({...newLoc, contact_person:e.target.value})} /></FormRow>
            <FormRow label="Area (sq ft)" half><input className="input" type="number" value={newLoc.area_sqft} onChange={e => setNewLoc({...newLoc, area_sqft:Number(e.target.value)})} /></FormRow>
            <FormRow label="Headcount" half><input className="input" type="number" value={newLoc.headcount} onChange={e => setNewLoc({...newLoc, headcount:Number(e.target.value)})} /></FormRow>
            <div className="section-divider" style={{ width:'100%' }}>Fixtures (for budget calculation)</div>
            {[['Washrooms','num_washrooms'],['Urinals','num_urinals'],['WCs','num_wcs'],['Wash Basins','num_wash_basins'],['Pantries','num_pantries'],['Meeting Rooms','num_meeting_rooms'],['AC Units','num_ac_units'],['Fans','num_fans']].map(([l,f])=>(
              <FormRow key={f} label={l} half><input className="input" type="number" value={newLoc[f]||0} onChange={e => setNewLoc({...newLoc, [f]:Number(e.target.value)})} /></FormRow>
            ))}
          </FormGrid>
        </SlideOver>

        {/* ── Add Service ── */}
        <SlideOver open={showAddService} onClose={() => setShowAddService(false)} title="Add Third-Party Service"
          subtitle={selected ? `For ${selected.name}` : ''}
          footer={<><button className="btn btn-outline" onClick={() => setShowAddService(false)}>Cancel</button><button className="btn btn-accent" onClick={addService}>Add Service</button></>}>
          <FormGrid>
            <FormRow label="Service Type"><select className="select" value={svcForm.service_type} onChange={e => setSvcForm({...svcForm, service_type:e.target.value})}>{SERVICE_TYPES.map(t=><option key={t}>{t}</option>)}</select></FormRow>
            <FormRow label="Vendor / Agency Name"><input className="input" value={svcForm.vendor_name} onChange={e => setSvcForm({...svcForm, vendor_name:e.target.value})} /></FormRow>
            <FormRow label="Contact" half><input className="input" value={svcForm.vendor_contact} onChange={e => setSvcForm({...svcForm, vendor_contact:e.target.value})} /></FormRow>
            <FormRow label="Monthly Cost (₹)" half><input className="input" type="number" value={svcForm.monthly_cost} onChange={e => setSvcForm({...svcForm, monthly_cost:Number(e.target.value)})} /></FormRow>
            <FormRow label="Contract Start" half><input className="input" type="date" value={svcForm.contract_start} onChange={e => setSvcForm({...svcForm, contract_start:e.target.value})} /></FormRow>
            <FormRow label="Contract End" half><input className="input" type="date" value={svcForm.contract_end} onChange={e => setSvcForm({...svcForm, contract_end:e.target.value})} /></FormRow>
            <FormRow label="Scope of Work"><textarea className="input" rows={3} value={svcForm.scope} onChange={e => setSvcForm({...svcForm, scope:e.target.value})} placeholder="e.g. Daily floor mopping, weekly deep cleaning of washrooms..." /></FormRow>
          </FormGrid>
        </SlideOver>
      </div>
        <DeleteToolbar dm={dm} label="locations" />
    </>
  )
}
