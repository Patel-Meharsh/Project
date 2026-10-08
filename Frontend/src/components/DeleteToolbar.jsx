const TrashIcon = () => (
  <svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 6 5 6 17 6"/><path d="M8 6V4h4v2"/><path d="M6 6l1 11h6l1-11"/>
  </svg>
)
const PencilIcon = () => (
  <svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4l4 4L6 17H2v-4L11 4z"/><path d="M9.5 6.5l4 4"/>
  </svg>
)

// Pencil toggle — sits next to the table title / search bar
export function EditModeToggle({ dm }) {
  return (
    <div style={{ display:'flex', alignItems:'center', gap:6 }}>
      {dm.active && (
        <button onClick={dm.toggle}
          style={{ padding:'5px 12px', borderRadius:7, border:'1px solid #dde1ec', background:'white', fontSize:12, color:'#64748b', cursor:'pointer', fontWeight:500 }}>
          Cancel
        </button>
      )}
      <button
        onClick={dm.toggle}
        title={dm.active ? 'Exit selection' : 'Select rows to delete'}
        style={{
          width:30, height:30, borderRadius:7,
          border: dm.active ? '1px solid #ef4444' : '1px solid #e2e8f0',
          background: dm.active ? '#fef2f2' : 'white',
          color: dm.active ? '#ef4444' : '#64748b',
          cursor:'pointer', display:'flex', alignItems:'center', justifyContent:'center',
          transition:'all 0.15s', flexShrink:0,
        }}>
        {dm.active ? <PencilIcon /> : <PencilIcon />}
      </button>
    </div>
  )
}

// Checkbox <th> — first column in thead when active
export function SelectTh({ dm }) {
  if (!dm.active) return null
  return (
    <th style={{ width:40, padding:'11px 4px 11px 14px' }}>
      <input type="checkbox" checked={dm.allSelected} onChange={dm.toggleAll}
        aria-label="Select all rows"
        style={{ width:14, height:14, accentColor:'#ef4444', cursor:'pointer' }} />
    </th>
  )
}

// Checkbox <td> — first cell in each row when active
export function SelectTd({ dm, id }) {
  if (!dm.active) return null
  return (
    <td style={{ padding:'12px 4px 12px 14px' }} onClick={e => e.stopPropagation()}>
      <input type="checkbox" checked={dm.isSelected(id)} onChange={() => dm.toggleRow(id)}
        aria-label={`Select row ${id}`}
        style={{ width:14, height:14, accentColor:'#ef4444', cursor:'pointer' }} />
    </td>
  )
}

// Sticky bottom bar — anchored to left edge of content, not screen center
export default function DeleteToolbar({ dm, label = 'records' }) {
  if (!dm.active) return null
  return (
    <div role="toolbar" aria-label="Delete toolbar" style={{
      position:'sticky', bottom:0, left:0, right:0,
      background: dm.selected.size > 0 ? '#fef2f2' : '#f8f9fc',
      borderTop: `1px solid ${dm.selected.size > 0 ? '#fecaca' : '#edf0f7'}`,
      padding:'12px 22px',
      display:'flex', alignItems:'center', gap:12,
      transition:'all 0.2s',
      zIndex:10,
    }}>
      <span style={{ fontSize:13, color: dm.selected.size > 0 ? '#dc2626' : '#94a3b8' }}>
        {dm.selected.size > 0
          ? <><strong>{dm.selected.size}</strong> {label} selected</>
          : `Select ${label} above to delete`}
      </span>
      <div style={{ marginLeft:'auto', display:'flex', gap:8 }}>
        <button onClick={dm.toggle}
          style={{ padding:'6px 14px', borderRadius:7, border:'1px solid #dde1ec', background:'white', fontSize:12.5, cursor:'pointer', color:'#374151' }}>
          Cancel
        </button>
        {dm.selected.size > 0 && (
          <button onClick={dm.doDelete} disabled={dm.deleting}
            style={{ padding:'6px 16px', borderRadius:7, border:'none', background:'#ef4444', color:'white', fontSize:12.5, fontWeight:600, cursor:dm.deleting?'wait':'pointer', display:'flex', alignItems:'center', gap:6 }}>
            <TrashIcon /> {dm.deleting ? 'Deleting…' : `Delete ${dm.selected.size}`}
          </button>
        )}
      </div>
    </div>
  )
}
