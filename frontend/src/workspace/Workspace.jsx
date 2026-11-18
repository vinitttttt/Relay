import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../auth/AuthContext.jsx'
import { navigate } from '../auth/router.jsx'
import './Workspace.css'

function conversationTitle(conversation, user) {
  if (conversation.conversation_type === 'direct') {
    return conversation.members?.find((member) => member.id !== user?.id)?.username || 'Direct conversation'
  }
  return conversation.name || 'Group conversation'
}

function formatTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  if (date.toDateString() === now.toDateString()) return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(date)
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(date)
}

export function Workspace() {
  const { user, signOut, apiFetch } = useAuth()
  const [conversations, setConversations] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [loadingConversations, setLoadingConversations] = useState(true)
  const [conversationError, setConversationError] = useState('')
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchError, setSearchError] = useState('')
  const [openingUserId, setOpeningUserId] = useState(null)
  const searchSequence = useRef(0)
  const conversationSequence = useRef(0)
  const mountedRef = useRef(false)

  const loadConversations = useCallback(async () => {
    const sequence = ++conversationSequence.current
    setLoadingConversations(true)
    setConversationError('')
    try {
      const rows = await apiFetch('/api/v1/conversations')
      if (sequence === conversationSequence.current) setConversations(Array.isArray(rows) ? rows : [])
    } catch (error) {
      if (sequence === conversationSequence.current) setConversationError(error.message)
    } finally {
      if (sequence === conversationSequence.current) setLoadingConversations(false)
    }
  }, [apiFetch])

  useEffect(() => {
    mountedRef.current = true
    loadConversations()
    return () => {
      mountedRef.current = false
      conversationSequence.current += 1
      searchSequence.current += 1
    }
  }, [loadConversations])

  useEffect(() => {
    const cleanQuery = query.trim()
    const sequence = ++searchSequence.current
    setSearchError('')
    if (cleanQuery.length < 2) {
      setSearchResults([])
      setSearchLoading(false)
      return undefined
    }
    setSearchLoading(true)
    const timer = window.setTimeout(async () => {
      try {
        const results = await apiFetch(`/api/v1/users/search?q=${encodeURIComponent(cleanQuery)}`)
        if (sequence === searchSequence.current) {
          setSearchResults((Array.isArray(results) ? results : []).filter((profile) => profile.id !== user?.id))
        }
      } catch (error) {
        if (sequence === searchSequence.current) setSearchError(error.message)
      } finally {
        if (sequence === searchSequence.current) setSearchLoading(false)
      }
    }, 300)
    return () => {
      window.clearTimeout(timer)
      if (sequence === searchSequence.current) searchSequence.current += 1
    }
  }, [apiFetch, query, user?.id])

  const selected = useMemo(() => conversations.find((item) => item.id === selectedId) || null, [conversations, selectedId])

  async function openDirectConversation(profile) {
    setOpeningUserId(profile.id)
    setSearchError('')
    try {
      const opened = await apiFetch('/api/v1/conversations/direct', {
        method: 'POST',
        body: JSON.stringify({ target_user_id: profile.id }),
      })
      if (!mountedRef.current) return
      setConversations((current) => current.some((item) => item.id === opened.id) ? current : [opened, ...current])
      setSelectedId(opened.id)
      setQuery('')
      setSearchResults([])
      await loadConversations()
      if (mountedRef.current) setSelectedId(opened.id)
    } catch (error) {
      if (mountedRef.current) setSearchError(error.message)
    } finally {
      if (mountedRef.current) setOpeningUserId(null)
    }
  }

  return (
    <main className={`workspace-shell${selected ? ' has-selection' : ''}`}>
      <Sidebar
        user={user}
        conversations={conversations}
        selectedId={selectedId}
        onSelect={setSelectedId}
        loading={loadingConversations}
        error={conversationError}
        onRetry={loadConversations}
        query={query}
        onQueryChange={setQuery}
        searchResults={searchResults}
        searchLoading={searchLoading}
        searchError={searchError}
        onOpenProfile={openDirectConversation}
        openingUserId={openingUserId}
        onSignOut={() => { signOut(); navigate('/login', true) }}
      />
      <section className="workspace-main" aria-label="Conversation area">
        {selected
          ? <ConversationHeader conversation={selected} title={conversationTitle(selected, user)} onBack={() => setSelectedId(null)} />
          : <ChatPlaceholder username={user?.username} />}
      </section>
    </main>
  )
}

function Sidebar(props) {
  return (
    <aside className="workspace-sidebar">
      <div className="sidebar-brand-row">
        <a className="workspace-brand" href="/app" aria-label="Relay workspace">
          <span className="workspace-mark" aria-hidden="true"><RelayIcon /></span><span>relay</span>
        </a>
        <span className="sidebar-status"><i />Workspace</span>
      </div>
      <UserSearch {...props} />
      <ConversationList {...props} />
      <ProfileSection user={props.user} onSignOut={props.onSignOut} />
    </aside>
  )
}

function UserSearch({ query, onQueryChange, searchResults, searchLoading, searchError, onOpenProfile, openingUserId }) {
  const showResults = query.trim().length >= 2
  return (
    <div className="search-area">
      <label className="search-label" htmlFor="workspace-search">Find people</label>
      <div className="search-field">
        <SearchIcon />
        <input id="workspace-search" type="search" maxLength={50} value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="Search by username" autoComplete="off" />
        {query && <button className="clear-search" type="button" aria-label="Clear search" onClick={() => onQueryChange('')}>×</button>}
      </div>
      {showResults && <div className="search-results" aria-live="polite">
        {searchLoading && <p className="search-feedback">Searching people…</p>}
        {!searchLoading && searchError && <p className="search-feedback search-error">{searchError}</p>}
        {!searchLoading && !searchError && searchResults.length === 0 && <p className="search-feedback">No people found for “{query.trim()}”.</p>}
        {!searchLoading && !searchError && searchResults.map((profile) => (
          <button className="search-result" key={profile.id} type="button" disabled={openingUserId !== null} onClick={() => onOpenProfile(profile)}>
            <Avatar name={profile.username} /><span className="search-result-name">{profile.username}</span>
            <span className="result-action">{openingUserId === profile.id ? 'Opening…' : 'Message'}</span>
          </button>
        ))}
      </div>}
      {!showResults && <p className="search-hint">Enter at least 2 characters</p>}
    </div>
  )
}

function ConversationList({ conversations, selectedId, onSelect, loading, error, onRetry, user }) {
  return (
    <section className="conversation-section" aria-label="Conversations">
      <div className="section-heading"><h2>Messages</h2><span>{conversations.length || ''}</span></div>
      <div className="conversation-list">
        {loading && <div className="list-state"><span className="mini-spinner" />Loading conversations</div>}
        {!loading && error && <div className="list-state list-error"><p>{error}</p><button type="button" onClick={onRetry}>Try again</button></div>}
        {!loading && !error && conversations.length === 0 && <div className="list-empty"><span className="empty-chat-icon"><MessageIcon /></span><p>No conversations yet</p><span>Search for someone to start a conversation.</span></div>}
        {!loading && !error && conversations.map((conversation) => <ConversationItem key={conversation.id} conversation={conversation} title={conversationTitle(conversation, user)} active={conversation.id === selectedId} onClick={() => onSelect(conversation.id)} />)}
      </div>
    </section>
  )
}

function ConversationItem({ conversation, title, active, onClick }) {
  const latest = conversation.latest_message
  return (
    <button type="button" className={`conversation-item${active ? ' is-active' : ''}`} onClick={onClick} aria-current={active ? 'page' : undefined}>
      <Avatar name={title} />
      <span className="conversation-item-copy">
        <span className="conversation-item-top"><strong>{title}</strong><time>{formatTime(latest?.created_at || conversation.created_at)}</time></span>
        <span className="conversation-preview">{latest ? `${latest.sender?.username ? `${latest.sender.username}: ` : ''}${latest.content}` : 'Start a conversation'}</span>
      </span>
    </button>
  )
}

function ProfileSection({ user, onSignOut }) {
  return (
    <footer className="profile-section">
      <Avatar name={user?.username || 'You'} />
      <div className="profile-copy"><strong>{user?.username || 'Your account'}</strong><span>Personal workspace</span></div>
      <button className="signout-button" type="button" onClick={onSignOut} aria-label="Log out" title="Log out"><LogoutIcon /></button>
    </footer>
  )
}

function ConversationHeader({ conversation, title, onBack }) {
  return (
    <>
      <header className="conversation-header">
        <button className="mobile-back-button" type="button" onClick={onBack} aria-label="Back to conversations">‹</button>
        <Avatar name={title} large />
        <div><h1>{title}</h1><p>{conversation.conversation_type === 'direct' ? 'Direct conversation' : 'Group conversation'}</p></div>
      </header>
      <div className="conversation-placeholder">
        <span className="placeholder-illustration"><MessageIcon /></span>
        <p className="form-eyebrow">YOUR SPACE WITH {title.toUpperCase()}</p>
        <h2>Good conversations start here.</h2>
        <p>Messages will appear here. Your conversation is ready when you are.</p>
      </div>
    </>
  )
}

function ChatPlaceholder({ username }) {
  return <div className="welcome-state">
    <span className="welcome-art"><RelayIcon /></span>
    <p className="form-eyebrow">YOUR WORKSPACE</p>
    <h1>Welcome to Relay, {username}.</h1>
    <p>Choose a conversation to pick up where you left off, or search for someone to start a new one.</p>
    <div className="welcome-tip"><SearchIcon /><span>Find a teammate by their username in the sidebar.</span></div>
  </div>
}

function Avatar({ name, large = false }) {
  const initial = name?.trim()?.[0]?.toUpperCase() || '?'
  return <span className={`avatar${large ? ' avatar-large' : ''}`} aria-hidden="true">{initial}</span>
}

function RelayIcon() { return <svg viewBox="0 0 32 32" fill="none"><path d="M7 23V9h10.3a6.7 6.7 0 0 1 0 13.4H7" /><path d="m18 18 7 7" /><path d="M12 14h5.2a1.7 1.7 0 0 1 0 3.4H12" /></svg> }
function SearchIcon() { return <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="8.8" cy="8.8" r="5.8" /><path d="m13.2 13.2 4 4" /></svg> }
function MessageIcon() { return <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H5l1.8-3.1A7.5 7.5 0 1 1 20 11.5Z" /><path d="M8.5 11.5h7M8.5 14.5h4" /></svg> }
function LogoutIcon() { return <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M8 3H4.5A1.5 1.5 0 0 0 3 4.5v11A1.5 1.5 0 0 0 4.5 17H8M12 6l4 4-4 4M16 10H7" /></svg> }
