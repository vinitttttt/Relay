import { useEffect, useState } from 'react'
import './App.css'
import { AuthProvider, useAuth } from './auth/AuthContext.jsx'
import { Link, navigate, usePathname } from './auth/router.jsx'
import { LoginScreen, RegisterScreen } from './auth/AuthScreens.jsx'
import { Workspace } from './workspace/Workspace.jsx'

function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  )
}

function AppRoutes() {
  const { status } = useAuth()
  const pathname = usePathname()

  if (status === 'checking') return <LoadingScreen label="Restoring your Relay session…" />

  const isAuthRoute = pathname === '/login' || pathname === '/register'
  if (status === 'authenticated' && (isAuthRoute || pathname === '/')) {
    return <RedirectTo path="/app" />
  }
  if (status !== 'authenticated' && pathname === '/app') {
    return <RedirectTo path="/login" />
  }
  if (pathname === '/') return <RedirectTo path="/login" />
  if (pathname !== '/login' && pathname !== '/register' && pathname !== '/app') {
    return <RedirectTo path={status === 'authenticated' ? '/app' : '/login'} />
  }

  if (pathname === '/login') return <LoginScreen />
  if (pathname === '/register') return <RegisterScreen />
  return <Workspace />
}

function RedirectTo({ path }) {
  useEffect(() => navigate(path, true), [path])
  return <LoadingScreen label="Taking you there…" />
}

function LoadingScreen({ label }) {
  return (
    <main className="app-loading" role="status">
      <span className="loading-mark" aria-hidden="true">r</span>
      <span>{label}</span>
    </main>
  )
}

function ProtectedPlaceholder() {
  const { user, signOut, apiFetch } = useAuth()
  const [error, setError] = useState('')

  async function checkSession() {
    setError('')
    try {
      await apiFetch('/api/v1/auth/me')
      setError('Your account is connected and ready.')
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  return (
    <main className="protected-shell">
      <header className="app-header">
        <Link className="brand-lockup app-brand" to="/app" aria-label="Relay home">
          <span className="relay-mark" aria-hidden="true">r</span><span>relay</span>
        </Link>
        <div className="account-controls">
          <span className="account-name">{user?.username}</span>
          <button className="text-button" type="button" onClick={signOut}>Sign out</button>
        </div>
      </header>
      <section className="placeholder-card">
        <span className="placeholder-icon" aria-hidden="true">✦</span>
        <p className="form-eyebrow">YOU’RE SIGNED IN</p>
        <h1>Welcome to Relay, {user?.username}.</h1>
        <p>Your account is ready. The messaging workspace will take shape here next.</p>
        <button className="secondary-button" type="button" onClick={checkSession}>Check connection</button>
        {error && <p className="connection-status" role="status">{error}</p>}
      </section>
    </main>
  )
}

export default App
