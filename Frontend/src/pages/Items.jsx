import { useState } from 'react'
import DeleteToolbar, { EditModeToggle, SelectTh, SelectTd } from '../components/DeleteToolbar'
import { useDeleteMode } from '../hooks/useDeleteMode'
import { deleteApi } from '../lib/api'
import { itemApi, vendorApi, codeApi, categoryApi, masterGroupApi } from '../lib/api'
import { fmtCurrency } from '../lib/utils'
import { SearchInput, Spinner, CategoryDot, FormRow, FormGrid } from '../components/UI'
import SlideOver from '../components/SlideOver'
import Header from '../components/Header'
import useDataFetch from '../lib/useDataFetch'
import { useToast } from '../components/Toast'

const EMPTY_FORM = { code:'', name:'', category:'', sub_category:'', uom:'Liter', brand_tier:'Standard', vendor_code:'', rate:"", gst_pct:18, rol:20, max_stock:100, lead_days:5, status:'Active', master_group_id:'' }

const num = (v) => Number(v) || 0

function F({ label, field, type='text', half, readOnly, children, form, setForm }) {
  return (
    <FormRow label={label} half={half}>
      {children || (
        <input className="input" type={type}
          readOnly={!!readOnly || field === 'code'}
          style={(readOnly || field === 'code') ? { background:'#f8f9fc', color:'#64748b', cursor:'default' } : {}}
          value={form[field] ?? ''}
          onChange={e => (readOnly || field === 'code') ? null : setForm({ ...form, [field]: e.target.value })}
        />
      )}
    </FormRow>
  )
}

export default function Items() {
  const toast = useToast()
  const { data: fetchResult, loading, refetch } = useDataFetch(() =>
    Promise.all([itemApi.getAll(), vendorApi.getAll(), categoryApi.getAll(), masterGroupApi.getAll().catch(() => [])])
  )
  const [items, vendors, categories, masterGroups] = fetchResult || [[], [], [], []]
  const mgMap = Object.fromEntries(masterGroups.map(g => [g.id, g.name]))

  const [search, setSearch] = useState('')
  const [catFilter, setCatFilter] = useState('All')
  const [groupFilter, setGroupFilter] = useState('All')
  const [selected, setSelected] = useState(null)
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [editMode, setEditMode] = useState(false)

  // Inline category creation (no nested modal)
  const [showNewCat, setShowNewCat] = useState(false)
  const [newCatName, setNewCatName] = useState('')
  const [newCatGroup, setNewCatGroup] = useState('')
  const [newCatIsSubOf, setNewCatIsSubOf] = useState('') // parent category name for sub-cat
  const [catSaving, setCatSaving] = useState(false)

  const vMap = Object.fromEntries(vendors.map(v => [v.code, v.name]))

  // Category helpers — filtered by selected master group
  const selectedGroupName = form.master_group_id ? (masterGroups.find(g => g.id === Number(form.master_group_id))?.name || '') : ''
  const filteredCategories = selectedGroupName
    ? categories.filter(c => c.master_group === selectedGroupName)
    : categories
  const getSubCategories = (parentName) => {
    const parent = categories.find(c => c.name === parentName && !c.parent_id)
    return parent ? categories.filter(c => c.parent_id === parent.id) : []
  }
  const unlinkedCategories = categories.filter(c => !c.master_group)

  // Filters
  const groupFilterOptions = ['All', ...new Set(items.map(i => i.master_group_name || mgMap[i.master_group_id] || '').filter(Boolean))]
  const cats = ['All', ...new Set(items.map(i => i.category).filter(Boolean))]
  const filtered = items.filter(i => {
    const ms = !search || i.code.toLowerCase().includes(search.toLowerCase()) || i.name.toLowerCase().includes(search.toLowerCase())
    const gName = i.master_group_name || mgMap[i.master_group_id] || ''
    return ms && (catFilter === 'All' || i.category === catFilter) && (groupFilter === 'All' || gName === groupFilter)
  })

  const openCreate = async () => {
    const code = await codeApi.next('item')
    setForm({ ...EMPTY_FORM, code })
    setEditMode(false); setShowCreate(true)
  }
  const openEdit = (item) => { setForm({...item}); setEditMode(true); setShowCreate(true) }

  const save = async () => {
    if (!form.code || !form.name) return alert('Code and Name are required')
    try {
      if (editMode) await itemApi.update(form.code, form)
      else await itemApi.create(form)
      toast.success(editMode ? 'Item updated' : 'Item created')
      setShowCreate(false); setSelected(null); refetch()
    } catch (err) {
      toast.error(editMode ? 'Failed to update item' : 'Failed to create item')
    }
  }

  const createCategory = async () => {
    if (!newCatName.trim()) return
    setCatSaving(true)
    try {
      const parentCat = newCatIsSubOf ? categories.find(c => c.name === newCatIsSubOf && !c.parent_id) : null
      // Auto-assign to currently selected master group (or explicit newCatGroup)
      const groupToAssign = newCatGroup || selectedGroupName || null
      await categoryApi.create({
        name: newCatName.trim(),
        parent_id: parentCat?.id || null,
        master_group: groupToAssign,
      })
      toast.success(`Category "${newCatName}" created`)
      if (parentCat) {
        setForm(f => ({ ...f, sub_category: newCatName.trim() }))
      } else {
        setForm(f => ({ ...f, category: newCatName.trim() }))
      }
      setShowNewCat(false); setNewCatName(''); setNewCatGroup(''); setNewCatIsSubOf('')
      refetch()
    } catch (err) {
      toast.error('Failed to create category: ' + (err?.response?.data?.detail || err.message))
    } finally { setCatSaving(false) }
  }

  const assignExistingCat = async (cat) => {
    try {
      await categoryApi.patch(cat.id, { master_group: selectedGroupName })
      toast.success(`"${cat.name}" assigned to ${selectedGroupName}`)
      setForm(f => ({ ...f, category: cat.name }))
      setShowNewCat(false)
      refetch()
    } catch (err) {
      toast.error('Failed to assign category')
    }
  }

  // Master group prefix mapping for item codes
  const GROUP_PREFIXES = { 'HK Benchmark':'HK', 'Diwali Gifts':'DG', 'Welcome Kit':'WK', 'Stationery':'ST', 'Electrical Refurbished':'EL', 'Electrical':'EL', 'IT Consumables':'IT', 'Maintenance':'MT', 'Pantry':'PT', 'PPE & Safety':'PP', 'Pest Control':'PC' }
  const getPrefixForGroup = (groupId) => {
    const g = masterGroups.find(mg => mg.id === groupId)
    if (!g) return null
    return GROUP_PREFIXES[g.name] || g.name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2)
  }

  const dm = useDeleteMode(filtered, r => r.code, deleteApi.items, refetch)

  if (loading) return <><Header title="Active Items" /><div className="page-content"><Spinner /></div></>

  return (
    <>
      <Header title="Active Item Master" subtitle={`${items.length} items currently in use`}
        actions={<button className="btn btn-accent" onClick={openCreate}>+ Add Item</button>} />
      <div className="page-content">
        {/* Master Group filter */}
        {groupFilterOptions.length > 1 && (
          <div style={{ display:'flex', gap:6, marginBottom:10, flexWrap:'wrap' }}>
            <span style={{ fontSize:11, color:'#94a3b8', alignSelf:'center', marginRight:4 }}>Group:</span>
            {groupFilterOptions.map(g => (
              <button key={g} onClick={() => setGroupFilter(g)} className="btn btn-sm"
                style={{ background: groupFilter===g ? '#1d4ed8' : 'white', color: groupFilter===g ? 'white' : '#374151', border:'1px solid #dde1ec', fontSize:11.5, padding:'3px 10px' }}>
                {g}
              </button>
            ))}
          </div>
        )}

        {/* Category filter pills */}
        <div style={{ display:'flex', gap:8, flexWrap:'wrap', marginBottom:16 }}>
          {cats.map(c => (
            <button key={c} onClick={() => setCatFilter(c)} className="btn btn-sm"
              style={{ background: catFilter===c ? '#0d0f1a' : 'white', color: catFilter===c ? 'white' : '#374151', border: '1px solid #dde1ec' }}>
              {c} {c!=='All' && <span style={{ opacity:0.5, fontSize:11 }}>{items.filter(i=>i.category===c).length}</span>}
            </button>
          ))}
        </div>

        <div className="table-wrap">
          <div className="table-header">
            <span className="table-title">{filtered.length} Items</span>
            <div style={{display:"flex",alignItems:"center",gap:8}}>
              <EditModeToggle dm={dm} />
              <SearchInput value={search} onChange={setSearch} placeholder="Search code or name…" />
            </div>
          </div>
          <div style={{ overflowX:'auto' }}>
            <table>
              <thead><tr>
                <SelectTh dm={dm} />
                <th>Code</th><th>Item Name</th><th>Category</th><th>Group</th><th>UOM</th><th>Brand</th>
                <th style={{ textAlign:'right' }}>Rate</th><th>GST</th>
                <th style={{ textAlign:'right' }}>ROL</th><th>Lead</th><th>Vendor</th><th>Status</th><th></th>
              </tr></thead>
              <tbody>
                {filtered.length === 0 && <tr><td colSpan={14} style={{ textAlign:'center', padding:40, color:'#94a3b8' }}>No items found</td></tr>}
                {filtered.map(i => (
                  <tr key={i.code} onClick={() => setSelected(i)} style={{ cursor:'pointer' }}>
                    <SelectTd dm={dm} id={i.code} />
                    <td><span className="td-code">{i.code}</span></td>
                    <td style={{ fontWeight:500, maxWidth:220 }}>{i.name}</td>
                    <td><CategoryDot category={i.category} /></td>
                    <td style={{ fontSize:12, color:'#64748b' }}>{i.master_group_name || mgMap[i.master_group_id] || '—'}</td>
                    <td style={{ fontSize:13 }}>{i.uom}</td>
                    <td>
                      <span className="badge" style={{ background: i.brand_tier==='Premium'?'#fef9c3':i.brand_tier==='Economy'?'#f1f5f9':'#f0fdf4', color: i.brand_tier==='Premium'?'#854d0e':i.brand_tier==='Economy'?'#64748b':'#166534', fontSize:11 }}>{i.brand_tier}</span>
                    </td>
                    <td style={{ textAlign:'right', fontFamily:"'Fraunces',serif", fontWeight:600 }}>{fmtCurrency(i.rate)}</td>
                    <td style={{ textAlign:'center', fontSize:13, color:'#64748b' }}>{i.gst_pct}%</td>
                    <td style={{ textAlign:'right', fontWeight:500 }}>{i.rol}</td>
                    <td style={{ textAlign:'center', fontSize:13 }}>{i.lead_days}d</td>
                    <td style={{ fontSize:12, color:'#64748b', maxWidth:140 }}>{vMap[i.vendor_code] || i.vendor_code}</td>
                    <td><span className="badge" style={{ background:'#f0fdf4', color:'#16a34a', fontSize:11 }}>{i.status}</span></td>
                    <td><button className="btn btn-outline btn-sm row-action" onClick={e => { e.stopPropagation(); openEdit(i) }}>Edit</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Detail SlideOver */}
        <SlideOver open={!!selected && !showCreate} onClose={() => setSelected(null)} title={selected?.name} subtitle={`${selected?.code} · ${selected?.category}`}
          footer={<><button className="btn btn-outline" onClick={() => setSelected(null)}>Close</button><button className="btn btn-accent" onClick={() => openEdit(selected)}>Edit Item</button></>}>
          {selected && (
            <div>
              <div className="section-divider">Item Details</div>
              <div className="info-grid" style={{ marginBottom:20 }}>
                {[['Code',selected.code],['Category',selected.category],['Sub-Category',selected.sub_category],['Master Group',selected.master_group_name || mgMap[selected.master_group_id] || ''],['UOM',selected.uom],['Brand Tier',selected.brand_tier],['Status',selected.status]].map(([l,v])=>(
                  <div key={l} className="info-item"><div className="info-label">{l}</div><div className="info-value">{v||'—'}</div></div>
                ))}
              </div>
              <div className="section-divider">Pricing</div>
              <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:10, marginBottom:20 }}>
                {[['Rate',fmtCurrency(selected.rate)],['GST',`${selected.gst_pct}%`],['Rate incl. GST',fmtCurrency(selected.rate*(1+selected.gst_pct/100))]].map(([l,v])=>(
                  <div key={l} style={{ background:'#f8f9fc', borderRadius:8, padding:14, textAlign:'center' }}>
                    <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:18, color:'#0d0f1a' }}>{v}</div>
                    <div style={{ fontSize:11, color:'#94a3b8', marginTop:3 }}>{l}</div>
                  </div>
                ))}
              </div>
              <div className="section-divider">Stock Controls</div>
              <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:10 }}>
                {[['Reorder Level',selected.rol],['Max Stock',selected.max_stock],['Lead Days',`${selected.lead_days} days`]].map(([l,v])=>(
                  <div key={l} style={{ background:'#f8f9fc', borderRadius:8, padding:14, textAlign:'center' }}>
                    <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:20, color:'#0d0f1a' }}>{v}</div>
                    <div style={{ fontSize:11, color:'#94a3b8', marginTop:3 }}>{l}</div>
                  </div>
                ))}
              </div>
              <div className="section-divider" style={{ marginTop:20 }}>Vendor</div>
              <div className="info-item"><div className="info-label">Preferred Vendor</div><div className="info-value">{vMap[selected.vendor_code] || selected.vendor_code}</div></div>
            </div>
          )}
        </SlideOver>

        {/* Create / Edit SlideOver */}
        <SlideOver open={showCreate} onClose={() => setShowCreate(false)} title={editMode ? `Edit: ${form.name}` : 'Add New Item'}
          footer={<><button className="btn btn-outline" onClick={() => setShowCreate(false)}>Cancel</button><button className="btn btn-accent" onClick={save}>{editMode ? 'Save Changes' : 'Create Item'}</button></>}
          wide>
          <FormGrid>
            <F form={form} setForm={setForm} label="Item Code" field="code" half />
            <F form={form} setForm={setForm} label="Status" half>
              <select className="select" value={form.status} onChange={e=>setForm({...form,status:e.target.value})}>
                {['Active','Inactive','Discontinued'].map(s=><option key={s}>{s}</option>)}
              </select>
            </F>
            <F form={form} setForm={setForm} label="Item Name" field="name" />

            {/* Master Group — drives item code prefix */}
            <FormRow label="Master Group *" half>
              <select className="select" value={form.master_group_id || ''} onChange={async e => {
                const gid = e.target.value ? Number(e.target.value) : ''
                const pfx = gid ? getPrefixForGroup(gid) : null
                let newCode = form.code
                if (pfx && !editMode) {
                  try { newCode = await codeApi.next('item', pfx) } catch {}
                }
                setForm(f => ({...f, master_group_id: gid, code: newCode, category: '', sub_category: ''}))
                setShowNewCat(false)
              }}>
                <option value="">— Select —</option>
                {masterGroups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
              </select>
            </FormRow>

            {/* Category — filtered by selected Master Group */}
            <FormRow label="Category" half>
              <select className="select" value={form.category}
                disabled={!selectedGroupName}
                onChange={e => {
                  const v = e.target.value
                  if (v === '__new__') { setNewCatIsSubOf(''); setShowNewCat(true); return }
                  setForm({...form, category: v, sub_category: ''})
                }}>
                <option value="">{selectedGroupName ? '— Select category —' : '— Select master group first —'}</option>
                {filteredCategories.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
                {/* Show current value even if not in filtered list (edit mode compat) */}
                {form.category && !filteredCategories.find(c => c.name === form.category) && (
                  <option value={form.category}>{form.category}</option>
                )}
                {selectedGroupName && <option value="__new__">+ Create New Category</option>}
              </select>
            </FormRow>

            {/* Inline new category + assign existing */}
            {showNewCat && selectedGroupName && (
              <div style={{ gridColumn:'1/-1', background:'#fffbeb', borderRadius:10, border:'1px solid #f59e0b', padding:14, marginBottom:4 }}>
                <div style={{ fontSize:13, fontWeight:600, color:'#92400e', marginBottom:12 }}>
                  {newCatIsSubOf ? `New Sub-Category under "${newCatIsSubOf}"` : `Create category under "${selectedGroupName}"`}
                </div>
                <div style={{ display:'flex', gap:8, alignItems:'flex-end', flexWrap:'wrap', marginBottom: unlinkedCategories.length > 0 ? 14 : 0 }}>
                  <div style={{ flex:1, minWidth:160 }}>
                    <div style={{ fontSize:11, color:'#64748b', marginBottom:3 }}>Category Name</div>
                    <input className="input" value={newCatName} onChange={e => setNewCatName(e.target.value)}
                      placeholder="e.g. Cleaning Chemicals" autoFocus
                      onKeyDown={e => { if (e.key === 'Enter' && newCatName.trim()) createCategory() }}
                      style={{ fontSize:13 }} />
                  </div>
                  <button className="btn btn-accent btn-sm" onClick={createCategory} disabled={catSaving || !newCatName.trim()}
                    style={{ height:36, padding:'0 14px' }}>{catSaving ? '…' : 'Save Category'}</button>
                  <button className="btn btn-outline btn-sm" onClick={() => { setShowNewCat(false); setNewCatName(''); setNewCatGroup(''); setNewCatIsSubOf(''); setForm(f => ({...f, category: f.category === '__new__' ? '' : f.category})) }}
                    style={{ height:36, padding:'0 14px' }}>Cancel</button>
                </div>
                {/* Existing unlinked categories that can be assigned to this group */}
                {!newCatIsSubOf && unlinkedCategories.length > 0 && (
                  <div>
                    <div style={{ fontSize:11, color:'#64748b', marginBottom:6 }}>Or assign an existing category to "{selectedGroupName}":</div>
                    <div style={{ display:'flex', flexWrap:'wrap', gap:6 }}>
                      {unlinkedCategories.map(c => (
                        <button key={c.id} type="button" onClick={() => assignExistingCat(c)}
                          style={{ padding:'3px 10px', fontSize:12, border:'1px solid #d1d5db', borderRadius:20, background:'#fff', cursor:'pointer', color:'#374151' }}>
                          {c.name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Sub-category */}
            <FormRow label="Sub-Category" half>
              <select className="select" value={form.sub_category} onChange={e => {
                const v = e.target.value
                if (v === '__new__') { setNewCatIsSubOf(form.category); setShowNewCat(true); return }
                setForm({...form, sub_category: v})
              }}>
                <option value="">— Select —</option>
                {getSubCategories(form.category).map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
                {form.sub_category && !getSubCategories(form.category).find(c => c.name === form.sub_category) && (
                  <option value={form.sub_category}>{form.sub_category}</option>
                )}
                <option value="__new__">+ Create New Sub-Category</option>
              </select>
            </FormRow>

            <F form={form} setForm={setForm} label="UOM" half>
              <select className="select" value={form.uom} onChange={e=>setForm({...form,uom:e.target.value})}>
                {['Liter','Kg','Piece','Roll','Pack','Pair','Meter','Box','Can','Jar','Set','Bundle'].map(u=><option key={u}>{u}</option>)}
              </select>
            </F>
            <F form={form} setForm={setForm} label="Brand Tier" half>
              <select className="select" value={form.brand_tier} onChange={e=>setForm({...form,brand_tier:e.target.value})}>
                {['Economy','Standard','Premium'].map(b=><option key={b}>{b}</option>)}
              </select>
            </F>
            <F form={form} setForm={setForm} label="Rate (₹)" field="rate" type="number" half />
            <F form={form} setForm={setForm} label="GST %" half>
              <select className="select" value={form.gst_pct} onChange={e=>setForm({...form,gst_pct:Number(e.target.value)})}>
                {[0,5,12,18,28].map(g=><option key={g} value={g}>{g}%</option>)}
              </select>
            </F>
            {num(form.rate) > 0 && <div style={{ gridColumn:'1/-1', background:'#f8f9fc', borderRadius:8, padding:12, fontSize:13, color:'#64748b' }}>Rate incl. GST: <strong style={{ color:'#0d0f1a', fontFamily:"'Fraunces',serif" }}>{fmtCurrency(num(form.rate) * (1 + num(form.gst_pct)/100))}</strong></div>}
            <div className="section-divider" style={{ width:'100%' }}>Stock Controls</div>
            <F form={form} setForm={setForm} label="Reorder Level" field="rol" type="number" half />
            <F form={form} setForm={setForm} label="Max Stock" field="max_stock" type="number" half />
            <F form={form} setForm={setForm} label="Lead Days" field="lead_days" type="number" half />
            <F form={form} setForm={setForm} label="Preferred Vendor" half>
              <select className="select" value={form.vendor_code} onChange={e=>setForm({...form,vendor_code:e.target.value})}>
                <option value="">— Select —</option>
                {vendors.map(v=><option key={v.code} value={v.code}>{v.code} — {v.name}</option>)}
              </select>
            </F>
          </FormGrid>
        </SlideOver>

        {/* Category modal removed — inline form replaces it (see Category section in SlideOver) */}
      </div>
      <DeleteToolbar dm={dm} label="items" />
    </>
  )
}
