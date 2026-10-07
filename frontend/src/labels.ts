import { useTranslation } from 'react-i18next'
import type { Course, Meal, Season, Unit } from './api'

// Stable codes from the API, translated for display. Kept in one place so every screen
// names things the same way.
export const COURSES: Course[] = ['first', 'main', 'single', 'side', 'starter', 'dessert']
export const UNITS: Unit[] = ['g', 'ml', 'pc', 'tt']
export const MEALS: Meal[] = ['breakfast', 'lunch', 'dinner']
export const SEASONS: Season[] = ['winter', 'spring', 'summer', 'autumn']
export const SEASON_MONTHS: Record<Season, number[]> = {
  winter: [12, 1, 2],
  spring: [3, 4, 5],
  summer: [6, 7, 8],
  autumn: [9, 10, 11],
}
export const INGREDIENT_CATEGORIES = [
  'vegetable', 'fruit', 'legume', 'cereal', 'red_meat', 'white_meat', 'cured_meat', 'fish',
  'seafood', 'egg', 'dairy', 'cheese', 'fat', 'nut_seed', 'herb_spice', 'condiment', 'sweetener',
  'other',
]

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

export function useLabels() {
  const { t, i18n } = useTranslation()
  const monthFormat = new Intl.DateTimeFormat(i18n.resolvedLanguage, { month: 'short' })
  const monthLong = new Intl.DateTimeFormat(i18n.resolvedLanguage, { month: 'long' })
  const weekdayFormat = new Intl.DateTimeFormat(i18n.resolvedLanguage, { weekday: 'long' })
  const weekdayShort = new Intl.DateTimeFormat(i18n.resolvedLanguage, { weekday: 'short' })
  // 2026-10-05 is a Monday: weekday 0 is Monday, as in the API.
  const weekdayDate = (d: number) => new Date(2026, 9, 5 + d)
  return {
    course: (c: string) => t(`course.${c}`),
    unit: (u: string) => t(`unit.${u}`),
    category: (c: string) => t(`category.${c}`),
    season: (s: string) => t(`season.${s}`),
    // Shipped tools are translated from their code; tools added by users keep their own name.
    tool: (tool: { code: string | null; name: string }) =>
      tool.code ? t(`tool.${tool.code}`, { defaultValue: tool.name }) : tool.name,
    month: (m: number) => monthFormat.format(new Date(2026, m - 1, 1)),
    monthLong: (m: number) => monthLong.format(new Date(2026, m - 1, 1)),
    meal: (m: Meal) => t(`meal.${m}`),
    // Italian weekday names are lowercase; they head rows and cards here.
    weekday: (d: number) => capitalize(weekdayFormat.format(weekdayDate(d))),
    weekdayShort: (d: number) => capitalize(weekdayShort.format(weekdayDate(d))),
  }
}

/** Short human description of a month set: "Estate", "Estate, autunno", "Mag-Ago", "Tutto l'anno". */
export function useDescribeMonths() {
  const { t } = useTranslation()
  const labels = useLabels()
  return (months: number[]) => {
    if (months.length === 0 || months.length === 12) return t('season.allYear')
    const set = new Set(months)
    const whole = SEASONS.filter((s) => SEASON_MONTHS[s].every((m) => set.has(m)))
    const covered = new Set(whole.flatMap((s) => SEASON_MONTHS[s]))
    if (covered.size === set.size) return whole.map((s) => labels.season(s)).join(', ')
    return [...set].sort((a, b) => a - b).map(labels.month).join(', ')
  }
}

/** Quantities are decimals from the API ("240.00"); show them without trailing zeros. */
export function formatQuantity(value: number, language?: string): string {
  const rounded = value >= 10 ? Math.round(value) : Math.round(value * 10) / 10
  return new Intl.NumberFormat(language, { maximumFractionDigits: 1 }).format(rounded)
}

/** Months are what is stored; seasons are only a view onto them. */
export function isSeasonAligned(months: number[]): boolean {
  const set = new Set(months)
  return SEASONS.every((s) => {
    const inSet = SEASON_MONTHS[s].filter((m) => set.has(m)).length
    return inSet === 0 || inSet === 3
  })
}
