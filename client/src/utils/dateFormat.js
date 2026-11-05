// Format a date for display. Date-only strings ("YYYY-MM-DD", e.g. expected_delivery)
// are parsed as LOCAL dates: `new Date('2026-03-05')` is treated as UTC midnight, which
// renders as the previous day in timezones west of UTC.
// Returns an empty string for missing/invalid input instead of "Invalid Date".
export function formatDateOnly(dateString, locale = 'en') {
  if (!dateString) return ''
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateString)
  const date = match
    ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
    : new Date(dateString)
  if (isNaN(date.getTime())) return ''
  return date.toLocaleDateString(locale === 'ja' ? 'ja-JP' : 'en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
}
