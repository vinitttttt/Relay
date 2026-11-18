import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { authenticatedRequest, request } from './api.js'

const AuthContext = createContext(null)
const TOKEN_KEY = 'relay_access_token'

export function AuthProvider({ children }) {
  const [token, setToken] = useState(null)
  const [user, setUser] = useState(null)
  const [status, setStatus] = useState('checking')

  const clearSession = useCallback(() => {
    window.sessionStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setUser(null)
    setStatus('anonymous')
  }, [])

  useEffect(() => {
    let active = true
    const storedToken = window.sessionStorage.getItem(TOKEN_KEY)
    if (!storedToken) {
      setStatus('anonymous')
      return () => { active = false }
    }

    authenticatedRequest('/api/v1/auth/me', storedToken)
      .then((profile) => {
        if (!active) return
        setToken(storedToken)
        setUser(profile)
        setStatus('authenticated')
      })
      .catch(() => {
        window.sessionStorage.removeItem(TOKEN_KEY)
        if (active) setStatus('anonymous')
      })

    return () => { active = false }
  }, [])

  const establishSession = useCallback(async (accessToken) => {
    window.sessionStorage.setItem(TOKEN_KEY, accessToken)
    try {
      const profile = await authenticatedRequest('/api/v1/auth/me', accessToken)
      setToken(accessToken)
      setUser(profile)
      setStatus('authenticated')
      return profile
    } catch (error) {
      window.sessionStorage.removeItem(TOKEN_KEY)
      setToken(null)
      setUser(null)
      setStatus('anonymous')
      throw error
    }
  }, [])

  const signIn = useCallback(async (identifier, password) => {
    const result = await request('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ identifier, password }),
    })
    await establishSession(result.access_token)
  }, [establishSession])

  const register = useCallback(async ({ username, email, password }) => {
    await request('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, email, password }),
    })
    await signIn(username, password)
  }, [signIn])

  const signOut = useCallback(() => clearSession(), [clearSession])

  const apiFetch = useCallback(async (path, options = {}) => {
    if (!token) throw new Error('You need to sign in to continue.')
    try {
      return await authenticatedRequest(path, token, options)
    } catch (error) {
      if (error.status === 401) clearSession()
      throw error
    }
  }, [clearSession, token])

  const value = useMemo(() => ({
    user,
    token,
    status,
    signIn,
    register,
    signOut,
    apiFetch,
  }), [user, token, status, signIn, register, signOut, apiFetch])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within an AuthProvider')
  return context
}
