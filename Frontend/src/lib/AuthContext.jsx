import { createContext, useContext, useState, useEffect } from 'react'
import { authApi } from './auth'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user,    setUser]    = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Remove legacy client-side auth tokens left by older builds.
    localStorage.removeItem('gg_token')
    authApi.me()
      .then(u => setUser(u))
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  const login = async (email, password) => {
    const res = await authApi.login(email, password)
    setUser(res.user)
    return res.user
  }

  const signup = async (data) => {
    const res = await authApi.signup(data)
    setUser(res.user)
    return res.user
  }

  const logout = () => {
    authApi.logout().catch(() => {}).finally(() => setUser(null))
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