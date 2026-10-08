import { useState, useCallback } from 'react'

export function useDeleteMode(rows, getId, deleteFn, onDone) {
  const [active,   setActive]   = useState(false)
  const [selected, setSelected] = useState(new Set())
  const [deleting, setDeleting] = useState(false)

  const toggle = useCallback(() => { setActive(a => !a); setSelected(new Set()) }, [])
  const isSelected = useCallback((id) => selected.has(id), [selected])
  const toggleRow  = useCallback((id) => {
    setSelected(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  }, [])
  const toggleAll  = useCallback(() => {
    setSelected(s => s.size === rows.length ? new Set() : new Set(rows.map(r => getId(r))))
  }, [rows, getId])

  const doDelete = useCallback(async () => {
    if (!selected.size) return
    if (!window.confirm(`Delete ${selected.size} record${selected.size > 1 ? 's' : ''}? This cannot be undone.`)) return
    setDeleting(true)
    try {
      await deleteFn([...selected])
      setSelected(new Set()); setActive(false); onDone && onDone()
    } finally { setDeleting(false) }
  }, [selected, deleteFn, onDone])

  return { active, toggle, isSelected, toggleRow, toggleAll, selected, deleting, doDelete,
    allSelected: selected.size === rows.length && rows.length > 0 }
}
