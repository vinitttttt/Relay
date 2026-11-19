export function parseApiTimestamp(value) {
  if (typeof value !== 'string') return value
  // Legacy SQLite timestamps had no zone marker but represent UTC.
  return /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`
}

export function apiDate(value) {
  return new Date(parseApiTimestamp(value))
}
