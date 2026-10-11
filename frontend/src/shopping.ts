import type { ShoppingItem } from './api'
import { formatQuantity } from './labels'

/** "12–18 ottobre", or across months/weeks "28 settembre – 11 ottobre": the days covered. */
export function weekRange(mondays: string[], locale: string | undefined): string {
  if (mondays.length === 0) return ''
  const sorted = [...mondays].sort()
  const first = new Date(`${sorted[0]}T12:00:00`)
  const last = new Date(`${sorted[sorted.length - 1]}T12:00:00`)
  last.setDate(last.getDate() + 6)
  return new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'long' }).formatRange(first, last)
}

/** "400 g", "1,5 pz", "q.b.": an item's amount as people read it. */
export function formatAmount(
  item: Pick<ShoppingItem, 'quantity' | 'unit' | 'ingredient'>,
  unitLabel: (u: string) => string,
  locale: string | undefined,
): string {
  // "To taste" is a recipe's word: something added by hand without an amount shows none.
  if (item.unit === 'tt') return item.ingredient === null ? '' : unitLabel('tt')
  if (item.quantity === null) return ''
  return `${formatQuantity(Number(item.quantity), locale)} ${unitLabel(item.unit)}`
}
