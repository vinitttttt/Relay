import assert from 'node:assert/strict'
import test from 'node:test'

import { createTicketedWebSocket } from './api.js'

test('each WebSocket connection request obtains and uses a fresh ticket', async () => {
  const previousWindow = globalThis.window
  globalThis.window = { location: { href: 'https://relay.example/app' } }
  const requests = []
  const sockets = []
  let sequence = 0

  class FakeWebSocket {
    constructor(url, protocols) { this.url = url; this.protocols = protocols; sockets.push(this) }
  }

  const apiFetch = async (path, options) => {
    requests.push({ path, options })
    sequence += 1
    return { ticket: `opaque-ticket-${sequence}`, expires_in: 30 }
  }

  try {
    await createTicketedWebSocket(apiFetch, 12, FakeWebSocket)
    await createTicketedWebSocket(apiFetch, 12, FakeWebSocket)

    assert.equal(requests.length, 2)
    assert.deepEqual(requests.map(({ path, options }) => [path, options.method]), [
      ['/api/v1/auth/websocket-ticket', 'POST'],
      ['/api/v1/auth/websocket-ticket', 'POST'],
    ])
    assert.deepEqual(sockets.map(({ url, protocols }) => {
      const parsed = new URL(url)
      return [parsed.protocol, parsed.pathname, parsed.search, protocols]
    }), [
      ['wss:', '/ws/conversations/12', '', ['relay.v1', 'relay-ticket.opaque-ticket-1']],
      ['wss:', '/ws/conversations/12', '', ['relay.v1', 'relay-ticket.opaque-ticket-2']],
    ])
  } finally {
    if (previousWindow === undefined) delete globalThis.window
    else globalThis.window = previousWindow
  }
})
