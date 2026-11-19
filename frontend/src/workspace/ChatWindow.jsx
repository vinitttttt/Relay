import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createTicketedWebSocket } from '../auth/api.js'

const PAGE_SIZE = 50

function formatMessageTime(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(date)
}

function mergeMessages(current, incoming) {
  const byId = new Map(current.map((message) => [message.id, message]))
  incoming.forEach((message) => byId.set(message.id, { ...byId.get(message.id), ...message }))
  return [...byId.values()].sort((a, b) => {
    const timeDifference = new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    if (timeDifference) return timeDifference
    return String(a.id).localeCompare(String(b.id), undefined, { numeric: true })
  })
}

function findPending(pending, content) {
  for (const [id, item] of pending) if (item.content === content) return id
  return null
}

function reconcilePending(messages, pending, userId) {
  const remaining = [...pending.entries()]
  const confirmedIds = new Set()
  messages.forEach((message) => {
    if (message.sender?.id !== userId) return
    const matchIndex = remaining.findIndex(([, item]) => item.content === message.content)
    if (matchIndex !== -1) {
      confirmedIds.add(remaining[matchIndex][0])
      remaining.splice(matchIndex, 1)
    }
  })
  confirmedIds.forEach((id) => pending.delete(id))
  return messages.filter((message) => !confirmedIds.has(message.id))
}

export function ChatWindow({ conversation, title, user, apiFetch, onBack, onMessage }) {
  const [messages, setMessages] = useState([])
  const [nextCursor, setNextCursor] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState('')
  const [connectionStatus, setConnectionStatus] = useState('connecting')
  const [reloadKey, setReloadKey] = useState(0)
  const scrollRef = useRef(null)
  const nearBottomRef = useRef(true)
  const bottomRequestedRef = useRef(false)
  const preserveScrollRef = useRef(null)
  const olderRequestRef = useRef(false)
  const sendingRef = useRef(false)
  const mountedRef = useRef(false)
  const socketRef = useRef(null)
  const pendingRef = useRef(new Map())
  const updateConnectionStatus = useCallback((status) => {
    setConnectionStatus(status)
  }, [])

  useEffect(() => {
    mountedRef.current = true
    let active = true
    setLoading(true)
    setHistoryError('')
    apiFetch(`/api/v1/conversations/${conversation.id}/messages?limit=${PAGE_SIZE}`)
      .then((page) => {
        if (!active) return
        setMessages((current) => mergeMessages(current, Array.isArray(page?.items) ? page.items : []))
        setNextCursor(page?.next_cursor ?? null)
        bottomRequestedRef.current = true
      })
      .catch((error) => { if (active) setHistoryError(error.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false; mountedRef.current = false }
  }, [apiFetch, conversation.id, reloadKey])

  useEffect(() => {
    let stopped = false
    let reconnectTimer = null
    let stableTimer = null
    let socket = null
    let attempts = 0
    let reconnecting = false
    const recoverLatest = async () => {
      try {
        const page = await apiFetch(`/api/v1/conversations/${conversation.id}/messages?limit=${PAGE_SIZE}`)
        if (!stopped && mountedRef.current) {
          const recovered = Array.isArray(page?.items) ? page.items : []
          setMessages((current) => reconcilePending(mergeMessages(current, recovered), pendingRef.current, user.id))
          if (recovered.length) onMessage?.(conversation.id, recovered[recovered.length - 1])
        }
      } catch { /* The next reconnect or normal history retry can recover it. */ }
    }
    const connect = async () => {
      if (stopped) return
      updateConnectionStatus(attempts ? 'reconnecting' : 'connecting')
      try {
        socket = await createTicketedWebSocket(apiFetch, conversation.id)
      } catch (error) {
        if (stopped) return
        if (error.status === 401 || error.status === 403) {
          updateConnectionStatus('disconnected')
          return
        }
        scheduleReconnect()
        return
      }
      if (stopped) {
        socket.close()
        return
      }
      socketRef.current = socket
      socket.onopen = () => {
        if (stopped || socketRef.current !== socket) return
        updateConnectionStatus('connected')
        if (stableTimer) window.clearTimeout(stableTimer)
        stableTimer = window.setTimeout(() => { attempts = 0 }, 30000)
        if (reconnecting) recoverLatest()
        reconnecting = false
      }
      socket.onmessage = (event) => {
        if (stopped || socketRef.current !== socket) return
        let payload
        try { payload = JSON.parse(event.data) } catch { return }
        if (payload?.type === 'connection.ready') {
          if (payload.data?.conversation_id === conversation.id) updateConnectionStatus('connected')
          return
        }
        if (payload?.type === 'message.created') {
          const data = payload.data
          if (!data || data.conversation_id !== conversation.id || !Number.isFinite(Number(data.id)) || !Number.isFinite(Number(data.sender_id)) || typeof data.sender_username !== 'string' || typeof data.content !== 'string') return
          const message = {
            id: data.id,
            conversation_id: data.conversation_id,
            content: data.content,
            created_at: data.created_at,
            sender: { id: data.sender_id, username: data.sender_username },
          }
          onMessage?.(conversation.id, message)
          if (data.sender_id === user.id) {
            const pendingId = findPending(pendingRef.current, data.content)
            if (pendingId) pendingRef.current.delete(pendingId)
            setMessages((current) => mergeMessages(current.filter((item) => item.id !== pendingId), [message]))
          } else {
            setMessages((current) => mergeMessages(current, [message]))
          }
          return
        }
        if (payload?.type === 'error') {
          const pendingId = [...pendingRef.current.keys()][0]
          if (pendingId) {
            pendingRef.current.delete(pendingId)
            setMessages((current) => current.map((item) => item.id === pendingId ? { ...item, delivery: 'failed', deliveryMessage: payload.data?.detail || 'The server rejected this message.' } : item))
            setSendError(payload.data?.detail || 'The server rejected this message.')
          }
        }
      }
      socket.onclose = (event) => {
        if (socketRef.current === socket) socketRef.current = null
        if (stopped) return
        if (event.code === 4403 || event.code === 4404) {
          updateConnectionStatus('disconnected')
          return
        }
        pendingRef.current.forEach((pending, id) => {
          if (pending.sent) setMessages((current) => current.map((item) => item.id === id ? { ...item, delivery: 'unknown' } : item))
        })
        scheduleReconnect()
      }
      socket.onerror = () => { /* onclose owns reconnect scheduling */ }
    }
    function scheduleReconnect() {
      if (stopped || reconnectTimer) return
      updateConnectionStatus(attempts ? 'reconnecting' : 'disconnected')
      const delay = Math.min(1000 * (2 ** attempts), 30000)
      attempts += 1
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null
        reconnecting = true
        connect()
      }, delay)
    }
    connect()
    return () => {
      stopped = true
      if (reconnectTimer) window.clearTimeout(reconnectTimer)
      if (stableTimer) window.clearTimeout(stableTimer)
      if (socketRef.current === socket) socketRef.current = null
      if (socket) {
        socket.onopen = null
        socket.onmessage = null
        socket.onclose = null
        socket.onerror = null
        socket.close()
      }
    }
  }, [apiFetch, conversation.id, onMessage, user.id, updateConnectionStatus])

  useLayoutEffect(() => {
    const container = scrollRef.current
    if (!container) return
    if (preserveScrollRef.current !== null) {
      const previous = preserveScrollRef.current
      container.scrollTop = previous.top + (container.scrollHeight - previous.height)
      preserveScrollRef.current = null
    } else if (bottomRequestedRef.current || nearBottomRef.current) {
      container.scrollTop = container.scrollHeight
    }
    bottomRequestedRef.current = false
  }, [messages, loading])

  const loadOlder = useCallback(async () => {
    if (olderRequestRef.current || nextCursor === null || loading) return
    olderRequestRef.current = true
    setLoadingOlder(true)
    setHistoryError('')
    const container = scrollRef.current
    if (container) preserveScrollRef.current = { top: container.scrollTop, height: container.scrollHeight }
    try {
      const page = await apiFetch(`/api/v1/conversations/${conversation.id}/messages?limit=${PAGE_SIZE}&before_id=${nextCursor}`)
      if (!mountedRef.current) return
      setMessages((current) => mergeMessages(current, Array.isArray(page?.items) ? page.items : []))
      setNextCursor(page?.next_cursor ?? null)
    } catch (error) {
      if (mountedRef.current) {
        preserveScrollRef.current = null
        setHistoryError(error.message)
      }
    } finally {
      olderRequestRef.current = false
      if (mountedRef.current) setLoadingOlder(false)
    }
  }, [apiFetch, conversation.id, loading, nextCursor])

  function onScroll() {
    const container = scrollRef.current
    if (!container) return
    nearBottomRef.current = container.scrollHeight - container.scrollTop - container.clientHeight < 96
  }

  async function sendMessage(content = draft, retryId = null) {
    const messageContent = content
    if (!messageContent.trim() || messageContent.length > 5000 || sendingRef.current) return
    sendingRef.current = true
    setSending(true)
    setSendError('')
    bottomRequestedRef.current = true
    let localId = retryId
    if (!localId) {
      localId = `pending-${Date.now()}-${Math.random().toString(36).slice(2)}`
      setMessages((current) => mergeMessages(current, [{
        id: localId,
        conversation_id: conversation.id,
        content: messageContent,
        created_at: new Date().toISOString(),
        sender: { id: user.id, username: user.username },
        delivery: 'sending',
      }]))
    } else {
      setMessages((current) => current.map((message) => message.id === localId ? { ...message, delivery: 'sending' } : message))
    }
    try {
      const socket = socketRef.current
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        // REST fallback is safe only before anything was handed to a WebSocket.
        const saved = await apiFetch(`/api/v1/conversations/${conversation.id}/messages`, { method: 'POST', body: JSON.stringify({ content: messageContent }) })
        if (!mountedRef.current) return
        setMessages((current) => mergeMessages(current.filter((message) => message.id !== localId), [saved]))
        onMessage?.(conversation.id, saved)
      } else {
        pendingRef.current.set(localId, { content: messageContent, sent: true })
        socket.send(JSON.stringify({ type: 'message.send', content: messageContent }))
        setDraft((current) => current === messageContent ? '' : current)
      }
      setDraft((current) => current === messageContent ? '' : current)
    } catch (error) {
      if (!mountedRef.current) return
      const ambiguous = pendingRef.current.has(localId)
      setMessages((current) => current.map((message) => message.id === localId ? { ...message, delivery: ambiguous ? 'unknown' : 'failed' } : message))
      setSendError(error.message)
    } finally {
      sendingRef.current = false
      if (mountedRef.current) setSending(false)
    }
  }

  function handleComposerKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      sendMessage()
    }
  }

  const canSend = Boolean(draft.trim()) && draft.length <= 5000 && !sending

  return (
    <div className="chat-window">
      <header className="conversation-header">
        <button className="mobile-back-button" type="button" onClick={onBack} aria-label="Back to conversations">‹</button>
        <Avatar name={title} />
        <div className="chat-header-copy"><h1>{title}</h1><p>{conversation.conversation_type === 'direct' ? 'Direct conversation' : 'Group conversation'}</p></div>
        <span className={`connection-indicator is-${connectionStatus}`} aria-live="polite"><i />{connectionStatus[0].toUpperCase() + connectionStatus.slice(1)}</span>
      </header>
      <div className="message-scroll" ref={scrollRef} onScroll={onScroll} role="log" aria-label={`Messages with ${title}`} aria-live="polite" aria-busy={loading || loadingOlder}>
        {nextCursor !== null && <div className="older-messages-control"><button type="button" onClick={loadOlder} disabled={loadingOlder || loading}>{loadingOlder ? 'Loading older messages…' : 'Load older messages'}</button></div>}
        {loading && <div className="message-state"><span className="mini-spinner" />Loading messages</div>}
        {!loading && historyError && messages.length === 0 && <div className="message-state message-error"><p>{historyError}</p><button type="button" onClick={() => setReloadKey((value) => value + 1)}>Try again</button></div>}
        {!loading && !historyError && messages.length === 0 && <div className="message-state"><span className="empty-chat-icon"><MessageIcon /></span><p>No messages yet</p><span>Send the first message to get the conversation started.</span></div>}
        {!loading && messages.map((message) => <MessageBubble key={message.id} message={message} outgoing={message.sender?.id === user.id} onRetry={() => sendMessage(message.content, message.id)} retryDisabled={sending} />)}
        {!loading && historyError && messages.length > 0 && <div className="inline-history-error" role="alert">{historyError}</div>}
      </div>
      <MessageComposer draft={draft} onDraftChange={setDraft} onKeyDown={handleComposerKeyDown} onSend={() => sendMessage()} canSend={canSend} sending={sending} sendError={sendError} />
    </div>
  )
}

function MessageBubble({ message, outgoing, onRetry, retryDisabled }) {
  const failed = message.delivery === 'failed'
  return (
    <article className={`message-row${outgoing ? ' is-outgoing' : ''}`}>
      {!outgoing && <Avatar name={message.sender?.username} />}
      <div className={`message-bubble${outgoing ? ' outgoing-bubble' : ' incoming-bubble'}${failed ? ' failed-bubble' : ''}`}>
        {!outgoing && <strong className="message-sender">{message.sender?.username || 'Unknown user'}</strong>}
        <p>{message.content}</p>
        <div className="message-meta"><time dateTime={message.created_at}>{formatMessageTime(message.created_at)}</time>{message.delivery === 'sending' && <span>Sending…</span>}{message.delivery === 'unknown' && <span title="The connection closed before Relay confirmed delivery. Check the conversation before sending this again.">Delivery unknown · check history</span>}{failed && <><span>{message.deliveryMessage || 'Not sent'}</span><button type="button" onClick={onRetry} disabled={retryDisabled}>Retry</button></>}</div>
      </div>
    </article>
  )
}

function MessageComposer({ draft, onDraftChange, onKeyDown, onSend, canSend, sending, sendError }) {
  return (
    <form className="message-composer" onSubmit={(event) => { event.preventDefault(); onSend() }}>
      <label className="sr-only" htmlFor="message-draft">Write a message</label>
      <textarea id="message-draft" value={draft} maxLength={5000} onChange={(event) => onDraftChange(event.target.value)} onKeyDown={onKeyDown} placeholder="Write a message…" rows={2} aria-describedby="composer-hint" />
      <div className="composer-bottom">
        <span id="composer-hint" className="composer-hint">Enter to send · Shift+Enter for a new line · {draft.length}/5000</span>
        <button className="send-button" type="submit" disabled={!canSend}>{sending ? 'Sending…' : 'Send'}<SendIcon /></button>
      </div>
      {sendError && <p className="composer-error" role="alert">{sendError}</p>}
    </form>
  )
}

function Avatar({ name }) {
  const initial = name?.trim()?.[0]?.toUpperCase() || '?'
  return <span className="avatar" aria-hidden="true">{initial}</span>
}

function MessageIcon() { return <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H5l1.8-3.1A7.5 7.5 0 1 1 20 11.5Z" /><path d="M8.5 11.5h7M8.5 14.5h4" /></svg> }
function SendIcon() { return <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m17 3-6.5 14-1.4-5.9L3 9.5 17 3Z" /><path d="m9.1 11.1 3.7-3.7" /></svg> }
