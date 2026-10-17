import { listonicLink, type CalendarDay, type Meal, type ShoppingItem } from './api'
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

const MOBILE = /Android|iPhone|iPad|iPod/i

/**
 * Opens Listonic with these lines, as its own website button does: the app on phones (on
 * Android through an intent, which falls back to the Play Store), its web widget elsewhere.
 * The window is opened before the link is ready, while the tap still allows it; `ready` runs
 * once the link exists and before leaving the page (on phones the app takes over).
 */
export async function sendToListonic(
  lines: string[],
  listName: string,
  ready: () => Promise<unknown>,
): Promise<void> {
  const mobile = MOBILE.test(navigator.userAgent)
  const popup = mobile ? null : window.open('', '_blank')
  try {
    const link = await listonicLink(lines, listName)
    await ready()
    if (!mobile) {
      const hash = link.substring(link.lastIndexOf('/') + 1)
      if (popup) popup.location.href = `https://button.listonic.com/widget?hash=${hash}`
      else window.open(`https://button.listonic.com/widget?hash=${hash}`, '_blank')
    } else if (/Android/i.test(navigator.userAgent)) {
      window.location.href = `intent${link.substring(5)}#Intent;scheme=https;package=com.l;S.browser_fallback_url=${encodeURIComponent(link)};end`
    } else {
      window.location.href = link
    }
  } catch (error) {
    popup?.close()
    throw error
  }
}

/** Whether a meal has something to buy: people at home and an accepted dish with a recipe, as
 * the backend counts (`apps/menus/shopping.py`). */
export function mealHasShopping(day: CalendarDay, meal: Meal): boolean {
  return day.people[meal] > 0 && (day.dishes[meal] ?? []).some((d) => d.recipe !== null && !d.proposed)
}

/** What a new list is for: a day (`date`), a meal (`date`, `meal`) or a recipe (`recipe`,
 * `people`), named by `title`. */
export type ShoppingFor =
  | { date: string; meal?: Meal; title: string }
  | { recipe: number; people: number; title: string }
