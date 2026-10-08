import { useState } from 'react'
import { masterGroupApi, categoryApi } from '../lib/api'
import { Spinner, SearchInput, Modal, FormRow } from '../components/UI'
import SlideOver from '../components/SlideOver'
import Header from '../components/Header'
import useDataFetch from '../lib/useDataFetch'
import { useToast } from '../components/Toast'
import { useAuth } from '../lib/AuthContext'
import { canDo } from '../lib/auth'
import { fmtDate } from '../lib/utils'

export default function MasterGroups() {
  const toast = useToast()
  const { user } = useAuth()
  const isAdmin = canDo(user?.role, 'admin')
  const { data: fetchResult, loading, refetch } = useDataFetch(() =>
    Promise.all([masterGroupApi.getAll(), categoryApi.getAll().catch(() => [])])
  )
  const [groups, allCategories] = fetchResult || [[], []]

  const [search, setSearch] = useState('')
  const [showModal, setShowModal] = useState(false)
  const [editGroup, setEditGroup] = useState(null)
  const [form, setForm] = useState({ name: '', description: '' })
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(null)

  // Detail view
  const [viewGroup, setViewGroup] = useState(null)

  // Inline add-category inside detail view
  const [newCatName, setNewCatName] = useState('')
  const [addingCat, setAddingCat] = useState(false)

  const filtered = groups.filter(g =>
    !search || g.name.toLowerCase().includes(search.toLowerCase()) || (g.description || '').toLowerCase().includes(search.toLowerCase())
  )

  // Categories belonging to the viewed group
  const groupCategories = viewGroup
    ? allCategories.filter(c => c.master_group === viewGroup.name)
    : []

  // Unlinked categories (no master_group assigned)
  const unlinkedCategories = allCategories.filter(c => !c.master_group)

  const openCreate = () => {
    setEditGroup(null)
    setForm({ name: '', description: '' })
    setShowModal(true)
  }

  const openEditModal = (grp) => {
    setEditGroup(grp)
    setForm({ name: grp.name, description: grp.description || '' })
    setShowModal(true)
  }

  const save = async () => {
    if (!form.name.trim()) return alert('Name is required')
    setSaving(true)
    try {
      if (editGroup) {
        await masterGroupApi.update(editGroup.id, form)
        toast.success('Group updated')
      } else {
        await masterGroupApi.create(form)
        toast.success('Group created')
      }
      setShowModal(false); refetch()
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Failed to save')
    } finally { setSaving(false) }
  }

  const handleDelete = async (grp) => {
    if (!confirm(`Delete "${grp.name}"? This cannot be undone.`)) return
    setDeleting(grp.id)
    try {
      await masterGroupApi.delete(grp.id)
      toast.success('Group deleted')
      setViewGroup(null)
      refetch()
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Failed to delete')
    } finally { setDeleting(null) }
  }

  const addCategory = async () => {
    if (!newCatName.trim() || !viewGroup) return
    setAddingCat(true)
    try {
      await categoryApi.create({
        name: newCatName.trim(),
        master_group: viewGroup.name,
      })
      toast.success(`Category "${newCatName}" added to ${viewGroup.name}`)
      setNewCatName('')
      refetch()
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Failed to create category')
    } finally { setAddingCat(false) }
  }

  const deleteCategory = async (cat) => {
    try {
      await categoryApi.delete(cat.id)
      toast.success(`Category "${cat.name}" removed`)
      refetch()
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Failed to delete')
    }
  }

  const assignCategoryToGroup = async (cat) => {
    if (!viewGroup) return
    try {
      await categoryApi.patch(cat.id, { master_group: viewGroup.name })
      toast.success(`"${cat.name}" assigned to ${viewGroup.name}`)
      refetch()
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Failed to assign')
    }
  }

  if (loading) return <><Header title="Master Groups" /><div className="page-content"><Spinner /></div></>

  return (
    <>
      <Header title="Master Groups" subtitle={`${groups.length} groups — organize items by business function`}
        actions={isAdmin && <button className="btn btn-accent" onClick={openCreate}>+ New Group</button>} />
      <div className="page-content">
        {/* KPIs */}
        <div className="kpi-grid" style={{ gridTemplateColumns:'repeat(3,1fr)', marginBottom:20 }}>
          <div className="kpi-card blue">
            <div className="kpi-icon blue">📂</div>
            <div className="kpi-value">{groups.length}</div>
            <div className="kpi-label">Total Groups</div>
          </div>
          <div className="kpi-card green">
            <div className="kpi-icon green">✅</div>
            <div className="kpi-value">{groups.filter(g => g.status === 'Active').length}</div>
            <div className="kpi-label">Active Groups</div>
          </div>
          <div className="kpi-card amber">
            <div className="kpi-icon amber">📦</div>
            <div className="kpi-value">{groups.reduce((s,g) => s + (g.item_count || 0), 0)}</div>
            <div className="kpi-label">Total Items Linked</div>
          </div>
        </div>

        <div className="table-wrap">
          <div className="table-header">
            <span className="table-title">{filtered.length} Group{filtered.length !== 1 ? 's' : ''}</span>
            <SearchInput value={search} onChange={setSearch} placeholder="Search groups…" />
          </div>
          <table>
            <thead><tr>
              <th>Name</th>
              <th>Description</th>
              <th style={{ textAlign:'center' }}>Categories</th>
              <th style={{ textAlign:'center' }}>Items</th>
              <th>Status</th>
              <th>Created</th>
              {isAdmin && <th>Actions</th>}
            </tr></thead>
            <tbody>
              {filtered.length === 0 && (
                <tr><td colSpan={7} style={{ textAlign:'center', padding:40, color:'#94a3b8' }}>
                  {search ? `No results for "${search}"` : 'No groups yet — create your first one'}
                </td></tr>
              )}
              {filtered.map(g => {
                const catCount = allCategories.filter(c => c.master_group === g.name).length
                return (
                  <tr key={g.id} onClick={() => setViewGroup(g)} style={{ cursor:'pointer' }}>
                    <td style={{ fontWeight:600, fontSize:14 }}>{g.name}</td>
                    <td style={{ fontSize:13, color:'#64748b', maxWidth:300 }}>{g.description || '—'}</td>
                    <td style={{ textAlign:'center' }}>
                      <span style={{ background:'#f5f3ff', color:'#7c3aed', fontWeight:600, fontSize:12, padding:'2px 10px', borderRadius:99 }}>
                        {catCount}
                      </span>
                    </td>
                    <td style={{ textAlign:'center' }}>
                      <span style={{ background:'#eff6ff', color:'#1d4ed8', fontWeight:600, fontSize:12, padding:'2px 10px', borderRadius:99 }}>
                        {g.item_count || 0}
                      </span>
                    </td>
                    <td>
                      <span className="badge" style={{ background: g.status==='Active' ? '#f0fdf4' : '#f8fafc', color: g.status==='Active' ? '#16a34a' : '#94a3b8', fontSize:11 }}>
                        {g.status}
                      </span>
                    </td>
                    <td style={{ fontSize:12, color:'#94a3b8' }}>{g.created_at ? fmtDate(g.created_at) : '—'}</td>
                    {isAdmin && (
                      <td onClick={e => e.stopPropagation()}>
                        <div style={{ display:'flex', gap:6 }}>
                          <button className="btn btn-outline btn-sm" onClick={() => openEditModal(g)}>Edit</button>
                          <button className="btn btn-outline btn-sm" onClick={() => handleDelete(g)} disabled={deleting === g.id}
                            style={{ color:'#dc2626', borderColor:'#fecaca' }}>
                            {deleting === g.id ? '…' : 'Delete'}
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Detail SlideOver (row click) ── */}
      <SlideOver
        open={!!viewGroup}
        onClose={() => { setViewGroup(null); setNewCatName('') }}
        title={viewGroup?.name}
        subtitle="Master Group Details"
        wide
        footer={isAdmin && (
          <div style={{ display:'flex', gap:8 }}>
            <button className="btn btn-outline" onClick={() => { setViewGroup(null); setNewCatName('') }}>Close</button>
            <button className="btn btn-accent" onClick={() => { const g = viewGroup; setViewGroup(null); openEditModal(g) }}>Edit Group</button>
          </div>
        )}
      >
        {viewGroup && (
          <>
            {/* Group info */}
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'10px 20px', marginBottom:20 }}>
              {[
                { label:'Status', value: <span className="badge" style={{ background: viewGroup.status==='Active'?'#f0fdf4':'#f8fafc', color: viewGroup.status==='Active'?'#16a34a':'#94a3b8' }}>{viewGroup.status}</span> },
                { label:'Items Linked', value: viewGroup.item_count || 0 },
                { label:'Created', value: viewGroup.created_at ? fmtDate(viewGroup.created_at) : '—' },
                { label:'Updated', value: viewGroup.updated_at ? fmtDate(viewGroup.updated_at) : '—' },
              ].map(({label, value}) => (
                <div key={label}>
                  <div style={{ fontSize:11, color:'#94a3b8', marginBottom:2 }}>{label}</div>
                  <div style={{ fontSize:13.5, fontWeight:500, color:'#0d0f1a' }}>{value}</div>
                </div>
              ))}
              {viewGroup.description && (
                <div style={{ gridColumn:'1/-1' }}>
                  <div style={{ fontSize:11, color:'#94a3b8', marginBottom:2 }}>Description</div>
                  <div style={{ fontSize:13, color:'#475569' }}>{viewGroup.description}</div>
                </div>
              )}
            </div>

            {/* Categories under this group */}
            <div style={{ marginTop:8 }}>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:12 }}>
                <div style={{ fontSize:14, fontWeight:600, color:'#0d0f1a' }}>
                  Categories ({groupCategories.length})
                </div>
              </div>

              {groupCategories.length === 0 && (
                <div style={{ padding:'20px 0', textAlign:'center', color:'#94a3b8', fontSize:13 }}>
                  No categories yet — add one below
                </div>
              )}

              <div style={{ display:'flex', flexDirection:'column', gap:6, marginBottom:16 }}>
                {groupCategories.map(cat => (
                  <div key={cat.id} style={{
                    display:'flex', alignItems:'center', justifyContent:'space-between',
                    padding:'10px 14px', border:'1px solid #edf0f7', borderRadius:8, background:'#fafbfc'
                  }}>
                    <div>
                      <div style={{ fontWeight:500, fontSize:13.5, color:'#0d0f1a' }}>{cat.name}</div>
                      {cat.description && <div style={{ fontSize:11.5, color:'#94a3b8', marginTop:1 }}>{cat.description}</div>}
                    </div>
                    {isAdmin && (
                      <button onClick={() => deleteCategory(cat)} title="Remove category"
                        style={{ background:'none', border:'none', cursor:'pointer', color:'#dc2626', fontSize:15, padding:'2px 6px', lineHeight:1 }}>×</button>
                    )}
                  </div>
                ))}
              </div>

              {/* Inline add category + assign existing unlinked */}
              {isAdmin && (
                <div style={{ background:'#fffbeb', borderRadius:10, border:'1px solid #f59e0b', padding:14 }}>
                  <div style={{ fontSize:13, fontWeight:600, color:'#92400e', marginBottom:10 }}>Add Category to "{viewGroup.name}"</div>

                  {/* Create new */}
                  <div style={{ display:'flex', gap:8, alignItems:'flex-end', marginBottom: unlinkedCategories.length > 0 ? 14 : 0 }}>
                    <div style={{ flex:1 }}>
                      <div style={{ fontSize:11, color:'#64748b', marginBottom:3 }}>New Category Name</div>
                      <input className="input" value={newCatName} onChange={e => setNewCatName(e.target.value)}
                        placeholder="e.g. Cleaning Chemicals"
                        onKeyDown={e => { if (e.key === 'Enter' && newCatName.trim()) addCategory() }}
                        style={{ fontSize:13 }} />
                    </div>
                    <button className="btn btn-accent btn-sm" onClick={addCategory}
                      disabled={addingCat || !newCatName.trim()}
                      style={{ height:36, padding:'0 16px', whiteSpace:'nowrap' }}>
                      {addingCat ? '…' : '+ Create'}
                    </button>
                  </div>

                  {/* Assign existing unlinked categories */}
                  {unlinkedCategories.length > 0 && (
                    <div>
                      <div style={{ fontSize:11, color:'#64748b', marginBottom:6 }}>Or assign an existing unlinked category:</div>
                      <div style={{ display:'flex', flexWrap:'wrap', gap:6 }}>
                        {unlinkedCategories.map(c => (
                          <button key={c.id} type="button" onClick={() => assignCategoryToGroup(c)}
                            style={{ padding:'4px 12px', fontSize:12, border:'1px solid #d1d5db', borderRadius:20, background:'#fff', cursor:'pointer', color:'#374151', transition:'all 0.15s' }}
                            onMouseEnter={e => { e.currentTarget.style.background='#f0fdf4'; e.currentTarget.style.borderColor='#10b981' }}
                            onMouseLeave={e => { e.currentTarget.style.background='#fff'; e.currentTarget.style.borderColor='#d1d5db' }}>
                            + {c.name}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </SlideOver>

      {/* ── Create / Edit Modal ── */}
      <Modal open={showModal} onClose={() => setShowModal(false)}
        title={editGroup ? `Edit: ${editGroup.name}` : 'Create Master Group'}
        footer={<>
          <button className="btn btn-outline" onClick={() => setShowModal(false)}>Cancel</button>
          <button className="btn btn-accent" onClick={save} disabled={saving}>{saving ? 'Saving…' : editGroup ? 'Save Changes' : 'Create Group'}</button>
        </>}>
        <FormRow label="Group Name *">
          <input className="input" value={form.name} onChange={e => setForm({...form, name: e.target.value})} placeholder="e.g. HK Benchmark, Electrical" autoFocus />
        </FormRow>
        <FormRow label="Description">
          <textarea className="input" rows={2} value={form.description} onChange={e => setForm({...form, description: e.target.value})} placeholder="Optional description" />
        </FormRow>
      </Modal>
    </>
  )
}
