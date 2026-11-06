import { useEffect, useRef, useState } from 'react'
import DeleteToolbar, { SelectTh, SelectTd } from '../components/DeleteToolbar'
import { useDeleteMode } from '../hooks/useDeleteMode'
import { deleteApi } from '../lib/api'
import { grnApi, poApi, vendorApi, itemApi, codeApi, locationApi, categoryApi, masterGroupApi } from '../lib/api'
import { fmtCurrency, fmtDate } from '../lib/utils'
import { StatusBadge, Spinner, SearchInput, FormRow, FormGrid } from '../components/UI'
import SlideOver from '../components/SlideOver'
import Header from '../components/Header'
import { useAuth } from '../lib/AuthContext'
import { canDo } from '../lib/auth'
import useDataFetch from '../lib/useDataFetch'
import { useToast } from '../components/Toast'

const normalizeGstin = value => String(value || '').normalize('NFKC').replace(/[^A-Z0-9]/gi, '').toUpperCase().slice(0, 15)
const normalizeVendorName = value => String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '')
const findDirectoryVendor = (vendors, name, code = '') => {
  if (code) {
    const byCode = vendors.find(v => String(v.code || '').toLowerCase() === String(code).toLowerCase())
    if (byCode) return byCode
  }
  const normalized = normalizeVendorName(name)
  if (!normalized) return null
  const exact = vendors.filter(v => normalizeVendorName(v.name) === normalized)
  if (exact.length === 1) return exact[0]
  if (exact.length > 1) return null
  // OCR may omit punctuation, spaces, or a small part of the registered name.
  // Accept a partial match only when it identifies one directory vendor uniquely.
  const partial = vendors.filter(v => {
    const candidate = normalizeVendorName(v.name)
    return candidate && (candidate.includes(normalized) || normalized.includes(candidate))
  })
  return partial.length === 1 ? partial[0] : null
}

const findInvoiceVendor = (vendors, { code = '', name = '', gstin = '' } = {}) => {
  const byCode = code
    ? vendors.find(v => String(v.code || '').trim().toUpperCase() === String(code).trim().toUpperCase())
    : null
  if (byCode) return byCode

  const normalizedGstin = normalizeGstin(gstin)
  if (normalizedGstin.length === 15) {
    const byGstin = vendors.filter(v => normalizeGstin(v.gst_no) === normalizedGstin)
    if (byGstin.length === 1) return byGstin[0]
    if (byGstin.length > 1) return null
  }
  return findDirectoryVendor(vendors, name)
}

const PencilIcon = () => (
  <svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4l4 4L6 17H2v-4L11 4z"/><path d="M9.5 6.5l4 4"/>
  </svg>
)
const TrashIcon = () => (
  <svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 6 5 6 17 6"/><path d="M8 6V4h4v2"/><path d="M6 6l1 11h6l1-11"/>
  </svg>
)

// Searchable combo input — searches options by code or name, shows two-line suggestions
function ComboSearch({ query, onQueryChange, onSelect, options, placeholder, hasError }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  const q = (query || '').toLowerCase()
  const suggestions = q.length === 0 ? [] : options
    .filter(o => o.code.toLowerCase().includes(q) || o.name.toLowerCase().includes(q))
    .slice(0, 10)

  useEffect(() => {
    const handler = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <input
        className="input"
        value={query}
        placeholder={placeholder}
        style={hasError ? { borderColor: '#dc2626' } : {}}
        onChange={e => { onQueryChange(e.target.value); setOpen(true) }}
        onFocus={() => { if (q.length > 0) setOpen(true) }}
        onKeyDown={e => { if (e.key === 'Escape') setOpen(false) }}
      />
      {open && suggestions.length > 0 && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 400,
          background: 'white', border: '1px solid #e2e8f0', borderRadius: 8,
          boxShadow: '0 6px 20px rgba(0,0,0,0.12)', maxHeight: 200, overflowY: 'auto',
        }}>
          {suggestions.map(o => (
            <div key={o.code}
              style={{ padding: '8px 12px', cursor: 'pointer', borderBottom: '1px solid #f1f5f9' }}
              onMouseEnter={e => e.currentTarget.style.background = '#f8fafc'}
              onMouseLeave={e => e.currentTarget.style.background = ''}
              onMouseDown={e => { e.preventDefault(); onSelect(o); setOpen(false) }}
            >
              <div style={{ fontWeight: 700, fontFamily: 'monospace', fontSize: 12.5, color: '#0d0f1a' }}>{o.code}</div>
              <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 1 }}>{o.name}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}


// Suggest category/UOM from existing master items with similar descriptions.
// Suggestions are only defaults; the user can review/change them before Save Item.
function suggestItemMasterDefaults(name, items) {
  const tokens = value => new Set(String(value || '').toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ').trim().split(/\s+/).filter(token => token.length > 1))
  const target = tokens(name)
  if (!target.size) return { master_group: '', category: '', sub_category: '', uom: '' }
  const ranked = items.map(item => {
    const candidate = tokens(item.name)
    const overlap = [...target].filter(token => candidate.has(token)).length
    const score = overlap / Math.max(target.size, candidate.size, 1)
    return { item, score }
  }).sort((a, b) => b.score - a.score)
  const best = ranked[0]
  // Only use a reasonably strong match; never infer from a weak/ambiguous name.
  if (!best || best.score < 0.5 || (ranked[1] && best.score - ranked[1].score < 0.12)) {
    return { master_group: '', category: '', sub_category: '', uom: '' }
  }
  return {
    master_group: best.item.master_group_name || best.item.master_group || '',
    category: best.item.category || '',
    sub_category: best.item.sub_category || '',
    uom: best.item.uom || '',
  }
}

const CATEGORY_SUGGESTIONS_BY_GROUP = {
  hardware: ['Door Fittings', 'Fasteners', 'Plumbing Fittings', 'Hand Tools'],
  electrical: ['Lighting', 'Wiring'],
}

export default function GRN() {
  const toast = useToast()
  const { data: fetchResult, loading, refetch } = useDataFetch(() =>
    Promise.all([
      grnApi.getAll(),
      poApi.getAll(),
      vendorApi.getAll(),
      itemApi.getAll(),
      locationApi.getAll(),
      categoryApi.getAll(),
      masterGroupApi.getAll(),
    ]).catch(err => { toast.error('Failed to load GRN data'); return [[], [], [], [], [], [], []] })
  )
  const [grns, pos, vendors, items, locs, categories, masterGroups] = fetchResult || [[], [], [], [], [], [], []]
  const masterGroupNames = [...new Set([...masterGroups.map(group => group.name), ...items.map(item => item.master_group_name || item.master_group), 'Hardware', 'Electrical', 'Stationery', 'Cleaning', 'Washroom', 'Waste Management', 'General'].map(value => String(value || '').trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b))
  const [search, setSearch] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({ grn_no:'', grn_date: new Date().toISOString().split('T')[0], invoice_no:'', po_no:'', uom:'', rate:0, received_by:'Store Keeper', inspected_by:'', store_location:'STORE-CH', batch_lot:'', status:'Stored', remarks:'' })
  const emptyRow = () => ({
    id: Date.now(),
    item_code: '',
    item_name: '',
    vendor_code: '',
    vendor_name: '',
    recd_qty: 0,
    accepted_qty: 0,
    rate: 0,
  })
  const [lineItems, setLineItems] = useState([emptyRow()])
  const [rowError, setRowError] = useState(false)
  const [editMode, setEditMode] = useState(false)
  const [editTarget, setEditTarget] = useState(null)
  const [viewGrn, setViewGrn] = useState(null)
  const [extractingDocument, setExtractingDocument] = useState(false)
  const extractionAbortControllerRef = useRef(null)
  const [extractionResult, setExtractionResult] = useState(null)
  const [selectedDocumentName, setSelectedDocumentName] = useState('')
  const [itemMasterDraft, setItemMasterDraft] = useState(null)
  const [createdVendorRecords, setCreatedVendorRecords] = useState([])
  const [savingMasterItem, setSavingMasterItem] = useState(false)
  const [pendingMasterIndexes, setPendingMasterIndexes] = useState([])
  const [showDraftChoice, setShowDraftChoice] = useState(false)

  const { user } = useAuth()
  const isAdmin = canDo(user?.role, 'admin')

  useEffect(() => () => {
    extractionAbortControllerRef.current?.abort()
  }, [])

  const load = () => refetch()

  const openEdit = (grn) => {
    setEditTarget(grn)
    setForm({
      grn_no:         grn.grn_no || '',
      grn_date:       grn.grn_date || new Date().toISOString().split('T')[0],
      invoice_no:     grn.invoice_no || '',
      po_no:          grn.po_no || '',
      uom:            grn.uom || '',
      rate:           grn.rate || 0,
      received_by:    grn.received_by || '',
      inspected_by:   grn.inspected_by || '',
      store_location: grn.store_location || '',
      batch_lot:      grn.batch_lot || '',
      status:         grn.status || 'Stored',
      remarks:        grn.remarks || '',
    })
    const rows = Array.isArray(grn.line_items) && grn.line_items.length > 0
      ? grn.line_items.map(r => ({
          ...emptyRow(),
          item_code:    r.item_code    || '',
          item_name:    r.item_name    || '',
          vendor_code:  r.vendor_code  || '',
          vendor_name:  r.vendor_name  || '',
          recd_qty:     r.recd_qty     || 0,
          accepted_qty: r.accepted_qty || 0,
          rate:         r.rate != null ? r.rate : (grn.rate || 0),
        }))
      : [{ ...emptyRow(), item_code: grn.item_code || '', item_name: grn.item_name || '',
           vendor_code: grn.vendor_code || '', rate: grn.rate || 0 }]
    setLineItems(rows)
    setShowCreate(true)
  }

  const closeSlideOver = () => {
    extractionAbortControllerRef.current?.abort()
    extractionAbortControllerRef.current = null
    setShowCreate(false)
    setEditTarget(null)
    setRowError(false)
    // Keep the active invoice draft and its unmatched-item queue in memory when
    // the GRN panel is closed. Reopening GRN can resume review without OCR again.
    setItemMasterDraft(null)
    setExtractingDocument(false)
    if (!pendingMasterIndexes.length) {
      setExtractionResult(null)
      setSelectedDocumentName('')
    }
  }

  // Always start a new GRN with a clean draft. Never spread the previous form
  // state here, because that can carry invoice/PO/vendor/remarks into the next receipt.
  const blankGRNForm = () => ({
    grn_no: '', grn_date: new Date().toISOString().split('T')[0],
    invoice_no: '', po_no: '', uom: '', rate: 0,
    received_by: 'Store Keeper', inspected_by: '',
    store_location: 'STORE-CH', batch_lot: '', status: 'Stored', remarks: '',
  })

  const hasUnfinishedDraft = () => Boolean(
    form.invoice_no || form.po_no || selectedDocumentName || extractionResult ||
    pendingMasterIndexes.length ||
    lineItems.some(row => row.item_code || row.item_name || row.vendor_code || Number(row.recd_qty) > 0)
  )

  const startNewGRN = async () => {
    extractionAbortControllerRef.current?.abort()
    extractionAbortControllerRef.current = null
    setShowDraftChoice(false)
    setEditTarget(null)
    setRowError(false)
    setForm(blankGRNForm())
    setLineItems([emptyRow()])
    setPendingMasterIndexes([])
    setItemMasterDraft(null)
    setCreatedVendorRecords([])
    setExtractionResult(null)
    setExtractingDocument(false)
    setSelectedDocumentName('')
    setShowCreate(true)
  }

  const continueGRNDraft = () => {
    setShowDraftChoice(false)
    setEditTarget(null)
    setRowError(false)
    if (pendingMasterIndexes.length > 0) {
      const index = pendingMasterIndexes[0]
      const row = lineItems[index]
      if (row) {
        setItemMasterDraft({
          index,
          name: row.item_name || '',
          ...suggestItemMasterDefaults(row.item_name || '', items),
          uom: row.uom || '',
          vendor_name: row.vendor_name || '',
          gst_no: normalizeGstin(row.vendor_gst_no),
          vendor_code: row.vendor_code || '',
          vendor_is_new: !row.vendor_code,
          possible_matches: row.possible_matches || [],
          needs_review: row.needs_review,
        })
      }
    }
    setShowCreate(true)
  }

  const openCreate = async () => {
    if (hasUnfinishedDraft()) {
      setShowDraftChoice(true)
      return
    }
    await startNewGRN()
  }

  const [sortConfig, setSortConfig] = useState({ key: 'grn_no', direction: 'asc' })
  const toggleSort = (key) => setSortConfig(prev => ({ key, direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc' }))
  const sortArrow = (key) => sortConfig.key === key ? (sortConfig.direction === 'asc' ? ' ↑' : ' ↓') : ''

  const filtered = grns.filter(g => {
    const q = search.toLowerCase()
    return !search ||
      (g.grn_no||'').toLowerCase().includes(q) ||
      (g.item_name||'').toLowerCase().includes(q) ||
      (g.vendor_name||'').toLowerCase().includes(q) ||
      (g.vendor_code||'').toLowerCase().includes(q) ||
      (g.po_no||'').toLowerCase().includes(q)
  })

  const sorted = [...filtered].sort((a, b) => {
    if (!sortConfig.key) return 0
    const mul = sortConfig.direction === 'asc' ? 1 : -1
    if (sortConfig.key === 'grn_date') return (new Date(a.grn_date||0) - new Date(b.grn_date||0)) * mul
    const av = a[sortConfig.key], bv = b[sortConfig.key]
    if (typeof av === 'number' || (av != null && !isNaN(Number(av)))) return (Number(av||0) - Number(bv||0)) * mul
    return String(av||'').localeCompare(String(bv||''), undefined, { numeric: true, sensitivity: 'base' }) * mul
  })

  // Auto-fill all line items when a PO is selected. Per-line remaining_qty comes
  // from the backend (PO line qty − Σ accepted_qty across prior GRNs for same PO+item),
  // so partial GRNs default to what's actually left on each line.
  const selectPO = async (po_no) => {
    if (!po_no) {
      setForm(f => ({ ...f, po_no: '' }))
      return
    }
    try {
      const data = await poApi.grnPrefill(po_no)
      const firstRate = data.line_items[0]?.rate || 0
      setForm(f => ({
        ...f,
        po_no: data.po_no,
        rate: firstRate,
        store_location: f.store_location || data.delivery_location || 'STORE-CH',
      }))
      if (!data.line_items.length) {
        toast.error('All items on this PO are already fully received')
        setLineItems([emptyRow()])
        return
      }
      setLineItems(data.line_items.map((li, idx) => ({
        id: Date.now() + idx,
        item_code:    li.item_code,
        item_name:    li.item_name,
        vendor_code:  data.vendor_code,
        vendor_name:  data.vendor_name,
        recd_qty:     li.remaining_qty,
        accepted_qty: li.remaining_qty,
        rate:         li.rate,
      })))
    } catch (err) {
      toast.error('Failed to load PO details: ' + (err.response?.data?.detail || err.message))
      setForm(f => ({ ...f, po_no }))
    }
  }

const extractGRNDocument = async (file) => {
  if (!file) return
  extractionAbortControllerRef.current?.abort()
  const controller = new AbortController()
  extractionAbortControllerRef.current = controller
  setExtractingDocument(true)
  setExtractionResult(null)
  // Start each upload from a clean document draft, including when extraction fails.
  // Otherwise values from a previously uploaded invoice can remain visible and be saved.
  setForm(f => ({
    ...f,
    invoice_no: '',
    po_no: '',
    grn_date: new Date().toISOString().split('T')[0],
  }))
  setLineItems([emptyRow()])
  setPendingMasterIndexes([])
  setItemMasterDraft(null)
  try {
    const result = await grnApi.extractDocument(file, controller.signal)
    if (controller.signal.aborted) return
    setExtractionResult(result)
    const fields = result.fields || {}
    // This document is the source for the draft: clear missing extracted values
    // instead of silently retaining values from a previously selected PO/document.
    setForm(f => ({
      ...f,
      invoice_no: fields.invoice_no || '',
      po_no: fields.po_no || '',
      // If this upload has no readable date, use today's date rather than keeping
      // a date extracted from a different receipt uploaded earlier in this draft.
      grn_date: fields.grn_date || new Date().toISOString().split('T')[0],
      store_location: fields.store_location || 'STORE-CH',
    }))
    const normalizeItemName = value => String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '')
    const cleanExtractedName = value => String(value || '')
      .replace(/^\\s*(?:sr\\.?\\s*no\\.?\\s*)?\\d{1,3}\\s*[.)-]\\s*/i, '')
      .replace(/^\\s*(?:5|\\d{1,3})\\s+(?=(?:carting|freight|transport|delivery\\s+charges?|packing|handling|loading|unloading)\\b)/i, '')
      .replace(/\\s*\\(\\s*\\d+(?:\\.\\d+)?\\s*%\\s*\\)\\s*$/i, '')
      .replace(/^\\s*(?:5|\\d{1,3})\\s+(?=[a-z])/i, (prefix, offset, whole) => {
        // Treat a bare leading number as a serial only if removing it exactly
        // matches a known item. This protects real product numbers such as 15W.
        const withoutSerial = whole.slice(prefix.length).trim()
        return items.some(item => normalizeItemName(item.name) === normalizeItemName(withoutSerial)) ? '' : prefix
      }).trim()
    // Resolve the invoice vendor against the latest Vendor Directory. Code is
    // strongest, followed by exact GSTIN and then a unique normalized name match.
    // If no directory record matches, keep the invoice name/GSTIN editable so a
    // new vendor can be created together with the new Item Master record.
    const extractedRows = Array.isArray(result.line_items) ? result.line_items : []
    const extractedVendorCode = String(
      fields.vendor_code || extractedRows.find(row => row.vendor_code)?.vendor_code || ''
    ).trim()
    const invoiceVendorName = String(
      fields.vendor_name || extractedRows.find(row => row.vendor_name)?.vendor_name || ''
    ).trim()
    const invoiceVendorGstin = normalizeGstin(
      fields.vendor_gst_no || fields.gst_no || extractedRows.find(row => row.vendor_gst_no)?.vendor_gst_no || ''
    )
    const latestVendors = await vendorApi.getAll().catch(() => [...vendors, ...createdVendorRecords])
    if (controller.signal.aborted) return
    const matchedVendor = findInvoiceVendor(latestVendors, {
      code: extractedVendorCode,
      name: invoiceVendorName,
      gstin: invoiceVendorGstin,
    })
    const suggestedRows = (result.line_items || [])
      .map((row, idx) => ({ row, idx, cleanedName: cleanExtractedName(row.item_name) }))
      .map(({ row, idx, cleanedName }) => {
        const isChargeLine = Boolean(row.is_charge_line) ||
          /\b(?:carting|freight|transport(?:ation)?|delivery\s+charges?|packing\s+charges?|handling\s+charges?|loading|unloading|round\s*off)\b/i.test(cleanedName)
        // Keep invoice charges visible in the GRN draft, but never send them
        // through Item Master matching or stock-item creation.
        if (isChargeLine) return {
          id: Date.now() + idx,
          item_code: '',
          item_name: cleanedName || row.item_name || 'Invoice charge',
          vendor_code: matchedVendor?.code || '',
          vendor_name: matchedVendor?.name || invoiceVendorName || row.vendor_name || '',
          vendor_gst_no: matchedVendor ? normalizeGstin(matchedVendor.gst_no) : invoiceVendorGstin,
          uom: row.uom || row.unit || '',
          recd_qty: row.recd_qty ?? '',
          accepted_qty: row.accepted_qty ?? '',
          rate: row.rate ?? '',
          line_amount: row.line_amount ?? null,
          is_charge_line: true,
          needs_review: false,
          extraction_warning: '',
          possible_matches: [],
        }
        const normalizedName = normalizeItemName(cleanedName)
        const validCodeMatch = items.find(item => row.item_code && item.code === row.item_code)
        const exactNameMatch = items.find(item =>
          normalizedName && normalizeItemName(item.name) === normalizedName
        )
        const withoutLeadingDigit = cleanedName.replace(/^\\s*\\d(?=[a-z])/i, '').trim()
        const serialCleanMatch = withoutLeadingDigit !== cleanedName
          ? items.find(item => normalizeItemName(item.name) === normalizeItemName(withoutLeadingDigit))
          : null
        const tokenSet = value => new Set(String(value || '').toLowerCase()
          .replace(/[^a-z0-9]+/g, ' ').trim().split(/\s+/).filter(token => token.length > 1))
        const sourceTokens = tokenSet(cleanedName)
        const rankedMatches = items.map(item => {
          const itemTokens = tokenSet(item.name)
          const intersection = [...sourceTokens].filter(token => itemTokens.has(token)).length
          const union = new Set([...sourceTokens, ...itemTokens]).size
          const tokenScore = union ? intersection / union : 0
          const sourceNorm = normalizeItemName(cleanedName)
          const itemNorm = normalizeItemName(item.name)
          const containmentScore = sourceNorm && itemNorm && (sourceNorm.includes(itemNorm) || itemNorm.includes(sourceNorm))
            ? Math.min(sourceNorm.length, itemNorm.length) / Math.max(sourceNorm.length, itemNorm.length)
            : 0
          return { item, score: Math.max(tokenScore, containmentScore) }
        }).filter(match => match.score >= 0.45)
          .sort((a, b) => b.score - a.score)
        const bestCandidate = rankedMatches[0]
        const runnerUp = rankedMatches[1]
        const confidentSimilarityMatch = bestCandidate &&
          bestCandidate.score >= 0.82 &&
          (!runnerUp || bestCandidate.score - runnerUp.score >= 0.12)
          ? bestCandidate.item
          : null
        const masterMatch = validCodeMatch || exactNameMatch || serialCleanMatch || confidentSimilarityMatch
        const possibleMatches = masterMatch ? [] : rankedMatches.slice(0, 3).map(({ item, score }) => ({
          code: item.code, name: item.name, category: item.category || '', score: Math.round(score * 100),
        }))
        const uncertainMatch = !masterMatch && possibleMatches.length > 0
        return {
          id: Date.now() + idx,
          item_code: masterMatch?.code || '',
          uom: row.uom || row.unit || '',
          item_name: masterMatch?.name || cleanedName || '',
          vendor_code: matchedVendor?.code || '',
          vendor_name: matchedVendor?.name || invoiceVendorName || row.vendor_name || '',
          vendor_gst_no: matchedVendor ? normalizeGstin(matchedVendor.gst_no) : invoiceVendorGstin,
          recd_qty: row.recd_qty ?? '',
          // Default accepted quantity to received quantity for GRN entry.
          accepted_qty: row.accepted_qty ?? row.recd_qty ?? '',
          rate: row.rate ?? '',
          rate_unreadable: Boolean(row.rate_unreadable),
          rate_warning: Boolean(row.rate_warning),
          line_amount: row.line_amount ?? null,
          is_charge_line: false,
          needs_review: Boolean(row.needs_review || uncertainMatch),
          extraction_warning: row.extraction_warning || (uncertainMatch
            ? 'Possible existing Item Master matches need review before creating a new item.'
            : ''),
          possible_matches: possibleMatches,
        }
      })
    // Replace existing rows even when no items were detected, so rows from an
    // earlier PO or receipt can never leak into this document's draft.
    setLineItems(suggestedRows.length ? suggestedRows : [emptyRow()])
    // Queue each unmatched invoice row for explicit user-confirmed Item Master creation.
    const unmatched = suggestedRows
      .map((row, index) => ({ row, index }))
      .filter(({ row }) => !row.is_charge_line && !row.item_code && row.item_name.trim())
      .map(({ index }) => index)
    setPendingMasterIndexes(unmatched)
    if (unmatched.length) {
      const first = suggestedRows[unmatched[0]]
      setItemMasterDraft({ index: unmatched[0], name: first.item_name, ...suggestItemMasterDefaults(first.item_name, items), uom: first.uom || '', vendor_name: first.vendor_name || fields.vendor_name || '', gst_no: first.vendor_gst_no || '', vendor_code: first.vendor_code || '', vendor_is_new: !first.vendor_code, possible_matches: first.possible_matches || [], needs_review: first.needs_review })
    }
    toast.success('Document read. Review every extracted field before saving.')
  } catch (err) {
    const wasCancelled = controller.signal.aborted || err.code === 'ERR_CANCELED' || err.name === 'CanceledError'
    if (!wasCancelled) {
      toast.error(err.response?.data?.detail || 'Could not extract document details.')
    }
  } finally {
    if (extractionAbortControllerRef.current === controller) {
      extractionAbortControllerRef.current = null
      setExtractingDocument(false)
    }
  }
}

const cancelDocumentExtraction = () => {
  extractionAbortControllerRef.current?.abort()
  extractionAbortControllerRef.current = null
  setExtractingDocument(false)
}


const resumePendingMasterSetup = () => {
  if (!pendingMasterIndexes.length) return
  const nextIndex = pendingMasterIndexes[0]
  const nextRow = lineItems[nextIndex]
  if (!nextRow) {
    setPendingMasterIndexes([])
    return
  }
  setItemMasterDraft({
    index: nextIndex,
    name: nextRow.item_name || '',
    ...suggestItemMasterDefaults(nextRow.item_name || '', items),
    uom: nextRow.uom || '',
    vendor_name: nextRow.vendor_name || '',
    gst_no: normalizeGstin(nextRow.vendor_gst_no),
    vendor_code: nextRow.vendor_code || '',
    vendor_is_new: !nextRow.vendor_code,
    possible_matches: nextRow.possible_matches || [],
    needs_review: nextRow.needs_review,
  })
}

const chooseExistingMasterItem = (match) => {
  if (!itemMasterDraft || !match?.code) return
  const selectedIndex = itemMasterDraft.index
  const updated = [...lineItems]
  updated[selectedIndex] = {
    ...updated[selectedIndex],
    item_code: match.code,
    item_name: match.name || updated[selectedIndex].item_name,
    needs_review: false,
    extraction_warning: '',
    possible_matches: [],
  }
  setLineItems(updated)
  const remaining = pendingMasterIndexes.filter(index => index !== selectedIndex)
  setPendingMasterIndexes(remaining)
  if (remaining.length) {
    const nextIndex = remaining[0]
    const nextRow = updated[nextIndex]
    setItemMasterDraft({
      index: nextIndex,
      name: nextRow.item_name,
      ...suggestItemMasterDefaults(nextRow.item_name, items),
      uom: nextRow.uom || '',
      vendor_name: nextRow.vendor_name || '',
      gst_no: normalizeGstin(nextRow.vendor_gst_no),
      vendor_code: nextRow.vendor_code || '',
      vendor_is_new: !nextRow.vendor_code,
      possible_matches: nextRow.possible_matches || [],
      needs_review: nextRow.needs_review,
    })
  } else {
    setItemMasterDraft(null)
    toast.success(`Linked invoice row to existing item ${match.code}.`)
  }
}

const saveNewMasterItem = async () => {
  if (!itemMasterDraft) return
  const name = (itemMasterDraft.name || '').trim()
  if (!name) return toast.error('Enter an item name before saving.')
  const masterGroup = String(itemMasterDraft.master_group || '').trim()
  if (!masterGroup) return toast.error('Enter or select a master group for this item.')
  if (!String(itemMasterDraft.category || '').trim()) return toast.error('Enter or select a category under the master group.')
  const subCategory = String(itemMasterDraft.sub_category || '').trim()
  // Unit of measurement is optional: use the invoice unit when detected,
  // otherwise allow the user to create the master item without blocking.
  const invoiceUnit = String(lineItems[itemMasterDraft.index]?.uom || itemMasterDraft.uom || '').trim()
  setSavingMasterItem(true)
  try {
    // Reuse the established code prefix for this category (for example,
    // an existing Electrical item EM-001 means the next item should be EM-002).
    // Only derive a new prefix when this category has no coded items yet.
    const categoryKey = itemMasterDraft.category.trim().toLowerCase()
    const categoryItems = items.filter(item =>
      (item.category || '').trim().toLowerCase() === categoryKey &&
      /^([A-Z][A-Z0-9]*)-(\d+)$/i.test(item.code || '')
    )
    const existingPrefixes = [...new Set(categoryItems.map(item =>
      (item.code.match(/^([A-Z][A-Z0-9]*)-\d+$/i) || [])[1]?.toUpperCase()
    ).filter(Boolean))]
    if (existingPrefixes.length > 1) {
      return toast.error('This category uses multiple item-code prefixes. Please ask an admin to standardize the category code before creating another item.')
    }
    const categoryPrefix = existingPrefixes[0] || ({
      electrical: 'EM',
      'electrical & maintenance': 'EM',
      'electrical and maintenance': 'EM',
      cleaning: 'CL',
      stationery: 'ST',
      washroom: 'WS',
      'waste management': 'WM',
      general: 'GN',
    }[categoryKey] || itemMasterDraft.category
      .split(/[^A-Za-z0-9]+/).filter(Boolean).map(part => part[0]).join('').toUpperCase().slice(0, 3) || 'ITM')
    const selectedRow = lineItems[itemMasterDraft.index] || {}
    // Refresh before saving so a vendor added elsewhere during this GRN session
    // is reused instead of creating a duplicate.
    const latestVendors = await vendorApi.getAll().catch(() => [...vendors, ...createdVendorRecords])
    const linkedVendor = findInvoiceVendor(latestVendors, {
      code: selectedRow.vendor_code || itemMasterDraft.vendor_code || '',
      name: itemMasterDraft.vendor_name || selectedRow.vendor_name || '',
      gstin: itemMasterDraft.gst_no || selectedRow.vendor_gst_no || '',
    })
    let newVendorData = null
    let resolvedVendor = linkedVendor
    if (!resolvedVendor) {
      const vendorName = String(itemMasterDraft.vendor_name || selectedRow.vendor_name || '').trim()
      const vendorGstin = normalizeGstin(itemMasterDraft.gst_no || selectedRow.vendor_gst_no || '')
      if (!vendorName) return toast.error('Enter the new vendor name from the invoice before saving this item.')
      if (vendorGstin.length !== 15 || !/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$/.test(vendorGstin)) {
        return toast.error('Enter a valid 15-character GSTIN for the new vendor before saving this item.')
      }
      const vendorCode = await codeApi.next('vendor')
      newVendorData = { code: vendorCode, name: vendorName, gst_no: vendorGstin, status: 'Active' }
      resolvedVendor = newVendorData
    } else {
      const directoryVendorName = String(resolvedVendor.name || '').trim()
      const directoryVendorGstin = normalizeGstin(resolvedVendor.gst_no)
      if (!directoryVendorName) return toast.error('The selected Vendor Directory record has no vendor name.')
      if (directoryVendorGstin && (directoryVendorGstin.length !== 15 || !/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$/.test(directoryVendorGstin))) {
        return toast.error('The GSTIN stored in Vendor Directory is invalid. Please correct the vendor record before adding this item.')
      }
    }

    const code = await codeApi.next('item', categoryPrefix)
    const itemData = {
      code, name, category: itemMasterDraft.category.trim(),
      master_group: masterGroup,
      sub_category: subCategory,
      uom: invoiceUnit,
      vendor_code: resolvedVendor.code,
      rate: Number(selectedRow.rate || 0),
      status: 'Active',
    }
    const result = newVendorData
      ? await itemApi.createWithVendor({ item: itemData, vendor: newVendorData })
      : { item: await itemApi.create(itemData), vendor: resolvedVendor }
    const created = result.item || result
    const savedVendor = result.vendor || resolvedVendor
    if (!created?.code || !savedVendor?.code) {
      throw new Error('The item or vendor was not returned after saving. Refresh Item Master and Vendor Directory before retrying.')
    }
    const savedVendorName = String(savedVendor.name || '').trim()
    const savedVendorGstin = normalizeGstin(savedVendor.gst_no)
    const updated = lineItems.map(row => row.vendor_code
      ? row
      : { ...row, vendor_code: savedVendor.code, vendor_name: savedVendorName, vendor_gst_no: savedVendorGstin })
    updated[itemMasterDraft.index] = {
      ...updated[itemMasterDraft.index],
      item_code: created.code,
      item_name: created.name,
      vendor_code: savedVendor.code,
      vendor_name: savedVendorName,
      vendor_gst_no: savedVendorGstin,
    }
    setLineItems(updated)
    if (newVendorData) {
      setCreatedVendorRecords(previous => [...previous.filter(v => v.code !== savedVendor.code), savedVendor])
    }
    await refetch()
    toast.success(newVendorData
      ? `Vendor ${savedVendor.code} and item ${created.code} added successfully.`
      : `Item ${created.code} added to Item Master using vendor ${savedVendor.code}.`)
    const remaining = pendingMasterIndexes.filter(index => index !== itemMasterDraft.index)
    setPendingMasterIndexes(remaining)
    if (remaining.length) {
      const nextIndex = remaining[0]
      const nextRow = updated[nextIndex]
      setItemMasterDraft({ index: nextIndex, name: nextRow.item_name, ...suggestItemMasterDefaults(nextRow.item_name, items), uom: nextRow.uom || '', vendor_name: nextRow.vendor_name || '', gst_no: normalizeGstin(nextRow.vendor_gst_no), vendor_code: nextRow.vendor_code || '', vendor_is_new: !nextRow.vendor_code, possible_matches: nextRow.possible_matches || [], needs_review: nextRow.needs_review })
    } else {
      setItemMasterDraft(null)
    }
  } catch (err) {
    toast.error(err.response?.data?.detail || 'Could not create the item. Check your permissions and try again.')
  } finally {
    setSavingMasterItem(false)
  }
}

const createGRN = async () => {

  // validation
  if (!form.store_location) return toast.error('Store Location is required — stock cannot be updated without it.')
  if (!form.grn_date) return toast.error('GRN date is required.')
  if (lineItems.length === 0) return toast.error('Add at least one invoice line before saving.')
  if (lineItems.some(r => !r.is_charge_line && (!String(r.item_name || '').trim() || !String(r.item_code || '').trim()))) {
    setRowError(true)
    return alert('Every invoice line must be linked to an Item Master record. For unmatched items, complete the Add item to Item Master popup and click Save Item before saving the GRN.')
  }
  if (lineItems.some(r => !r.is_charge_line && (!Number.isFinite(Number(r.recd_qty)) || Number(r.recd_qty) <= 0))) {
    return toast.error('Received quantity must be greater than 0 for every line item.')
  }
  if (lineItems.some(r => !r.is_charge_line && (!Number.isFinite(Number(r.accepted_qty)) || Number(r.accepted_qty) <= 0 || Number(r.accepted_qty) > Number(r.recd_qty)))) {
    return toast.error('Accepted quantity must be greater than 0 and cannot exceed received quantity.')
  }
  if (lineItems.some(r => !r.is_charge_line && !r.rate_unreadable && (!Number.isFinite(Number(r.rate)) || Number(r.rate) < 0))) {
    return toast.error('Rate must be a valid non-negative number.')
  }
  if (!window.confirm(`Save this GRN with ${lineItems.length} line item(s)? The GRN number will be assigned only after a successful save. This will update inventory${form.po_no ? ' and the linked purchase order' : ''}.`)) {
    return
  }

  // NEW payload (this is what you were missing)
  const payload = {
    ...form,
    line_items: lineItems.map(r => ({
      // Preserve invoice-derived line details (description, UOM, tax/amount
      // metadata, etc.) while replacing master references with saved codes.
      ...r,
      item_code: String(r.item_code || '').trim(),
      item_name: String(r.item_name || '').trim(),
      vendor_code: String(r.vendor_code || '').trim(),
      vendor_name: String(r.vendor_name || '').trim(),
      recd_qty: Number(r.recd_qty),
      accepted_qty: Number(r.accepted_qty),
      rate: r.rate_unreadable ? 0 : Number(r.rate || 0),
      rate_unreadable: Boolean(r.rate_unreadable),
      is_charge_line: Boolean(r.is_charge_line),
      line_amount: r.line_amount == null ? null : Number(r.line_amount),
    }))
  }

  try {
    if (editTarget) {
      await grnApi.update(editTarget.grn_no, payload)
      toast.success('GRN updated')
    } else {
      await grnApi.create(payload)
      toast.success('GRN created')
    }
  } catch (err) {
    toast.error(err.response?.data?.detail || (editTarget ? 'Failed to update GRN' : 'Failed to create GRN. No success was reported; check the records before retrying.'))
    return
  }

  // A successful save ends this in-memory invoice review session.
  setPendingMasterIndexes([])
  setItemMasterDraft(null)
  setExtractionResult(null)
  setSelectedDocumentName('')
  closeSlideOver()
  load()

  setForm({
    grn_no:'',
    grn_date: new Date().toISOString().split('T')[0],
    invoice_no:'',
    po_no:'',
    uom:'',
    rate:0,
    received_by:'Store Keeper',
    inspected_by:'',
    store_location:'STORE-CH',
    batch_lot:'',
    status:'Stored',
    remarks:''
  })

  setLineItems([emptyRow()])
}

  const selectedItem = items.find(i => i.code === form.item_code)
  const selectedVendor = vendors.find(v => v.code === form.vendor_code)

  const dm = useDeleteMode(filtered, r => r.grn_no, deleteApi.grns, load)

  if (loading) return <><Header title="Goods Receipt (GRN)" /><div className="page-content"><Spinner /></div></>

  return (
    <>
      <Header title="Goods Receipt Notes" subtitle="Record all incoming deliveries"
        actions={<button className="btn btn-accent" onClick={openCreate}>+ Record GRN</button>} />
      <div className="page-content">
        <div className="kpi-grid" style={{ gridTemplateColumns:'repeat(4,1fr)', marginBottom:20 }}>
          {[{l:'Total GRNs',v:grns.length,c:'blue'},{l:'Accepted Qty',v:grns.reduce((s,g)=>s+(g.accepted_qty||0),0),c:'green'},{l:'Rejected Qty',v:grns.reduce((s,g)=>s+(g.rejected_qty||0),0),c:'red'},{l:'Total Value',v:fmtCurrency(grns.reduce((s,g)=>s+(g.value||0),0)),c:'amber'}].map(k=>(
            <div key={k.l} className={`kpi-card ${k.c}`}><div className="kpi-value">{k.v}</div><div className="kpi-label">{k.l}</div></div>
          ))}
        </div>
        <div className="table-wrap">
          <div className="table-header">
            <span className="table-title">{sorted.length} GRN Records</span>
            <div style={{ display:'flex', alignItems:'center', gap:6 }}>
              {isAdmin && (
                <>
                  <button
                    onClick={() => { setEditMode(m => !m); if (dm.active) dm.toggle() }}
                    title={editMode ? 'Exit edit mode' : 'Edit a GRN'}
                    style={{
                      width:30, height:30, borderRadius:7, cursor:'pointer', flexShrink:0,
                      border: editMode ? '1px solid #3b82f6' : '1px solid #e2e8f0',
                      background: editMode ? '#eff6ff' : 'white',
                      color: editMode ? '#3b82f6' : '#64748b',
                      display:'flex', alignItems:'center', justifyContent:'center', transition:'all 0.15s',
                    }}>
                    <PencilIcon />
                  </button>
                  <button
                    onClick={() => { dm.toggle(); if (editMode) setEditMode(false) }}
                    title={dm.active ? 'Exit delete mode' : 'Select rows to delete'}
                    style={{
                      width:30, height:30, borderRadius:7, cursor:'pointer', flexShrink:0,
                      border: dm.active ? '1px solid #ef4444' : '1px solid #e2e8f0',
                      background: dm.active ? '#fef2f2' : 'white',
                      color: dm.active ? '#ef4444' : '#64748b',
                      display:'flex', alignItems:'center', justifyContent:'center', transition:'all 0.15s',
                    }}>
                    <TrashIcon />
                  </button>
                </>
              )}
              <SearchInput value={search} onChange={setSearch} placeholder="Search GRN, item, vendor…" />
            </div>
          </div>
          <div>
            <table>
              <thead><tr>
                {editMode && <th style={{ width:36 }} />}
                <SelectTh dm={dm} />
                {[
                  { key:'grn_no',        label:'GRN No',   w:100, align:'left'  },
                  { key:'grn_date',      label:'Date',     w:95,  align:'left'  },
                  { key:'po_no',         label:'PO Ref',   w:95,  align:'left'  },
                  { key:'invoice_no',    label:'Invoice',  w:100, align:'left'  },
                  { key:'vendor_name',   label:'Vendor',   w:150, align:'left'  },
                  { key:'item_name',     label:'Item',     w:'auto', align:'left' },
                  { key:'recd_qty',      label:'Recd',     w:65,  align:'right' },
                  { key:'accepted_qty',  label:'Accepted', w:80,  align:'right' },
                  { key:'rate',          label:'Value',    w:105, align:'right' },
                  { key:'store_location',label:'Location', w:100, align:'left'  },
                  { key:'status',        label:'Status',   w:110, align:'left'  },
                ].map(h => (
                  <th key={h.key} style={{ cursor:'pointer', userSelect:'none', whiteSpace:'nowrap', width:h.w, textAlign:h.align }}
                    onClick={() => toggleSort(h.key)}
                    onMouseEnter={e => e.currentTarget.style.color='#0d0f1a'}
                    onMouseLeave={e => e.currentTarget.style.color=''}
                  >{h.label}{sortArrow(h.key)}</th>
                ))}
              </tr></thead>
              <tbody>
                {sorted.length===0 && <tr><td colSpan={12} style={{ textAlign:'center', padding:40, color:'#94a3b8' }}>No GRNs yet</td></tr>}
                {sorted.map(g => {
                  const codes = (Array.isArray(g.line_items) ? g.line_items : []).map(li => li.item_code).filter(Boolean)
                  const itemSummary = codes.length === 0
                    ? (g.item_code || g.item_name || '—')
                    : codes.length <= 2
                      ? codes.join(', ')
                      : `${codes.slice(0,2).join(', ')} +${codes.length - 2} more`
                  const itemTitle = codes.length > 2 ? codes.join(', ') : ''
                  return (
                  <tr key={g.grn_no} onClick={() => setViewGrn(g)} style={{ cursor:'pointer' }}>
                    {editMode && (
                      <td style={{ padding:'8px 4px 8px 10px' }} onClick={e => e.stopPropagation()}>
                        <button
                          onClick={() => openEdit(g)}
                          title={`Edit ${g.grn_no}`}
                          style={{
                            width:26, height:26, borderRadius:6, cursor:'pointer',
                            border:'1px solid #bfdbfe', background:'#eff6ff', color:'#3b82f6',
                            display:'flex', alignItems:'center', justifyContent:'center',
                          }}>
                          <PencilIcon />
                        </button>
                      </td>
                    )}
                    <SelectTd dm={dm} id={g.grn_no} />
                    <td style={{ whiteSpace:'nowrap' }}>
                      <span className="td-code" style={{ color:'#2563eb', fontWeight:600 }}>{g.grn_no}</span>
                    </td>
                    <td style={{ fontSize:13, color:'#64748b', whiteSpace:'nowrap' }}>{fmtDate(g.grn_date)}</td>
                    <td style={{ whiteSpace:'nowrap' }}><span className="td-code" style={{ color:'#3b82f6' }}>{g.po_no}</span></td>
                    <td style={{ whiteSpace:'nowrap' }}><span className="td-code" style={{ color:'#64748b' }}>{g.invoice_no}</span></td>
                    <td style={{ fontSize:13 }}><div className="clamp-2">{g.vendor_name}</div></td>
                    <td title={itemTitle}>
                      <div className="clamp-1" style={{ fontFamily:'monospace', fontSize:12.5, fontWeight:500 }}>{itemSummary}</div>
                    </td>
                    <td style={{ textAlign:'right', whiteSpace:'nowrap' }}>{g.recd_qty}</td>
                    <td style={{ textAlign:'right', whiteSpace:'nowrap' }}><span style={{ color:'#16a34a', fontWeight:600 }}>{g.accepted_qty}</span></td>
                    <td style={{ textAlign:'right', whiteSpace:'nowrap', fontFamily:"'Fraunces',serif", fontWeight:600 }}>{fmtCurrency(g.value ?? (g.accepted_qty * g.rate))}</td>
                    <td style={{ whiteSpace:'nowrap' }}><span className="td-code">{g.store_location}</span></td>
                    <td style={{ whiteSpace:'nowrap' }}><StatusBadge status={g.status} /></td>
                  </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Create GRN SlideOver */}
  
      {showDraftChoice && (
        <div role="presentation" style={{ position:'fixed', inset:0, zIndex:1300, background:'rgba(15,23,42,.55)', display:'flex', alignItems:'center', justifyContent:'center', padding:20 }}>
          <div role="dialog" aria-modal="true" aria-labelledby="grn-draft-choice-title" style={{ width:'min(440px, 100%)', background:'#fff', borderRadius:14, padding:24, boxShadow:'0 20px 60px rgba(0,0,0,.25)' }}>
            <h2 id="grn-draft-choice-title" style={{ margin:'0 0 8px', fontSize:20 }}>Unfinished GRN found</h2>
            <p style={{ margin:'0 0 20px', color:'#64748b', fontSize:13, lineHeight:1.5 }}>You have an unfinished GRN draft. Would you like to continue where you left off or start a new GRN?</p>
            <div style={{ display:'flex', justifyContent:'flex-end', gap:8, flexWrap:'wrap' }}>
              <button className="btn btn-outline" onClick={()=>setShowDraftChoice(false)}>Cancel</button>
              <button className="btn btn-outline" onClick={startNewGRN}>Record New GRN</button>
              <button className="btn btn-accent" onClick={continueGRNDraft}>Continue Draft</button>
            </div>
          </div>
        </div>
      )}

      {itemMasterDraft && (
        <div role="presentation" style={{ position:'fixed', inset:0, zIndex:1200, background:'rgba(15,23,42,.55)', display:'flex', alignItems:'center', justifyContent:'center', padding:20 }}>
          <div role="dialog" aria-modal="true" aria-labelledby="new-item-master-title" style={{ width:'min(560px, 100%)', maxHeight:'90vh', overflowY:'auto', background:'#fff', borderRadius:14, padding:22, boxShadow:'0 20px 60px rgba(0,0,0,.25)', fontFamily:"'DM Sans', sans-serif", color:'var(--ink)' }}>
            <div style={{ fontSize:11, color:'#64748b', fontWeight:700, letterSpacing:'.06em', textTransform:'uppercase' }}>Invoice item {itemMasterDraft.index + 1} of {lineItems.length}</div>
            <h2 id="new-item-master-title" style={{ margin:'5px 0 6px', fontSize:20, fontFamily:"'Fraunces', serif", fontWeight:600 }}>
              {itemMasterDraft.possible_matches?.length ? 'Review possible Item Master matches' : 'Add item to Item Master'}
            </h2>
            <p style={{ margin:'0 0 16px', color:'#64748b', fontSize:13 }}>
              {itemMasterDraft.possible_matches?.length
                ? 'These existing items look similar to the invoice description. Select the correct record to reuse its code, or create a new item only if none match.'
                : 'No likely existing Item Master match was found. Review the name, category, and vendor before creating a new record.'}
            </p>
            {!!itemMasterDraft.possible_matches?.length && (
              <div style={{ display:'grid', gap:8, marginBottom:18 }}>
                {itemMasterDraft.possible_matches.map(match => (
                  <div key={match.code} style={{ display:'flex', alignItems:'center', justifyContent:'space-between', gap:12, padding:10, border:'1px solid #dbeafe', borderRadius:8, background:'#f8fbff' }}>
                    <div style={{ minWidth:0 }}>
                      <div style={{ fontWeight:600, color:'#0f172a', fontSize:13 }}>{match.name}</div>
                      <div style={{ fontSize:12, color:'#64748b', marginTop:3 }}>{match.code}{match.category ? ` · ${match.category}` : ''} · {match.score}% match</div>
                    </div>
                    <button type="button" className="btn btn-outline" disabled={savingMasterItem} onClick={() => chooseExistingMasterItem(match)} style={{ flexShrink:0 }}>Use existing</button>
                  </div>
                ))}
                <div style={{ borderTop:'1px solid #e2e8f0', paddingTop:12, color:'#64748b', fontSize:12 }}>
                  If none of these records is correct, create a new item below.
                </div>
              </div>
            )}
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12 }}>
              <label style={{ gridColumn:'1 / -1', fontSize:12, color:'#475569' }}>Item name *
                <input className="input" value={itemMasterDraft.name} onChange={e=>setItemMasterDraft(d=>({...d,name:e.target.value}))} style={{ marginTop:4 }} />
              </label>
              <label style={{ fontSize:12, color:'#475569' }}>Master group *
                {itemMasterDraft.master_group_is_new ? (
                  <div style={{ marginTop:4 }}>
                    <input required autoFocus className="input" value={itemMasterDraft.master_group || ''} onChange={e=>setItemMasterDraft(d=>({...d,master_group:e.target.value}))} placeholder="Enter new master group name" />
                    <button type="button" className="btn btn-outline" style={{ marginTop:6, padding:'4px 9px', fontSize:11 }} onClick={()=>setItemMasterDraft(d=>({...d,master_group:'',master_group_is_new:false,category:'',category_is_new:false}))}>Choose an existing group</button>
                  </div>
                ) : (
                  <select required className="input" value={itemMasterDraft.master_group || ''} onChange={e=>{
                    if(e.target.value==='__create_new__') setItemMasterDraft(d=>({...d,master_group:'',master_group_is_new:true,category:'',category_is_new:false}))
                    else setItemMasterDraft(d=>({...d,master_group:e.target.value,master_group_is_new:false,category:'',category_is_new:false}))
                  }} style={{ marginTop:4 }}>
                    <option value="">Select master group</option>
                    {[...new Set([...masterGroupNames, itemMasterDraft.master_group].map(value=>String(value||'').trim()).filter(Boolean))].sort((a,b)=>a.localeCompare(b)).map(group=><option key={group} value={group}>{group}</option>)}
                    <option value="__create_new__">+ Create New Master Group</option>
                  </select>
                )}
              </label>
              <label style={{ fontSize:12, color:'#475569' }}>Category *
                {itemMasterDraft.category_is_new ? (
                  <div style={{ marginTop:4 }}>
                    <input required autoFocus className="input" value={itemMasterDraft.category || ''} onChange={e=>setItemMasterDraft(d=>({...d,category:e.target.value}))} placeholder="Enter new category name" />
                    <button type="button" className="btn btn-outline" style={{ marginTop:6, padding:'4px 9px', fontSize:11 }} onClick={()=>setItemMasterDraft(d=>({...d,category:'',category_is_new:false}))}>Choose an existing category</button>
                  </div>
                ) : (
                  <select required className="input" value={itemMasterDraft.category || ''} onChange={e=>{
                    if(e.target.value==='__create_new__') setItemMasterDraft(d=>({...d,category:'',category_is_new:true}))
                    else setItemMasterDraft(d=>({...d,category:e.target.value,category_is_new:false}))
                  }} style={{ marginTop:4 }} disabled={!itemMasterDraft.master_group}>
                    <option value="">Select category</option>
                    {[...new Set([
                      ...categories.filter(category => String(category.master_group || '').trim().toLowerCase() === String(itemMasterDraft.master_group || '').trim().toLowerCase()).map(category => category.name),
                      ...items.filter(item => String(item.master_group_name || item.master_group || '').trim().toLowerCase() === String(itemMasterDraft.master_group || '').trim().toLowerCase()).map(item => item.category),
                      ...(CATEGORY_SUGGESTIONS_BY_GROUP[String(itemMasterDraft.master_group || '').trim().toLowerCase()] || []),
                      itemMasterDraft.category,
                    ].map(value=>String(value||'').trim()).filter(Boolean))].sort((a,b)=>a.localeCompare(b)).map(category=><option key={category} value={category}>{category}</option>)}
                    <option value="__create_new__">+ Create New Category</option>
                  </select>
                )}
              </label>
              <label style={{ fontSize:12, color:'#475569' }}>Sub-category
                <input className="input" value={itemMasterDraft.sub_category || ''} onChange={e=>setItemMasterDraft(d=>({...d,sub_category:e.target.value}))} style={{ marginTop:4 }} placeholder="Enter sub-category" list="grn-item-subcategory-options" />
                <datalist id="grn-item-subcategory-options">
                  {[...new Set(items.filter(i=>(i.category||'').trim().toLowerCase()===(itemMasterDraft.category||'').trim().toLowerCase()).map(i=>(i.sub_category||'').trim()).filter(Boolean))].sort().map(subCategory=><option key={subCategory} value={subCategory} />)}
                </datalist>
              </label>
              <label style={{ fontSize:12, color:'#475569' }}>Unit of measurement (from invoice)
                <input className="input" value={itemMasterDraft.uom || ''} readOnly aria-readonly="true" placeholder="Unit not detected in invoice" style={{ marginTop:4, background:'#f8fafc' }} />
                {!itemMasterDraft.uom && <span style={{ display:'block', marginTop:4, color:'#64748b' }}>No unit detected; you can still save this item.</span>}
              </label>
              <label style={{ fontSize:12, color:'#475569' }}>Vendor name {itemMasterDraft.vendor_is_new ? '*' : ''}
                <input className="input" value={itemMasterDraft.vendor_name || ''} readOnly={!itemMasterDraft.vendor_is_new} onChange={e=>setItemMasterDraft(d=>({...d,vendor_name:e.target.value}))} style={{ marginTop:4, background:itemMasterDraft.vendor_is_new ? '#fff' : '#f8fafc' }} placeholder={itemMasterDraft.vendor_is_new ? 'Vendor name from invoice' : 'Fetched from Vendor Directory'} />
                {itemMasterDraft.vendor_is_new && <span style={{ display:'block', marginTop:4, color:'#64748b', fontSize:11 }}>New vendor — verify or correct the invoice name before saving.</span>}
              </label>
              <label style={{ fontSize:12, color:'#475569' }}>Vendor GSTIN {itemMasterDraft.vendor_is_new ? '*' : ''}
                <input className="input" maxLength={15} autoComplete="off" spellCheck={false} value={itemMasterDraft.gst_no || ''} readOnly={!itemMasterDraft.vendor_is_new} onChange={e=>setItemMasterDraft(d=>({...d,gst_no:normalizeGstin(e.target.value)}))} style={{ marginTop:4, background:itemMasterDraft.vendor_is_new ? '#fff' : '#f8fafc' }} placeholder={itemMasterDraft.vendor_is_new ? '15-character GSTIN from invoice' : 'Fetched from Vendor Directory'} />
                <span style={{ display:'block', marginTop:4, color:'#64748b', fontSize:11, textAlign:'right' }}>{normalizeGstin(itemMasterDraft.gst_no).length}/15 characters{itemMasterDraft.vendor_is_new ? ' · editable' : ' · Vendor Directory'}</span>
              </label>
            </div>
            <div style={{ display:'flex', justifyContent:'flex-end', gap:8, marginTop:20 }}>
              <button className="btn btn-outline" disabled={savingMasterItem} onClick={()=>{setItemMasterDraft(null);toast('Item setup paused. Your extracted invoice and pending items are saved in this GRN draft.')}}>Close for now</button>
              <button className="btn btn-accent" disabled={savingMasterItem} onClick={saveNewMasterItem}>{savingMasterItem ? 'Saving…' : 'Save Item'}</button>
            </div>
          </div>
        </div>
      )}
      <SlideOver
          open={showCreate || !!editTarget}
          onClose={closeSlideOver}
          title={editTarget ? `Edit Goods Receipt — ${editTarget.grn_no}` : 'Record Goods Receipt'}
          subtitle={editTarget ? 'Update the details of this GRN' : 'Record delivery against a Purchase Order'}
          footer={<><button className="btn btn-outline" onClick={closeSlideOver}>Cancel</button><button className="btn btn-accent" onClick={createGRN}>{editTarget ? 'Update GRN' : 'Save GRN'}</button></>}
          wide>
          <FormGrid>
            <div style={{ gridColumn:'1/-1', border:'1px dashed #93c5fd', background:'#f8fbff', borderRadius:10, padding:14 }}>
              <div style={{ fontWeight:700, fontSize:13.5, marginBottom:4 }}>Upload Receipt — auto-fill GRN</div>
              <div style={{ fontSize:12, color:'#64748b', marginBottom:10 }}>Upload a receipt as JPG, JPEG, PNG, or PDF. Extracted values are suggestions only; nothing is saved until you review and click Save GRN.</div>
              <div style={{ display:'flex', alignItems:'center', gap:8, flexWrap:'wrap' }}>
                <label style={{ display:'inline-flex', alignItems:'center', gap:6, cursor:extractingDocument ? 'not-allowed' : 'pointer', opacity:extractingDocument ? 0.6 : 1 }}>
                  <span style={{ display:'inline-block', padding:'3px 8px', border:'1px solid #767676', borderRadius:2, background:'#efefef', color:'#111', fontSize:13, lineHeight:'20px' }}>
                    Choose File
                  </span>
                  <span style={{ fontSize:13, color:'#202124' }}>
                    {selectedDocumentName || 'No file chosen'}
                  </span>
                  <input
                    type="file"
                    accept=".jpg,.jpeg,.png,.pdf,image/jpeg,image/png,application/pdf"
                    disabled={extractingDocument}
                    aria-label="Choose receipt file"
                    style={{ position:'absolute', width:1, height:1, padding:0, margin:-1, overflow:'hidden', clip:'rect(0, 0, 0, 0)', whiteSpace:'nowrap', border:0 }}
                    onChange={e => {
                      const file = e.target.files?.[0]
                      if (file) {
                        setSelectedDocumentName(file.name)
                        extractGRNDocument(file)
                      }
                      // Keep the selected filename in React state while allowing the same file to be reselected.
                      e.target.value = ''
                    }}
                  />
                </label>
              </div>
              {extractingDocument && (
                <div style={{ marginTop:8, display:'flex', alignItems:'center', gap:10, flexWrap:'wrap' }}>
                  <span style={{ fontSize:12, color:'#2563eb' }}>Reading document…</span>
                  <button type="button" className="btn btn-outline" onClick={cancelDocumentExtraction} style={{ padding:'3px 10px', fontSize:12 }}>
                    Cancel reading
                  </button>
                </div>
              )}
              {extractionResult && pendingMasterIndexes.length > 0 && !itemMasterDraft && (
                <div style={{ marginTop:10, padding:10, border:'1px solid #f4c66a', borderRadius:8, background:'#fffbeb', display:'flex', alignItems:'center', justifyContent:'space-between', gap:10, flexWrap:'wrap' }}>
                  <div style={{ fontSize:12, color:'#92400e' }}>
                    <strong>{pendingMasterIndexes.length} invoice item{pendingMasterIndexes.length === 1 ? '' : 's'} still need Item Master setup.</strong>
                    <div>Your extracted invoice and GRN draft are retained. Continue whenever you are ready.</div>
                  </div>
                  <button type="button" className="btn btn-accent" onClick={resumePendingMasterSetup}>Review pending items ({pendingMasterIndexes.length})</button>
                </div>
              )}
              {extractionResult && <div style={{ marginTop:10, fontSize:12 }}>
                <div style={{ fontWeight:700, color:'#166534', marginBottom:4 }}>Document processed — manual review required</div>
                {(extractionResult.warnings || []).length > 0 && <ul style={{ margin:'4px 0 0', paddingLeft:18, color:'#92400e' }}>
                  {extractionResult.warnings.map((warning, i) => <li key={i}>{warning}</li>)}
                </ul>}
                <details style={{ marginTop:8 }}><summary style={{ cursor:'pointer', color:'#475569' }}>View extracted text preview</summary>
                  <pre style={{ whiteSpace:'pre-wrap', maxHeight:180, overflow:'auto', fontSize:11, marginTop:6 }}>{extractionResult.extracted_text_preview || 'No readable text detected.'}</pre>
                </details>
              </div>}
            </div>
            {/* ── Top fields ── */}
            <FormRow label="GRN Number" half><input className="input" value={form.grn_no} readOnly placeholder="Assigned when saved" style={{ background:'#f8f9fc', color:'#64748b' }} /></FormRow>
            <FormRow label="GRN Date" half><input className="input" type="date" value={form.grn_date} onChange={e => setForm({...form, grn_date:e.target.value})} /></FormRow>
            <FormRow label="Purchase Order (auto-fills details)">
              <select className="select" value={form.po_no} onChange={e => selectPO(e.target.value)}>
                <option value="">Select PO…</option>
                {pos.filter(p => !['Fully Received','Closed'].includes(p.status)).map(p => <option key={p.po_no} value={p.po_no}>{p.po_no} — {p.item_name} ({p.status})</option>)}
              </select>
            </FormRow>
            <FormRow label="Invoice Number" half><input className="input" value={form.invoice_no} onChange={e => setForm({...form, invoice_no:e.target.value})} placeholder="Enter invoice number" /></FormRow>
            <FormRow label="Store Location" half>
              <select className="select" value={form.store_location} onChange={e => setForm({...form, store_location:e.target.value})}>
                <option value=''>— Select location —</option>
                {locs.map(l => <option key={l.code} value={l.code}>{l.code} — {l.name}</option>)}
              </select>
            </FormRow>

            {/* ── Line Items — card layout, internally scrollable ── */}
            <div style={{ gridColumn:'1/-1' }}>
              <div style={{ fontWeight:600, fontSize:13.5, marginBottom:8 }}>Line Items</div>
              <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
                {lineItems.map((row, idx) => (
                  <div key={row.id} style={{
                    border: `1px solid ${rowError && !row.item_code ? '#dc2626' : '#e2e8f0'}`,
                    borderRadius:10, padding:'10px 12px', background:'#fafbfc',
                  }}>
                    {/* Card row 1: Item search + Vendor search + delete */}
                    <div style={{ display:'flex', gap:8, marginBottom:8 }}>
                      <div style={{ flex:1, minWidth:0 }}>
                        <div style={{ fontSize:11, color:'#64748b', marginBottom:3 }}>Item *</div>
                        {row.is_charge_line ? (
                          <div className="input" style={{ background:'#f8fafc', color:'#475569', minHeight:38, display:'flex', alignItems:'center' }}>
                            {row.item_name}
                          </div>
                        ) : <ComboSearch
                          query={row.item_code}
                          onQueryChange={val => {
                            const updated = [...lineItems]
                            updated[idx].item_code = val
                            setLineItems(updated)
                          }}
                          onSelect={opt => {
                            const updated = [...lineItems]
                            updated[idx] = {
                              ...updated[idx],
                              item_code: opt.code,
                              item_name: opt.name,
                              rate: Number(opt.rate) || 0,
                            }
                            setLineItems(updated)
                          }}
                          options={items.map(i => ({ code: i.code, name: i.name, rate: i.rate }))}
                          placeholder="HK-003 or item name…"
                          hasError={rowError && !row.item_code}
                        />}
                        {row.item_name && <div style={{ fontSize:11, color:'#94a3b8', marginTop:3, paddingLeft:2 }}>{row.item_name}</div>}
                        {row.needs_review && (
                          <div role="status" style={{ fontSize:11, color:'#b45309', marginTop:5, padding:'5px 7px', background:'#fffbeb', borderRadius:5 }}>
                            {'Review extracted values' + (row.extraction_warning ? ': ' + row.extraction_warning : ' before saving.')}
                          </div>
                        )}
                      </div>
                      <div style={{ flex:1, minWidth:0 }}>
                        <div style={{ fontSize:11, color:'#64748b', marginBottom:3 }}>Vendor</div>
                        <ComboSearch
                          query={row.vendor_code}
                          onQueryChange={val => {
                            const updated = [...lineItems]
                            updated[idx].vendor_code = val
                            setLineItems(updated)
                          }}
                          onSelect={opt => {
                            const updated = [...lineItems]
                            updated[idx].vendor_code = opt.code
                            updated[idx].vendor_name = opt.name
                            setLineItems(updated)
                          }}
                          options={vendors.map(v => ({ code: v.code, name: v.name }))}
                          placeholder="V-001 or vendor name…"
                        />
                        {row.vendor_name && <div style={{ fontSize:11, color:'#94a3b8', marginTop:3, paddingLeft:2 }}>{row.vendor_name}</div>}
                      </div>
                      <button
                        className="btn btn-outline"
                        style={{ alignSelf:'flex-start', marginTop:18, flexShrink:0 }}
                        onClick={() => { if (lineItems.length > 1) setLineItems(lineItems.filter((_, i) => i !== idx)) }}
                      >×</button>
                    </div>
                    {/* Card row 2: Qty Recd + Qty Accepted + Rate + Unit */}
                    <div style={{ display:'flex', gap:8, flexWrap:'wrap' }}>
                      <div style={{ flex:'1 1 105px', minWidth:0 }}>
                        <div style={{ fontSize:11, color:'#64748b', marginBottom:3 }}>Unit</div>
                        <input className="input" value={row.uom || ''} placeholder="From invoice" onChange={e => { const updated=[...lineItems]; updated[idx].uom=e.target.value; setLineItems(updated) }} />
                      </div>
                      <div style={{ flex:1 }}>
                        <div style={{ fontSize:11, color:'#64748b', marginBottom:3 }}>Qty Recd</div>
                        <input className="input" type="number" min="0"
                          value={row.recd_qty ?? ''}
                          onChange={e => {
                            const val = e.target.value
                            const updated = [...lineItems]
                            updated[idx].recd_qty = val === '' ? '' : Number(val)
                            setLineItems(updated)
                          }}
                        />
                      </div>
                      <div style={{ flex:1 }}>
                        <div style={{ fontSize:11, color:'#64748b', marginBottom:3 }}>Qty Accepted *</div>
                        <input className="input" type="number" min="0"
                          value={row.accepted_qty ?? ''}
                          onChange={e => {
                            const val = e.target.value
                            const updated = [...lineItems]
                            updated[idx].accepted_qty = val === '' ? '' : Number(val)
                            setLineItems(updated)
                          }}
                        />
                      </div>
                      <div style={{ flex:1 }}>
                        <div style={{ fontSize:11, color:'#64748b', marginBottom:3 }}>Rate ₹</div>
                        <input className="input" type="number" min="0" step="0.01"
                          value={row.rate ?? ''}
                          onChange={e => {
                            const val = e.target.value
                            const updated = [...lineItems]
                            updated[idx].rate = val === '' ? '' : Number(val)
                            setLineItems(updated)
                          }}
                        />
                        {row.rate_warning && (
                          <div role="status" style={{ fontSize:10.5, color:'#b45309', marginTop:4, lineHeight:1.35 }}>
                            Warning - The rate for this line item is unreadable.
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <button className="btn btn-outline" style={{ marginTop:8 }}
                onClick={() => setLineItems([...lineItems, emptyRow()])}>
                + Add Item
              </button>
            </div>

            {/* ── Bottom fields ── */}
            <FormRow label="Received By" half><input className="input" value={form.received_by} onChange={e => setForm({...form, received_by:e.target.value})} /></FormRow>
            <FormRow label="Inspected By" half><input className="input" value={form.inspected_by} onChange={e => setForm({...form, inspected_by:e.target.value})} /></FormRow>
            <FormRow label="Batch / Lot No" half><input className="input" value={form.batch_lot} onChange={e => setForm({...form, batch_lot:e.target.value})} placeholder="B005" /></FormRow>
            <FormRow label="GRN Status" half>
              <select className="select" value={form.status} onChange={e => setForm({...form, status:e.target.value})}>
                {['Pending Inspection','Inspected - OK','Inspected - Rejected','Partial Accept','Stored','Returned'].map(s => <option key={s}>{s}</option>)}
              </select>
            </FormRow>
            <FormRow label="Remarks"><textarea className="input" rows={2} value={form.remarks} onChange={e => setForm({...form, remarks:e.target.value})} placeholder="Quality notes, damage details, etc." /></FormRow>
          </FormGrid>

          {/* Accepted value and GST summary — GST is calculated at 18% (9% CGST + 9% SGST) */}
          {(() => {
            const acceptedValue = lineItems.reduce((sum, row) => sum + (row.is_charge_line ? Number(row.line_amount || 0) : Number(row.accepted_qty || 0) * Number(row.rate || 0)), 0)
            const cgst = Math.round(acceptedValue * 0.09 * 100) / 100
            const sgst = Math.round(acceptedValue * 0.09 * 100) / 100
            const finalAmount = acceptedValue + cgst + sgst
            return acceptedValue > 0 ? (
              <div style={{ background:'#f0fdf4', borderRadius:10, padding:14, marginTop:8, display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(125px, 1fr))', gap:16 }}>
                <div>
                  <div style={{ fontSize:11, color:'#64748b', marginBottom:3 }}>Accepted Value</div>
                  <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, color:'#16a34a', fontSize:18 }}>{fmtCurrency(acceptedValue)}</div>
                </div>
                <div>
                  <div style={{ fontSize:11, color:'#64748b', marginBottom:3 }}>CGST (9%)</div>
                  <div style={{ fontWeight:600, fontSize:16 }}>{fmtCurrency(cgst)}</div>
                </div>
                <div>
                  <div style={{ fontSize:11, color:'#64748b', marginBottom:3 }}>SGST (9%)</div>
                  <div style={{ fontWeight:600, fontSize:16 }}>{fmtCurrency(sgst)}</div>
                </div>
                <div>
                  <div style={{ fontSize:11, color:'#64748b', marginBottom:3 }}>Final Amount (18% GST)</div>
                  <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, color:'#0f766e', fontSize:20 }}>{fmtCurrency(finalAmount)}</div>
                </div>
              </div>
            ) : null
          })()}
        </SlideOver>
      </div>
        <DeleteToolbar dm={dm} label="grn" />

        {/* ── View GRN SlideOver (read-only) ── */}
        <SlideOver
          open={!!viewGrn}
          onClose={() => setViewGrn(null)}
          title={`GRN ${viewGrn?.grn_no}`}
          subtitle="Goods Receipt Details"
          wide
          footer={
            isAdmin && (
              <button className="btn btn-accent" onClick={() => { const g = viewGrn; setViewGrn(null); openEdit(g) }}>
                Edit GRN
              </button>
            )
          }
        >
          {viewGrn && (() => {
            const items = Array.isArray(viewGrn.line_items) && viewGrn.line_items.length > 0
              ? viewGrn.line_items
              : (() => { try { return JSON.parse(viewGrn.line_items || '[]') } catch { return [] } })()
            const totalAccepted = items.reduce((s, li) => s + Number(li.accepted_qty || 0), 0)
            const totalValue = items.reduce((s, li) => s + Number(li.accepted_qty || 0) * Number(li.rate || 0), 0)

            return (
              <>
                {/* Header Info */}
                <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'10px 20px', marginBottom:20 }}>
                  {[
                    { label:'Date',     value: fmtDate(viewGrn.grn_date) },
                    { label:'Status',   value: <StatusBadge status={viewGrn.status} /> },
                    { label:'Vendor',   value: viewGrn.vendor_name || '—' },
                    { label:'Invoice',  value: viewGrn.invoice_no || '—' },
                    { label:'PO Ref',   value: viewGrn.po_no || '—' },
                    { label:'Location', value: viewGrn.store_location || '—' },
                    { label:'Received By',  value: viewGrn.received_by || '—' },
                    { label:'Inspected By', value: viewGrn.inspected_by || '—' },
                  ].map(({ label, value }) => (
                    <div key={label}>
                      <div style={{ fontSize:11, color:'#94a3b8', marginBottom:2 }}>{label}</div>
                      <div style={{ fontSize:13.5, fontWeight:500, color:'#0d0f1a' }}>{value}</div>
                    </div>
                  ))}
                  {viewGrn.remarks && (
                    <div style={{ gridColumn:'1/-1' }}>
                      <div style={{ fontSize:11, color:'#94a3b8', marginBottom:2 }}>Remarks</div>
                      <div style={{ fontSize:13, color:'#475569' }}>{viewGrn.remarks}</div>
                    </div>
                  )}
                </div>

                {/* Totals */}
                {(totalAccepted > 0 || totalValue > 0) && (
                  <div style={{ display:'flex', gap:20, background:'#f0fdf4', borderRadius:10, padding:'12px 16px', marginBottom:16 }}>
                    <div>
                      <div style={{ fontSize:11, color:'#94a3b8' }}>Total Accepted Qty</div>
                      <div style={{ fontWeight:700, fontSize:18, color:'#16a34a' }}>{totalAccepted}</div>
                    </div>
                    <div>
                      <div style={{ fontSize:11, color:'#94a3b8' }}>Total Value</div>
                      <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:18, color:'#16a34a' }}>{fmtCurrency(totalValue)}</div>
                    </div>
                  </div>
                )}

                {/* Line Items */}
                <div style={{ fontWeight:600, fontSize:13.5, marginBottom:10, color:'#0d0f1a' }}>
                  Line Items ({items.length})
                </div>
                {items.length === 0 && (
                  <div style={{ fontSize:13, color:'#94a3b8', padding:'12px 0' }}>No line items recorded.</div>
                )}
                <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
                  {items.map((li, i) => (
                    <div key={i} style={{
                      border:'1px solid #e2e8f0', borderRadius:10,
                      padding:'12px 14px', background:'#fafbfc',
                    }}>
                      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:6 }}>
                        <div>
                          <span style={{ fontFamily:'monospace', fontWeight:700, fontSize:13, color:'#0d0f1a' }}>{li.item_code}</span>
                          {li.vendor_code && <span style={{ marginLeft:8, fontFamily:'monospace', fontSize:11.5, color:'#94a3b8' }}>{li.vendor_code}</span>}
                        </div>
                        <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:14, color:'#16a34a' }}>
                          {fmtCurrency(Number(li.accepted_qty || 0) * Number(li.rate || 0))}
                        </div>
                      </div>
                      {li.item_name && <div style={{ fontSize:12, color:'#64748b', marginBottom:8 }}>{li.item_name}</div>}
                      <div style={{ display:'flex', gap:16, fontSize:12.5 }}>
                        <div><span style={{ color:'#94a3b8' }}>Received: </span><span style={{ fontWeight:600 }}>{li.recd_qty ?? li.qty_received ?? '—'}</span></div>
                        <div><span style={{ color:'#94a3b8' }}>Accepted: </span><span style={{ fontWeight:600, color:'#16a34a' }}>{li.accepted_qty ?? li.qty_accepted ?? '—'}</span></div>
                        <div><span style={{ color:'#94a3b8' }}>Rate: </span><span style={{ fontWeight:600 }}>₹{li.rate ?? '—'}</span></div>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )
          })()}
        </SlideOver>
    </>
  )
}
