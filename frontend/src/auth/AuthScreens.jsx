import { useState } from 'react'
import { Link, navigate } from './router.jsx'
import { useAuth } from './AuthContext.jsx'

function RelayMark() {
  return (
    <span className="relay-mark" aria-hidden="true">
      <svg viewBox="0 0 32 32" fill="none">
        <path d="M7 23V9h10.3a6.7 6.7 0 0 1 0 13.4H7" />
        <path d="m18 18 7 7" />
        <path d="M12 14h5.2a1.7 1.7 0 0 1 0 3.4H12" />
      </svg>
    </span>
  )
}

function BrandPanel() {
  return (
    <aside className="brand-panel">
      <Link className="brand-lockup" to="/login" aria-label="Relay home">
        <RelayMark />
        <span>relay</span>
      </Link>
      <div className="brand-message">
        <p className="brand-kicker">A little more connected.</p>
        <h1>Good work moves<br />when people do.</h1>
        <p className="brand-copy">
          A thoughtful space for teams to share ideas, make plans, and keep work moving.
        </p>
      </div>
      <div className="brand-note">
        <span className="brand-note-icon" aria-hidden="true">↗</span>
        <span>Pick up right where your team left off.</span>
      </div>
      <span className="brand-copyright">Relay · Made for working together</span>
    </aside>
  )
}

function PasswordField({ id, label, value, onChange, autoComplete, error }) {
  const [visible, setVisible] = useState(false)
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className={`password-control${error ? ' has-error' : ''}`}>
        <input
          id={id}
          name={id}
          type={visible ? 'text' : 'password'}
          value={value}
          onChange={onChange}
          autoComplete={autoComplete}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${id}-error` : undefined}
          required
        />
        <button
          className="visibility-button"
          type="button"
          onClick={() => setVisible((current) => !current)}
          aria-label={visible ? 'Hide password' : 'Show password'}
          aria-pressed={visible}
        >
          {visible ? 'Hide' : 'Show'}
        </button>
      </div>
      {error && <p className="field-error" id={`${id}-error`}>{error}</p>}
    </div>
  )
}

function FormAlert({ message }) {
  return message ? <div className="form-alert" role="alert">{message}</div> : null
}

export function LoginScreen() {
  const { signIn } = useAuth()
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState({})
  const [apiError, setApiError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    const nextErrors = {}
    if (!identifier.trim()) nextErrors.identifier = 'Enter your username or email.'
    if (!password) nextErrors.password = 'Enter your password.'
    setErrors(nextErrors)
    setApiError('')
    if (Object.keys(nextErrors).length) return

    setSubmitting(true)
    try {
      await signIn(identifier.trim(), password)
      navigate('/app', true)
    } catch (error) {
      setApiError(error.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthLayout>
      <div className="form-heading">
        <p className="mobile-brand"><RelayMark /><span>relay</span></p>
        <p className="form-eyebrow">WELCOME BACK</p>
        <h2>Sign in to Relay</h2>
        <p className="form-subtitle">Your team and conversations are right where you left them.</p>
      </div>
      <FormAlert message={apiError} />
      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        <div className="field">
          <label htmlFor="identifier">Username or email</label>
          <input
            id="identifier"
            name="identifier"
            type="text"
            value={identifier}
            onChange={(event) => setIdentifier(event.target.value)}
            autoComplete="username"
            autoCapitalize="none"
            spellCheck="false"
            aria-invalid={Boolean(errors.identifier)}
            aria-describedby={errors.identifier ? 'identifier-error' : undefined}
            required
          />
          {errors.identifier && <p className="field-error" id="identifier-error">{errors.identifier}</p>}
        </div>
        <PasswordField
          id="password"
          label="Password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          error={errors.password}
        />
        <button className="primary-button" type="submit" disabled={submitting}>
          {submitting ? <><span className="button-spinner" aria-hidden="true" />Signing in…</> : 'Sign in'}
        </button>
      </form>
      <p className="form-switch">New to Relay? <Link to="/register">Create an account</Link></p>
      <p className="form-security">Your account details stay private and secure.</p>
    </AuthLayout>
  )
}

export function RegisterScreen() {
  const { register } = useAuth()
  const [values, setValues] = useState({ username: '', email: '', password: '', confirmPassword: '' })
  const [errors, setErrors] = useState({})
  const [apiError, setApiError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  function update(field) {
    return (event) => setValues((current) => ({ ...current, [field]: event.target.value }))
  }

  async function handleSubmit(event) {
    event.preventDefault()
    const username = values.username.trim()
    const email = values.email.trim()
    const nextErrors = {}
    if (username.length < 3 || username.length > 50 || !/^[A-Za-z0-9_.-]+$/.test(username)) {
      nextErrors.username = 'Use 3–50 letters, numbers, dots, dashes, or underscores.'
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 254) {
      nextErrors.email = 'Enter a valid email address.'
    }
    if (values.password.length < 8 || values.password.length > 128) {
      nextErrors.password = 'Use a password between 8 and 128 characters.'
    }
    if (values.confirmPassword !== values.password) {
      nextErrors.confirmPassword = 'The passwords do not match.'
    }
    setErrors(nextErrors)
    setApiError('')
    if (Object.keys(nextErrors).length) return

    setSubmitting(true)
    try {
      await register({ username, email, password: values.password })
      navigate('/app', true)
    } catch (error) {
      setApiError(error.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthLayout>
      <div className="form-heading">
        <p className="mobile-brand"><RelayMark /><span>relay</span></p>
        <p className="form-eyebrow">GET STARTED</p>
        <h2>Create your account</h2>
        <p className="form-subtitle">Bring your conversations and collaboration together.</p>
      </div>
      <FormAlert message={apiError} />
      <form className="auth-form register-form" onSubmit={handleSubmit} noValidate>
        <div className="field">
          <label htmlFor="username">Username</label>
          <input
            id="username"
            name="username"
            type="text"
            value={values.username}
            onChange={update('username')}
            autoComplete="username"
            autoCapitalize="none"
            spellCheck="false"
            maxLength={50}
            aria-invalid={Boolean(errors.username)}
            aria-describedby={errors.username ? 'username-error' : undefined}
            required
          />
          {errors.username && <p className="field-error" id="username-error">{errors.username}</p>}
        </div>
        <div className="field">
          <label htmlFor="email">Email address</label>
          <input
            id="email"
            name="email"
            type="email"
            value={values.email}
            onChange={update('email')}
            autoComplete="email"
            maxLength={254}
            aria-invalid={Boolean(errors.email)}
            aria-describedby={errors.email ? 'email-error' : undefined}
            required
          />
          {errors.email && <p className="field-error" id="email-error">{errors.email}</p>}
        </div>
        <PasswordField
          id="new-password"
          label="Password"
          value={values.password}
          onChange={update('password')}
          autoComplete="new-password"
          error={errors.password}
        />
        <PasswordField
          id="confirm-password"
          label="Confirm password"
          value={values.confirmPassword}
          onChange={update('confirmPassword')}
          autoComplete="new-password"
          error={errors.confirmPassword}
        />
        <button className="primary-button" type="submit" disabled={submitting}>
          {submitting ? <><span className="button-spinner" aria-hidden="true" />Creating account…</> : 'Create account'}
        </button>
      </form>
      <p className="form-switch">Already have an account? <Link to="/login">Sign in</Link></p>
      <p className="form-security">By continuing, you agree to use Relay responsibly.</p>
    </AuthLayout>
  )
}

function AuthLayout({ children }) {
  return (
    <main className="auth-shell">
      <BrandPanel />
      <section className="form-panel" aria-label="Account access">
        <div className="form-card">{children}</div>
      </section>
    </main>
  )
}
