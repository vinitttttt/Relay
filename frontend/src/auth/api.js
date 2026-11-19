const API_BASE_URL = (import.meta.env?.VITE_API_BASE_URL || '').replace(/\/$/, '')

export function conversationWebSocketUrl(conversationId) {
  const base = API_BASE_URL ? new URL(API_BASE_URL, window.location.href) : new URL(window.location.href)
  base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:'
  base.pathname = `/ws/conversations/${conversationId}`
  base.search = ''
  return base.toString()
}

export async function createTicketedWebSocket(apiFetch, conversationId, WebSocketImpl = WebSocket) {
  const response = await apiFetch('/api/v1/auth/websocket-ticket', { method: 'POST' })
  if (typeof response?.ticket !== 'string' || !response.ticket) {
    throw new Error('Relay did not issue a WebSocket ticket.')
  }
  return new WebSocketImpl(conversationWebSocketUrl(conversationId), [
    'relay.v1',
    `relay-ticket.${response.ticket}`,
  ])
}

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
    })
  } catch {
    throw new ApiError('Unable to reach Relay. Check your connection and try again.')
  }

  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = body?.detail
    const message = Array.isArray(detail)
      ? detail.map((issue) => issue.msg).join(' ')
      : typeof detail === 'string'
        ? detail
        : 'Something went wrong. Please try again.'
    throw new ApiError(message, response.status)
  }
  return body
}

export function authenticatedRequest(path, token, options = {}) {
  return request(path, {
    ...options,
    headers: {
      ...options.headers,
      Authorization: `Bearer ${token}`,
    },
  })
}
