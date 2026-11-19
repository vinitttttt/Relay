import assert from 'node:assert/strict'
import test from 'node:test'

import {
  getClientMessageId,
  latestConfirmedMessageId,
  mergeMessages,
  recoverMessagesAfter,
} from './messageReliability.js'
import { apiDate, parseApiTimestamp } from './timestamps.js'

const own = (id, clientId, content, extra = {}) => ({
  id,
  conversation_id: 7,
  client_message_id: clientId,
  content,
  created_at: new Date((Number(id) || 1) * 1000).toISOString(),
  sender: { id: 1, username: 'alice' },
  ...extra,
})

test('optimistic reconciliation uses client ID and preserves retry IDs', () => {
  const optimistic = own('pending-stable', 'stable-client-id', 'same text')
  const unrelated = own(40, 'other-id', 'same text')
  const confirmed = own(41, 'stable-client-id', 'same text')
  const merged = mergeMessages([optimistic, unrelated], [confirmed])
  assert.deepEqual(merged.map((message) => message.id), [40, 41])
  assert.equal(getClientMessageId(optimistic), 'stable-client-id')
})

test('duplicate REST, event and recovery messages merge once in server order', () => {
  const first = own(8, 'a', 'first')
  const second = own(9, 'b', 'second')
  const merged = mergeMessages([first], [second, first, second])
  assert.deepEqual(merged.map((message) => message.id), [8, 9])
  assert.equal(latestConfirmedMessageId(merged), 9)
})

test('reconnect recovery follows every forward page until caught up', async () => {
  const calls = []
  const pages = new Map([
    [10, { items: [own(11, '11', 'eleven'), own(12, '12', 'twelve')], next_cursor: 12 }],
    [12, { items: [own(13, '13', 'thirteen'), own(14, '14', 'fourteen')], next_cursor: 14 }],
    [14, { items: [own(15, '15', 'fifteen')], next_cursor: null }],
  ])
  const recovered = await recoverMessagesAfter(async (path) => {
    calls.push(path)
    const cursor = Number(new URL(path, 'https://relay.example').searchParams.get('after_id'))
    return pages.get(cursor) || { items: [], next_cursor: null }
  }, 7, 10, 2)
  assert.deepEqual(calls.map((path) => Number(new URL(path, 'https://relay.example').searchParams.get('after_id'))), [10, 12, 14])
  assert.deepEqual(recovered.map((message) => message.id), [11, 12, 13, 14, 15])
  assert.deepEqual(mergeMessages([own(12, '12', 'twelve')], recovered).map((message) => message.id), [11, 12, 13, 14, 15])
})

test('recovery stops safely on an empty or non-advancing page', async () => {
  let calls = 0
  const messages = await recoverMessagesAfter(async () => {
    calls += 1
    return { items: [own(5, '5', 'stale')], next_cursor: 4 }
  }, 7, 4, 2)
  assert.equal(calls, 1)
  assert.deepEqual(messages.map((message) => message.id), [5])

  let emptyCalls = 0
  const empty = await recoverMessagesAfter(async () => {
    emptyCalls += 1
    return { items: [], next_cursor: null }
  }, 7, 5, 2)
  assert.equal(emptyCalls, 1)
  assert.deepEqual(empty, [])
})

test('UTC and legacy SQLite timestamps parse as the same instant', () => {
  const utc = '2025-02-03T04:05:06Z'
  const legacy = '2025-02-03T04:05:06'
  assert.equal(parseApiTimestamp(legacy), `${legacy}Z`)
  assert.equal(apiDate(utc).toISOString(), apiDate(legacy).toISOString())
})
