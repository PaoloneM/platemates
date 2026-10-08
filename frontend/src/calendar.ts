import { api, ApiError, type CalendarDay, type CalendarDayChange, type CalendarDish, type DishInput, type Meal, type MenuGeneration, type Paginated } from './api'

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
      meals.filter((meal) => day.dishes[meal]).map((meal) => [meal, day.dishes[meal]!.map(dishInput)]),
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

/** A dish as a change names it: its recipe, or its title when it has none. */
export const dishInput = (dish: CalendarDish): DishInput =>
  dish.recipe ?? { title: dish.title, course: dish.course }

/** The generator proposed something for this meal: dishes, or a change of people. */
export const hasProposal = (day: CalendarDay, meal: Meal) =>
  day.proposed_people[meal] !== undefined || (day.dishes[meal] ?? []).some((d) => d.proposed)

export const generationActive = (generation: MenuGeneration | null) =>
  generation?.status === 'queued' || generation?.status === 'running'

/** Queue a generation of the week; if one is already running, that one is returned. */
export async function generateMenu(team: number, weekStart: string, useWeekSettings: boolean) {
  try {
    return await api<MenuGeneration>('/menus/generate/', {
      method: 'POST',
      body: JSON.stringify({ team, week_start: weekStart, use_week_settings: useWeekSettings }),
    })
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) return error.body as MenuGeneration
    throw error
  }
}

/** The week's latest generation, or null if it was never generated. */
export async function latestGeneration(team: number, weekStart: string) {
  const page = await api<Paginated<MenuGeneration>>(`/menu-generations/?team=${team}&week_start=${weekStart}`)
  return page.results[0] ?? null
}

/** Accept or reject the generator's proposals: for the given meals, or the whole week. */
export function reviewProposals(menu: number, action: 'accept' | 'reject', meals?: { date: string; meal: Meal }[]) {
  return api<void>(`/menus/${menu}/review/`, { method: 'POST', body: JSON.stringify({ action, meals }) })
}

/** Accept or reject the proposals of one meal, finding its week's menu. */
export async function reviewMeal(team: number, date: string, meal: Meal, action: 'accept' | 'reject') {
  const weekStart = isoDate(mondayOf(fromIso(date)))
  const menus = await api<Paginated<{ id: number }>>(`/menus/?team=${team}&week_start=${weekStart}`)
  if (menus.results[0]) await reviewProposals(menus.results[0].id, action, [{ date, meal }])
}
