import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createTicketedWebSocket } from '../auth/api.js'
import {
  createClientMessageId,
  getClientMessageId,
  latestConfirmedMessageId,
  mergeMessages,
  MESSAGE_PAGE_SIZE,
  recoverMessagesAfter,
} from './messageReliability.js'
import { apiDate } from './timestamps.js'

function formatMessageTime(value) {
  const date = apiDate(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(date)
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
  const latestConfirmedIdRef = useRef(0)
  const updateConnectionStatus = useCallback((status) => {
    setConnectionStatus(status)
  }, [])

  useEffect(() => {
    mountedRef.current = true
    let active = true
    setLoading(true)
    setHistoryError('')
    apiFetch(`/api/v1/conversations/${conversation.id}/messages?limit=${MESSAGE_PAGE_SIZE}`)
      .then((page) => {
        if (!active) return
        const initialMessages = Array.isArray(page?.items) ? page.items : []
        setMessages((current) => {
          const merged = mergeMessages(current, initialMessages)
          latestConfirmedIdRef.current = Math.max(
            latestConfirmedIdRef.current,
            latestConfirmedMessageId(merged),
          )
          return merged
        })
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
    const resendPending = () => {
      const activeSocket = socketRef.current
      if (!activeSocket || activeSocket.readyState !== WebSocket.OPEN) return
      pendingRef.current.forEach((pending, clientMessageId) => {
        pending.sent = true
        setMessages((current) => current.map((item) =>
          item.id === pending.localId ? { ...item, delivery: 'sending' } : item,
        ))
        try {
          activeSocket.send(JSON.stringify({
            type: 'message.send',
            client_message_id: clientMessageId,
            content: pending.content,
          }))
        } catch { /* The next socket close will schedule another attempt. */ }
      })
    }
    const recoverAfterCursor = async () => {
      try {
        const recovered = await recoverMessagesAfter(
          apiFetch,
          conversation.id,
          latestConfirmedIdRef.current,
          MESSAGE_PAGE_SIZE,
        )
        if (!stopped && mountedRef.current) {
          recovered.forEach((message) => {
            if (message.sender?.id === user.id && message.client_message_id) {
              pendingRef.current.delete(message.client_message_id)
            }
            onMessage?.(conversation.id, message)
          })
          setMessages((current) => {
            const merged = mergeMessages(current, recovered)
            latestConfirmedIdRef.current = Math.max(
              latestConfirmedIdRef.current,
              latestConfirmedMessageId(merged),
            )
            return merged
          })
        }
      } catch { /* The next reconnect or normal history retry can recover it. */ }
      finally { resendPending() }
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
        if (reconnecting) recoverAfterCursor()
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
            client_message_id: data.client_message_id ?? null,
            created_at: data.created_at,
            sender: { id: data.sender_id, username: data.sender_username },
          }
          if (message.sender.id === user.id && message.client_message_id) {
            pendingRef.current.delete(message.client_message_id)
          }
          latestConfirmedIdRef.current = Math.max(latestConfirmedIdRef.current, Number(message.id))
          onMessage?.(conversation.id, message)
          setMessages((current) => mergeMessages(current, [message]))
          return
        }
        if (payload?.type === 'error') {
          const clientMessageId = payload.data?.client_message_id
          const pendingMessage = clientMessageId ? pendingRef.current.get(clientMessageId) : null
          if (pendingMessage) {
            pendingRef.current.delete(clientMessageId)
            setMessages((current) => current.map((item) => item.id === pendingMessage.localId ? { ...item, delivery: 'failed', deliveryMessage: payload.data?.detail || 'The server rejected this message.' } : item))
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
        pendingRef.current.forEach((pending) => {
          if (pending.sent) setMessages((current) => current.map((item) => item.id === pending.localId ? { ...item, delivery: 'unknown' } : item))
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
      const page = await apiFetch(`/api/v1/conversations/${conversation.id}/messages?limit=${MESSAGE_PAGE_SIZE}&before_id=${nextCursor}`)
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

  async function sendMessage(content = draft, retryClientId = null, retryLocalId = null) {
    const messageContent = content
    if (!messageContent.trim() || messageContent.length > 5000 || sendingRef.current) return
    sendingRef.current = true
    setSending(true)
    setSendError('')
    bottomRequestedRef.current = true
    const clientMessageId = retryClientId || createClientMessageId()
    let localId = retryLocalId
    if (!localId) {
      localId = `pending-${clientMessageId}`
      setMessages((current) => mergeMessages(current, [{
        id: localId,
        conversation_id: conversation.id,
        content: messageContent,
        client_message_id: clientMessageId,
        created_at: new Date().toISOString(),
        sender: { id: user.id, username: user.username },
        delivery: 'sending',
      }]))
    } else {
      setMessages((current) => current.map((message) => message.id === localId ? { ...message, delivery: 'sending' } : message))
    }
    pendingRef.current.set(clientMessageId, { content: messageContent, localId, sent: false })
    try {
      const socket = socketRef.current
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        const saved = await apiFetch(`/api/v1/conversations/${conversation.id}/messages`, { method: 'POST', body: JSON.stringify({ content: messageContent, client_message_id: clientMessageId }) })
        if (!mountedRef.current) return
        pendingRef.current.delete(clientMessageId)
        latestConfirmedIdRef.current = Math.max(latestConfirmedIdRef.current, Number(saved.id))
        setMessages((current) => mergeMessages(current, [saved]))
        onMessage?.(conversation.id, saved)
      } else {
        pendingRef.current.set(clientMessageId, { content: messageContent, localId, sent: true })
        socket.send(JSON.stringify({ type: 'message.send', client_message_id: clientMessageId, content: messageContent }))
        setDraft((current) => current === messageContent ? '' : current)
      }
      setDraft((current) => current === messageContent ? '' : current)
    } catch (error) {
      if (!mountedRef.current) return
      const ambiguous = pendingRef.current.get(clientMessageId)?.sent
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
        {!loading && messages.map((message) => <MessageBubble key={message.id} message={message} outgoing={message.sender?.id === user.id} onRetry={() => sendMessage(message.content, getClientMessageId(message), message.id)} retryDisabled={sending} />)}
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
