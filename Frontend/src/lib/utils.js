export const fmtCurrency = (n) => {
  if (n === null || n === undefined) return '₹0'
  if (n >= 10000000) return `₹${(n/10000000).toFixed(2)}Cr`
  if (n >= 100000) return `₹${(n/100000).toFixed(1)}L`
  if (n >= 1000) return `₹${(n/1000).toFixed(1)}k`
  return `₹${Number(n).toLocaleString('en-IN')}`
}
export const fmtNum = (n) => n ? Number(n).toLocaleString('en-IN') : '0'
export const fmtDate = (d) => d ? new Date(d).toLocaleDateString('en-IN', { day:'2-digit', month:'short', year:'numeric' }) : '-'

export const CATEGORY_COLORS = {
  'Cleaning Chemicals': '#06b6d4',
  'Washroom Supplies': '#8b5cf6',
  'Cleaning Tools': '#10b981',
  'Waste Management': '#f59e0b',
  'Pantry': '#f97316',
  'Electrical': '#3b82f6',
  'PPE & Safety': '#ec4899',
  'Pest Control': '#84cc16',
  'Other': '#94a3b8',
}

export const PRIORITY_CONFIG = {
  Urgent: { color: '#ef4444', bg: '#fef2f2', label: 'Urgent' },
  High:   { color: '#f97316', bg: '#fff7ed', label: 'High' },
  Normal: { color: '#3b82f6', bg: '#eff6ff', label: 'Normal' },
  Low:    { color: '#94a3b8', bg: '#f8fafc', label: 'Low' },
}
export const STATUS_CONFIG = {
  Approved:          { color: '#10b981', bg: '#f0fdf4' },
  'Fully Received':  { color: '#10b981', bg: '#f0fdf4' },
  Stored:            { color: '#10b981', bg: '#f0fdf4' },
  Active:            { color: '#10b981', bg: '#f0fdf4' },
  Draft:             { color: '#94a3b8', bg: '#f8fafc' },
  Submitted:         { color: '#3b82f6', bg: '#eff6ff' },
  'Sent to Vendor':  { color: '#8b5cf6', bg: '#f5f3ff' },
  'Partial Received':{ color: '#f59e0b', bg: '#fffbeb' },
  Rejected:          { color: '#ef4444', bg: '#fef2f2' },
  'Below ROL':       { color: '#ef4444', bg: '#fef2f2' },
  'Negative Stock':  { color: '#ffffff', bg: '#dc2626' },
  OK:                { color: '#10b981', bg: '#f0fdf4' },
}
export const fmt = {
  currency: fmtCurrency,
  currencyFull: (n) => `₹${Number(n || 0).toLocaleString('en-IN')}`,
  number: fmtNum,
  date: fmtDate
}