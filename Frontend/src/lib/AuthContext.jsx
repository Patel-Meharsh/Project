import { createContext, useContext, useState, useEffect } from 'react'
import { authApi } from './auth'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user,    setUser]    = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem('gg_token')
    if (!token) { setLoading(false); return }
    authApi.me()
      .then(u => setUser(u))
      .catch(() => localStorage.removeItem('gg_token'))
      .finally(() => setLoading(false))
  }, [])

  const login = async (email, password) => {
    const res = await authApi.login(email, password)
    localStorage.setItem('gg_token', res.token)
    setUser(res.user)
    return res.user
  }

  const signup = async (data) => {
    const res = await authApi.signup(data)
    localStorage.setItem('gg_token', res.token)
    setUser(res.user)
    return res.user
  }

  const logout = () => {
    localStorage.removeItem('gg_token')
    setUser(null)
  }

  const refreshUser = async () => {
    const u = await authApi.me()
    setUser(u)
    return u
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, signup, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
