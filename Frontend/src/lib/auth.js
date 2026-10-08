import api from './api'  // Import the configured axios instance


export const authApi = {
  login:         (email, password)  => api.post('/auth/login',   { email, password }).then(r => r.data),
  signup:        (data)             => api.post('/auth/signup',   data).then(r => r.data),
  me:            ()                 => api.get('/auth/me').then(r => r.data),
  updateProfile: (data)             => api.put('/auth/profile',   data).then(r => r.data),
  listUsers:     ()                 => api.get('/auth/users').then(r => r.data),
  updateUser:    (id, data)         => api.put(`/auth/users/${id}`, data).then(r => r.data),
  resetPassword: (id, password)     => api.post(`/auth/users/${id}/reset-password`, { new_password: password }).then(r => r.data),
  createUser:    (data)             => api.post('/auth/users', data).then(r => r.data),
}

export const ROLES = {
  super_admin: { label: 'Super Admin', color: '#dc2626', bg: '#fef2f2', level: 4 },
  admin:       { label: 'Admin',       color: '#f59e0b', bg: '#fffbeb', level: 3 },
  analyst:     { label: 'Analyst',     color: '#3b82f6', bg: '#eff6ff', level: 2 },
  observer:    { label: 'Observer',    color: '#64748b', bg: '#f8fafc', level: 1 },
}

export function canDo(userRole, minRole) {
  return (ROLES[userRole]?.level || 0) >= (ROLES[minRole]?.level || 0)
}

// Password validation
export function validatePassword(pw) {
  const rules = [
    { id: 'len',     label: 'At least 8 characters',          ok: pw.length >= 8 },
    { id: 'upper',   label: 'One uppercase letter (A-Z)',      ok: /[A-Z]/.test(pw) },
    { id: 'special', label: 'One special character (. , @)',   ok: /[!@#$%^&*(),.?":{}|<>]/.test(pw) },
  ]
  return { rules, valid: rules.every(r => r.ok) }
}
