import { api, type CalendarDay, type CalendarDayChange, type Meal } from './api'

// Dates are calendar days, not instants: always built and formatted in local time.

export function mondayOf(date: Date): Date {
  const monday = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7))
  return monday
}

export function addDays(date: Date, days: number): Date {
  const result = new Date(date)
  result.setDate(result.getDate() + days)
  return result
}

export function isoDate(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export function fromIso(value: string): Date {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(year, month - 1, day)
}

export const isIsoDate = (value: string | null | undefined): value is string =>
  !!value && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(fromIso(value).getTime())

/** The calendar page showing the week of `date`. */
export const weekUrl = (date: string) => `/?week=${isoDate(mondayOf(fromIso(date)))}`

export const mealUrl = (date: string, meal: Meal) => `/calendar/${date}/${meal}`

export function changeDay(team: number, date: string, change: CalendarDayChange) {
  return api<CalendarDay>(`/calendar/${date}/?team=${team}`, { method: 'PUT', body: JSON.stringify(change) })
}

/** What `meals` of `day` look like now, as a change that would put them back (for Undo). */
export function snapshot(day: CalendarDay, meals: Meal[]): CalendarDayChange {
  return {
    people: Object.fromEntries(meals.map((meal) => [meal, day.people[meal]])),
    dishes: Object.fromEntries(
      meals.filter((meal) => day.dishes[meal]).map((meal) => [meal, day.dishes[meal]!.map((d) => d.id)]),
    ),
  }
}

/** Nobody at `meals`, and their dishes removed. */
export function cleared(day: CalendarDay, meals: Meal[]): CalendarDayChange {
  return {
    people: Object.fromEntries(meals.map((meal) => [meal, 0])),
    dishes: Object.fromEntries(meals.filter((meal) => day.dishes[meal]).map((meal) => [meal, []])),
  }
}

/** A meal has something to clear: people expected, or dishes planned. */
export const mealInUse = (day: CalendarDay, meal: Meal) =>
  day.people[meal] > 0 || (day.dishes[meal]?.length ?? 0) > 0
