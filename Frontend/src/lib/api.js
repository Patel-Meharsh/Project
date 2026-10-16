import axios from 'axios'

/**
 * In development:  calls backend directly at http://localhost:8000
 * In production:   VITE_API_URL = https://your-backend.com  (set in .env or CI/CD)
 *
 * Never hardcode localhost here.
 */
const BASE =
  import.meta.env.MODE === "development"
    ? "http://localhost:8000"
    : (import.meta.env.VITE_API_URL || "https://api.opex.vaanilabs.ai");

const api = axios.create({ baseURL: BASE + '/api', withCredentials: true });

// Redirect protected-page requests on 401, but leave auth requests alone.
// In particular, /auth/me returning 401 is normal when no session exists yet;
// redirecting during the initial session check can interrupt the login flow.
api.interceptors.response.use(
  r => r,
  err => {
    const status = err.response?.status
    const url = String(err.config?.url || '')
    const isAuthRequest = /\/auth\/(me|login|signup|logout)(?:\?|$)/.test(url)
    if (status === 401 && !isAuthRequest && window.location.pathname !== '/login') {
      window.location.assign('/login')
    }
    return Promise.reject(err)
  }
)

// ── INVENTORY ─────────────────────────────────────────────────────────────────
export const inventoryApi = {
  getAll:        (loc) => api.get('/inventory', { params: loc ? { location: loc } : {} }).then(r => Array.isArray(r.data) ? r.data : []),
  getConsumption: ()  => api.get('/inventory/consumption').then(r => Array.isArray(r.data) ? r.data : []),
  update:   (id, data) => api.put(`/inventory/${id}`, data).then(r => r.data),
  create:   (data) => api.post('/inventory', data).then(r => r.data),
  stockHistory: (itemCode) => api.get(`/inventory/${itemCode}/stock-history`).then(r => Array.isArray(r.data) ? r.data : []),
  reset: (id) => api.patch(`/inventory/${id}/reset`).then(r => r.data),
}

// ── HK MASTER ─────────────────────────────────────────────────────────────────
export const hkApi = {
  getAll:  () => api.get('/hk-master').then(r => Array.isArray(r.data) ? r.data : []),
  create:  (data) => api.post('/hk-master', data).then(r => r.data),
  update:  (code, data) => api.put(`/hk-master/${code}`, data).then(r => r.data),
}

// ── ITEMS ─────────────────────────────────────────────────────────────────────
export const itemApi = {
  getAll:  () => api.get('/items').then(r => Array.isArray(r.data) ? r.data : []),
  create:  (data) => api.post('/items', data).then(r => r.data),
  update:  (code, data) => api.put(`/items/${code}`, data).then(r => r.data),
}

// ── VENDORS ───────────────────────────────────────────────────────────────────
export const vendorApi = {
  getAll:   () => api.get('/vendors').then(r => Array.isArray(r.data) ? r.data : []),
  create:   (data) => api.post('/vendors', data).then(r => r.data),
  update:   (code, data) => api.put(`/vendors/${code}`, data).then(r => r.data),
  getProfile: (code) => api.get(`/vendors/${code}/profile`).then(r => r.data),
}

// ── VENDOR RATE CARDS ─────────────────────────────────────────────────────────
export const rateCardApi = {
  list:   (vendorCode) =>
    api.get(`/vendors/${vendorCode}/rate-cards`).then(r => Array.isArray(r.data) ? r.data : []),
  upload: (vendorCode, file, onProgress) => {
    const fd = new FormData(); fd.append('file', file)
    return api.post(`/vendors/${vendorCode}/rate-cards`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(Math.round((e.loaded * 100) / e.total))
      },
    }).then(r => r.data)
  },
  fetchBlob: (vendorCode, rateCardId) =>
    api.get(`/vendors/${vendorCode}/rate-cards/${rateCardId}`, { responseType: 'blob' })
       .then(r => r.data),
  delete: (vendorCode, rateCardId) =>
    api.delete(`/vendors/${vendorCode}/rate-cards/${rateCardId}`).then(r => r.data),
}

// ── LOCATIONS ─────────────────────────────────────────────────────────────────
export const locationApi = {
  getAll:  () => api.get('/locations').then(r => Array.isArray(r.data) ? r.data : []),
  create:  (data) => api.post('/locations', data).then(r => r.data),
  update:     (code, data)        => api.put(`/locations/${code}`, data).then(r => r.data),
  get:        (code)             => api.get(`/locations/${code}`).then(r => r.data),
  addService: (code, data)       => api.post(`/locations/${code}/services`, data).then(r => r.data),
}

// ── PURCHASE REQUISITIONS ─────────────────────────────────────────────────────
export const prApi = {
  getAll:  () => api.get('/purchase-requisitions').then(r => Array.isArray(r.data) ? r.data : []),
  create:  (data) => api.post('/purchase-requisitions', data).then(r => r.data),
  update:  (no, data) => api.put(`/purchase-requisitions/${no}`, data).then(r => r.data),
}

// ── PURCHASE ORDERS ───────────────────────────────────────────────────────────
export const poApi = {
  getAll:  () => api.get('/purchase-orders').then(r => Array.isArray(r.data) ? r.data : []),
  create:  (data) => api.post('/purchase-orders', data).then(r => r.data),
  update:  (no, data) => api.put(`/purchase-orders/${no}`, data).then(r => r.data),
  fromPR:  (prNo) => api.post(`/purchase-orders/from-pr/${prNo}`).then(r => r.data),
  grnPrefill: (poNo) => api.get(`/purchase-orders/${poNo}/grn-prefill`).then(r => r.data),
  downloadPdf: (no) => api.get(`/purchase-orders/${no}/pdf`, { responseType: 'blob' }),
}

// ── GRN ───────────────────────────────────────────────────────────────────────
export const grnApi = {
  getAll:  () => api.get('/grns').then(r => Array.isArray(r.data) ? r.data : []),
  create:  (data) => api.post('/grns', data).then(r => r.data),
  update:  (no, data) => api.put(`/grns/${no}`, data).then(r => r.data),
}

// ── ISSUANCE ──────────────────────────────────────────────────────────────────
export const issuanceApi = {
  getAll:  () => api.get('/issuances').then(r => Array.isArray(r.data) ? r.data : []),
  create:  (data) => api.post('/issuances', data).then(r => r.data),
}

// ── RETURNS ───────────────────────────────────────────────────────────────────
export const returnsApi = {
  getAll:  () => api.get('/returns').then(r => Array.isArray(r.data) ? r.data : []),
  create:  (data) => api.post('/returns', data).then(r => r.data),
}

// ── BUDGET ────────────────────────────────────────────────────────────────────
export const budgetCalcApi = {
  getApproved:        ()          => api.get('/budget/approved').then(r => r.data),
  calculate:          ()          => api.post('/budget/calculate').then(r => r.data),
  getCalculated:      ()          => api.get('/budget/calculated').then(r => r.data),
  getVsActual:        (month, year) => api.get('/budget/vs-actual', { params: { month: month || 1, year: year || new Date().getFullYear() } }).then(r => r.data),
  getForecast:        (inflation) => api.get('/budget/forecast', { params: { inflation: inflation ?? 6 } }).then(r => r.data),
  getMonthlyForecast: (inflation) => api.get('/budget/monthly-forecast', { params: { inflation: inflation ?? 6 } }).then(r => r.data),
  getCategorySummary: ()          => api.get('/budget/category-summary').then(r => r.data),
  getLocationSummary: ()          => api.get('/budget/location-summary').then(r => r.data),
}

// ── CODE GENERATOR ────────────────────────────────────────────────────────────
export const codeApi = {
  next: (entity, prefix) => api.get(`/next-code/${entity}`, { params: prefix ? { prefix } : {} }).then(r => r.data.code),
}

// ── CONSUMPTION NORMS ─────────────────────────────────────────────────────────
export const normsApi = {
  getAll:  () => api.get('/consumption-norms').then(r => Array.isArray(r.data) ? r.data : []),
  update:  (id, data) => api.put(`/consumption-norms/${id}`, data).then(r => r.data),
}

// ── DASHBOARD ─────────────────────────────────────────────────────────────────
export const dashboardApi = {
  kpis:              () => api.get('/dashboard/kpis').then(r => r.data),
  spendByCategory:   () => api.get('/dashboard/spend-by-category').then(r => r.data),
  spendByLocation:   () => api.get('/dashboard/spend-by-location').then(r => r.data),
}

// ── IMPORT ────────────────────────────────────────────────────────────────────
export const importApi = {
  upload:  (entity, file) => {
    const fd = new FormData(); fd.append('file', file)
    return api.post(`/import/${entity}`, fd, { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
  },
  template: (entity) => `${BASE}/api/import/template/${entity}`,
}

// ── DELETE (bulk) ─────────────────────────────────────────────────────────────
export const deleteApi = {
  hkMaster:  (ids) => api.delete('/hk-master/bulk',              { data: { ids } }).then(r => r.data),
  items:     (ids) => api.delete('/items/bulk',                  { data: { ids } }).then(r => r.data),
  vendors:   (ids) => api.delete('/vendors/bulk',                { data: { ids } }).then(r => r.data),
  locations: (ids) => api.delete('/locations/bulk',              { data: { ids } }).then(r => r.data),
  issuances: (ids) => api.delete('/issuances/bulk',              { data: { ids } }).then(r => r.data),
  returns:   (ids) => api.delete('/returns/bulk',                { data: { ids } }).then(r => r.data),
  prs:       (ids) => api.delete('/purchase-requisitions/bulk',  { data: { ids } }).then(r => r.data),
  pos:       (ids) => api.delete('/purchase-orders/bulk',        { data: { ids } }).then(r => r.data),
  grns:      (ids) => api.delete('/grns/bulk',                   { data: { ids } }).then(r => r.data),
  norms:     (ids) => api.delete('/consumption-norms/bulk',      { data: { ids } }).then(r => r.data),
}

// ── ANALYTICS & EVENT LOG ─────────────────────────────────────────────────────
export const analyticsApi = {
  snapshot:     ()       => api.get('/analytics/snapshot').then(r => r.data),
  itemVelocity: ()       => api.get('/analytics/item-velocity').then(r => Array.isArray(r.data) ? r.data : []),
  events:       (params) => api.get('/events', { params }).then(r => Array.isArray(r.data) ? r.data : []),
}

// ── CATEGORIES ───────────────────────────────────────────────────────────────
export const categoryApi = {
  getAll:  (group) => api.get('/categories', { params: group ? { group } : {} }).then(r => Array.isArray(r.data) ? r.data : []),
  create:  (data) => api.post('/categories', data).then(r => r.data),
  update:  (id, data) => api.put(`/categories/${id}`, data).then(r => r.data),
  patch:   (id, data) => api.patch(`/categories/${id}`, data).then(r => r.data),
  delete:  (id) => api.delete(`/categories/${id}`).then(r => r.data),
  seed:    () => api.post('/categories/seed').then(r => r.data),
}

// ── MASTER GROUPS ────────────────────────────────────────────────────────────
export const masterGroupApi = {
  getAll:  () => api.get('/master-groups').then(r => Array.isArray(r.data) ? r.data : []),
  create:  (data) => api.post('/master-groups', data).then(r => r.data),
  update:  (id, data) => api.put(`/master-groups/${id}`, data).then(r => r.data),
  delete:  (id) => api.delete(`/master-groups/${id}`).then(r => r.data),
  seed:    () => api.post('/master-groups/seed').then(r => r.data),
}

export default api

// ── ADMIN ─────────────────────────────────────────────────────────────────────
export const adminApi = {
  dataSummary: ()           => api.get('/admin/data-summary').then(r => r.data),
  resetData:   (keepMasters) => api.post('/admin/reset-data', { confirm: 'RESET', keep_masters: keepMasters }).then(r => r.data),
}