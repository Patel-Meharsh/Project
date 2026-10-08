import { useState, useRef } from 'react'
import Header from '../components/Header'
import { fmtCurrency } from '../lib/utils'
import api from '../lib/api'  


const ENTITIES = [
  {
    key:      'hk_master',
    label:    'HK Benchmark Catalog',
    icon:     '📋',
    desc:     'Import 128-item HK catalog with Economy / Standard / Premium pricing',
    fields:   'code, name, category, sub_category, uom, eco_brand, eco_price, std_brand, std_price, prem_brand, prem_price, recommended, rate, gst_pct, rol, max_stock, lead_days',
    color:    '#eff6ff', border: '#bfdbfe', accent: '#1e40af',
  },
  {
    key:      'items',
    label:    'Active Item Master',
    icon:     '🗂',
    desc:     'Import active items with rates, ROL, lead days and vendor codes',
    fields:   'code, name, category, uom, brand_tier, vendor_code, rate, gst_pct, rol, max_stock, lead_days',
    color:    '#f0fdf4', border: '#bbf7d0', accent: '#166534',
  },
  {
  key:      'vendors',
  label:    'Vendor Directory',
  icon:     '🏭',
  desc:     'Import vendors with contact details, GST, payment terms and rating',
  fields:   'code, name, category, contact_person, phone, email, city, gst_no, pan, payment_terms, rating, status',
  color:    '#fefce8',
  border:   '#fde68a',
  accent:   '#854d0e',
  },
  {
    key:      'locations',
    label:    'Locations & Fixtures',
    icon:     '📍',
    desc:     'Import sites with area, headcount, washrooms, ACs, pantries etc.',
    fields:   'code, name, city, type, contact_person, phone, status, area_sqft, headcount, num_washrooms, num_urinals, num_wcs, num_wash_basins, num_pantries, num_meeting_rooms, num_ac_units, num_fans',
    color:    '#fdf4ff', border: '#e9d5ff', accent: '#7e22ce',
  },
  {
    key:      'norms',
    label:    'Consumption Norms',
    icon:     '📐',
    desc:     'Import usage benchmarks that drive the budget calculator',
    fields:   'item_code, item_name, category, basis, norm_value, norm_unit, rate, cost_per_unit, frequency, remarks',
    color:    '#fff7ed', border: '#fed7aa', accent: '#c2410c',
  },
  {
    key:      'issuances',
    label:    'Issuance Log',
    icon:     '↗',
    desc:     'Import historical issuance records — populates spend charts and vs-actual',
    fields:   'issue_id, date, month, quarter, item_code, item_name, qty, uom, rate, value, location_code, department, issued_to, issued_by, remarks',
    color:    '#f8fafc', border: '#e2e8f0', accent: '#334155',
  },
  {
    key:      'returns',
    label:    'Returns Log',
    icon:     '↩️',
    desc:     'Import vendor return records with credit note and status',
    fields:   'return_id, return_date, grn_ref, item_code, item_name, qty_returned, vendor_code, reason, status, credit_note, remarks',
    color:    '#fef2f2', border: '#fecaca', accent: '#991b1b',
  },
]

const MAPPINGS = {
  locations: {
    code: 'location_code', name: 'location_name', area_sqft: 'area_sq_ft',
    num_washrooms: 'no_of_washrooms', num_urinals: 'no_of_urinals',
    num_wcs: 'no_of_wcs', num_wash_basins: 'no_of_wash_basins',
    num_pantries: 'no_of_pantries', num_meeting_rooms: 'no_of_meeting_rooms',
    num_ac_units: 'no_of_ac_units', num_fans: 'no_of_fans',
  },
  items: { code: 'item_code', name: 'item_name', rate: 'rate', gst_pct: 'gst_pct' },
  norms: {
    norm_value:    'value',
    norm_unit:     'unit',
    cost_per_unit: 'unit_cost',
  },
}

function appendMapping(fd, entityKey) {
  if (MAPPINGS[entityKey]) fd.append('mapping', JSON.stringify(MAPPINGS[entityKey]))
}

function UploadZone({ entity, onResult }) {
  const [state,    setState]   = useState('idle')   // idle | previewing | uploading | done | error
  const [preview,  setPreview] = useState(null)
  const [result,   setResult]  = useState(null)
  const [file,     setFile]    = useState(null)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef()

  const handleFile = async (f) => {
    if (!f) return
    setFile(f); setState('previewing')
    const fd = new FormData(); fd.append('file', f); fd.append('entity', entity.key)
    appendMapping(fd, entity.key)
    try {
      const r = await api.post('/import/preview', fd)
      const d = r.data
      if (d.error) { setState('error'); setResult({ error: d.error }); return }
      setPreview(d)
    } catch (e) { setState('error'); setResult({ error: e.message }) }
  }

  const doImport = async () => {
    if (!file) return
    setState('uploading')
    const fd = new FormData(); fd.append('file', file)
    appendMapping(fd, entity.key)
    try {
      const r = await api.post(`/import/${entity.key}`, fd)
      const d = r.data
      setResult(d); setState('done')
      onResult && onResult(entity.key, d)
    } catch (e) { setState('error'); setResult({ error: e.message }) }
  }

  const reset = () => { setState('idle'); setPreview(null); setResult(null); setFile(null) }

  const downloadTemplate = () => {
    window.open(`${api.defaults.baseURL}/import/template/${entity.key}`, '_blank')
  }

  return (
    <div style={{ border:`1px solid ${entity.border}`, borderRadius:14, background:entity.color, overflow:'hidden' }}>
      {/* Header */}
      <div style={{ padding:'18px 20px 14px', borderBottom:`1px solid ${entity.border}` }}>
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between' }}>
          <div style={{ display:'flex', alignItems:'center', gap:10 }}>
            <span style={{ fontSize:24 }}>{entity.icon}</span>
            <div>
              <div style={{ fontFamily:"'Fraunces',serif", fontWeight:600, fontSize:15, color:'#0d0f1a' }}>{entity.label}</div>
              <div style={{ fontSize:12, color:'#64748b', marginTop:2 }}>{entity.desc}</div>
            </div>
          </div>
          <button onClick={downloadTemplate} style={{ display:'flex', alignItems:'center', gap:5, padding:'5px 12px', borderRadius:7, border:`1px solid ${entity.border}`, background:'white', fontSize:12, color:entity.accent, cursor:'pointer', fontWeight:500, whiteSpace:'nowrap' }}>
            ⬇ Template
          </button>
        </div>
        <div style={{ marginTop:10, fontSize:11, color:'#94a3b8', fontFamily:"'JetBrains Mono',monospace", lineHeight:1.6, wordBreak:'break-all' }}>
          Required columns: {entity.fields}
        </div>
      </div>

      {/* Body */}
      <div style={{ padding:'16px 20px 20px' }}>
        {state === 'idle' && (
          <div
            onDragOver={e => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={e => { e.preventDefault(); setDragging(false); handleFile(e.dataTransfer.files[0]) }}
            onClick={() => inputRef.current.click()}
            style={{ border:`2px dashed ${dragging ? entity.accent : entity.border}`, borderRadius:10, padding:'28px 20px', textAlign:'center', cursor:'pointer', transition:'all 0.15s', background: dragging ? 'rgba(255,255,255,0.7)' : 'transparent' }}>
            <div style={{ fontSize:32, marginBottom:8 }}>📂</div>
            <div style={{ fontWeight:500, color:'#374151', fontSize:13.5 }}>Drop your Excel file here</div>
            <div style={{ fontSize:12, color:'#94a3b8', marginTop:4 }}>or click to browse · .xlsx or .csv</div>
            <input ref={inputRef} type="file" accept=".xlsx,.xls,.csv" style={{ display:'none' }} onChange={e => handleFile(e.target.files[0])} />
          </div>
        )}

        {state === 'previewing' && preview && (
          <div>
            <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:12 }}>
              <div>
                <div style={{ fontWeight:600, fontSize:13.5, color:'#0d0f1a' }}>📄 {file?.name}</div>
                <div style={{ fontSize:12, color:'#64748b', marginTop:2 }}>{preview.row_count} rows detected · {preview.columns.length} columns</div>
              </div>
              <div style={{ display:'flex', gap:8 }}>
                <button onClick={reset} style={{ padding:'6px 14px', borderRadius:7, border:'1px solid #dde1ec', background:'white', fontSize:12.5, cursor:'pointer' }}>✕ Cancel</button>
                <button onClick={doImport} style={{ padding:'6px 16px', borderRadius:7, border:'none', background:'#0d0f1a', color:'white', fontSize:12.5, cursor:'pointer', fontWeight:500 }}>⬆ Import {preview.row_count} rows</button>
              </div>
            </div>

            {/* Column match check */}
            <div style={{ marginBottom:12 }}>
              <div style={{ fontSize:11, color:'#94a3b8', textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:6 }}>Detected Columns</div>
              <div style={{ display:'flex', flexWrap:'wrap', gap:5 }}>
                {preview.columns.map(c => (
                  <span key={c} style={{ padding:'2px 8px', borderRadius:5, background:'white', border:`1px solid ${entity.border}`, fontSize:11, fontFamily:"'JetBrains Mono',monospace", color:entity.accent }}>{c}</span>
                ))}
              </div>
            </div>

            {/* Preview table */}
            <div style={{ overflowX:'auto', borderRadius:8, border:'1px solid #edf0f7', background:'white' }}>
              <table style={{ borderCollapse:'collapse', width:'100%', minWidth:500 }}>
                <thead>
                  <tr>{preview.columns.map(c => <th key={c} style={{ padding:'8px 12px', background:'#f8f9fc', fontSize:10, fontWeight:600, color:'#64748b', textTransform:'uppercase', textAlign:'left', whiteSpace:'nowrap', borderBottom:'1px solid #edf0f7' }}>{c}</th>)}</tr>
                </thead>
                <tbody>
                  {preview.preview.map((row, i) => (
                    <tr key={i} style={{ borderBottom:'1px solid #f8f9fc' }}>
                      {preview.columns.map(c => <td key={c} style={{ padding:'7px 12px', fontSize:12, color:'#374151', whiteSpace:'nowrap', maxWidth:160, overflow:'hidden', textOverflow:'ellipsis' }}>{row[c]}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {state === 'uploading' && (
          <div style={{ textAlign:'center', padding:'28px 0' }}>
            <div style={{ width:36, height:36, border:'3px solid #f1f3f8', borderTopColor:entity.accent, borderRadius:'50%', animation:'spin 0.7s linear infinite', margin:'0 auto 12px' }} />
            <div style={{ fontSize:13.5, color:'#374151', fontWeight:500 }}>Importing rows…</div>
            <div style={{ fontSize:12, color:'#94a3b8', marginTop:4 }}>Validating and writing to database</div>
          </div>
        )}

        {state === 'done' && result && (
          <div>
            <div style={{ display:'flex', gap:10, marginBottom:14 }}>
              {[
                { label:'Imported',  value:result.imported, bg:'#f0fdf4', color:'#16a34a', ic:'✅' },
                { label:'Skipped',   value:result.skipped,  bg:'#fffbeb', color:'#d97706', ic:'⚠️' },
                { label:'Errors',    value:result.errors?.length||0, bg:'#fef2f2', color:'#dc2626', ic:'❌' },
              ].map(s => (
                <div key={s.label} style={{ flex:1, background:s.bg, borderRadius:10, padding:'12px 14px', textAlign:'center' }}>
                  <div style={{ fontSize:22 }}>{s.ic}</div>
                  <div style={{ fontFamily:"'Fraunces',serif", fontWeight:700, fontSize:24, color:s.color }}>{s.value}</div>
                  <div style={{ fontSize:11, color:s.color, marginTop:2, fontWeight:500 }}>{s.label}</div>
                </div>
              ))}
            </div>

            {result.errors?.length > 0 && (
              <div style={{ background:'#fef2f2', borderRadius:8, padding:12, marginBottom:12, maxHeight:140, overflowY:'auto' }}>
                <div style={{ fontSize:11, color:'#991b1b', fontWeight:600, marginBottom:6 }}>Row Errors</div>
                {result.errors.map((e,i) => <div key={i} style={{ fontSize:11, color:'#991b1b', fontFamily:"'JetBrains Mono',monospace", marginBottom:2 }}>{e}</div>)}
              </div>
            )}

            <button onClick={reset} style={{ width:'100%', padding:'8px', borderRadius:8, border:'1px solid #dde1ec', background:'white', fontSize:13, cursor:'pointer', color:'#374151', fontWeight:500 }}>
              ⬆ Import another file
            </button>
          </div>
        )}

        {state === 'error' && (
          <div>
            <div style={{ background:'#fef2f2', borderRadius:8, padding:14, marginBottom:10 }}>
              <div style={{ fontSize:13, color:'#dc2626', fontWeight:600 }}>❌ Import failed</div>
              <div style={{ fontSize:12, color:'#991b1b', marginTop:4 }}>{result?.error}</div>
            </div>
            <button onClick={reset} style={{ padding:'6px 14px', borderRadius:7, border:'1px solid #dde1ec', background:'white', fontSize:12.5, cursor:'pointer' }}>Try again</button>
          </div>
        )}
      </div>
    </div>
  )
}

export default function Import() {
  const [log, setLog] = useState([])

  const onResult = (key, result) => {
    setLog(prev => [{ key, time: new Date().toLocaleTimeString(), ...result }, ...prev].slice(0, 20))
  }

  const totalImported = log.reduce((s, r) => s + (r.imported || 0), 0)

  return (
    <>
      <Header
        title="Import Hub"
        subtitle="Import data from Excel sheets into the system — drag, preview, then confirm"
      />
      <div className="page-content">

        {/* Session summary */}
        {log.length > 0 && (
          <div style={{ background:'#f0fdf4', border:'1px solid #bbf7d0', borderRadius:12, padding:'14px 20px', marginBottom:24, display:'flex', alignItems:'center', gap:16 }}>
            <span style={{ fontSize:24 }}>✅</span>
            <div>
              <div style={{ fontWeight:600, color:'#166534', fontSize:14 }}>{totalImported} rows imported this session</div>
              <div style={{ fontSize:12, color:'#16a34a', marginTop:2 }}>
                {log.map(r => `${r.key} (${r.imported} rows)`).join(' · ')}
              </div>
            </div>
          </div>
        )}

        {/* Tip banner */}
        <div className="alert-strip info" style={{ marginBottom:24 }}>
          💡 <strong>How it works:</strong> 
          <span>
            Download a template → fill your data → upload the file → preview rows → confirm import.
          </span>

          <span style={{ opacity: 0.7 }}>
            Existing codes updated • new codes inserted • invalid rows skipped.
          </span>

        </div>

        {/* Grid of upload zones */}
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
          {ENTITIES.map(e => <UploadZone key={e.key} entity={e} onResult={onResult} />)}
        </div>

        <div style={{ marginTop:20, padding:'14px 20px', background:'white', borderRadius:12, border:'1px solid #edf0f7', fontSize:12, color:'#94a3b8', lineHeight:1.8 }}>
          <strong style={{ color:'#374151' }}>Notes:</strong> Files must be .xlsx or .csv · First row must be column headers matching the listed field names ·
          Use the ⬇ Template button to get a pre-formatted file with a sample row · Column names are case-insensitive ·
          Spaces and hyphens in headers are auto-converted to underscores · Date fields should be in YYYY-MM-DD format
        </div>
      </div>
    </>
  )
}
