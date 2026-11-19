export const MESSAGE_PAGE_SIZE = 50

export function createClientMessageId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `relay-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function getClientMessageId(message) {
  return message?.client_message_id || createClientMessageId()
}

function clientKey(message) {
  const clientId = message.client_message_id
  const senderId = message.sender?.id ?? message.sender_id
  if (!clientId || senderId == null) return null
  return `${message.conversation_id}:${senderId}:${clientId}`
}

export function mergeMessages(current, incoming) {
  const byId = new Map(current.map((message) => [message.id, message]))
  const byClientId = new Map()
  byId.forEach((message) => {
    const key = clientKey(message)
    if (key) byClientId.set(key, message.id)
  })
  incoming.forEach((message) => {
    const key = clientKey(message)
    const matchingId = key ? byClientId.get(key) : null
    if (matchingId != null && matchingId !== message.id) byId.delete(matchingId)
    const existing = byId.get(message.id)
    byId.set(message.id, { ...existing, ...message })
    if (key) byClientId.set(key, message.id)
  })
  return [...byId.values()].sort((a, b) => {
    const timeDifference = new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    if (timeDifference) return timeDifference
    return String(a.id).localeCompare(String(b.id), undefined, { numeric: true })
  })
}

export function latestConfirmedMessageId(messages) {
  return messages.reduce((latest, message) => {
    const id = Number(message.id)
    return Number.isFinite(id) ? Math.max(latest, id) : latest
  }, 0)
}

export async function recoverMessagesAfter(apiFetch, conversationId, initialCursor, limit = MESSAGE_PAGE_SIZE) {
  const recovered = []
  let cursor = Number(initialCursor) || 0
  while (true) {
    const page = await apiFetch(
      `/api/v1/conversations/${conversationId}/messages?limit=${limit}&after_id=${cursor}`,
    )
    const items = Array.isArray(page?.items) ? page.items : []
    if (!items.length) break
    recovered.push(...items)
    const pageLastId = latestConfirmedMessageId(items)
    const nextCursor = page?.next_cursor == null ? null : Number(page.next_cursor)
    if (nextCursor == null || nextCursor <= cursor || pageLastId <= cursor) break
    cursor = Math.max(nextCursor, pageLastId)
  }
  return recovered
}
