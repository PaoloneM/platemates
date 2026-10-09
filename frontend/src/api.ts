// Thin client for the Django REST API. Same-origin: the dev proxy or nginx forwards /api.

import i18n from './i18n'

export type ServiceHealth = { ok: boolean; error?: string; [key: string]: unknown }
export type Health = Record<string, ServiceHealth>

export type Paginated<T> = { count: number; next: string | null; results: T[] }

export type Me =
  | { authenticated: false }
  | {
      authenticated: true
      user: {
        id: number
        email: string
        first_name: string
        last_name: string
        is_staff: boolean
        // Holds Keycloak's `admin` role: changes the application settings.
        is_admin: boolean
        language: string | null
      }
      teams: { id: number; name: string; role: 'owner' | 'member' }[]
      // Staff only: the system team, whose recipes are the curated part of the community.
      system_team: number | null
    }

export type LoginOptions = { identity_providers: IdentityProvider[] }
export type IdentityProvider = 'google' | 'microsoft' | 'apple'

export type InvitationPreview = {
  team_name: string
  role: 'owner' | 'member'
  state: 'pending' | 'accepted' | 'expired' | 'revoked'
  expires_at: string
}

export type Seasonality = { months: number[]; seasons: Season[]; by_season: boolean }
export type Season = 'winter' | 'spring' | 'summer' | 'autumn'
export type Unit = 'g' | 'ml' | 'pc' | 'tt'
export type Course = 'first' | 'main' | 'side' | 'single' | 'starter' | 'dessert'
export type Visibility = 'shared' | 'private'
export type Source = 'llm' | 'derived' | 'user'

export type Ingredient = {
  id: number
  name: string
  aliases: string[]
  category: string
  default_unit: Unit
  season_months: Seasonality
  // Recipes using it.
  usage_count: number
  provenance: Record<string, Source>
}

export type Cuisine = { id: number; name: string }
// `code` is set for the tools the app ships with (shown translated), null for the ones users add.
export type KitchenTool = { id: number; code: string | null; name: string; heats_kitchen: boolean }

export type RecipeLine = {
  id?: number
  ingredient: number
  ingredient_name?: string
  ingredient_category?: string
  ingredient_season_months?: number[]
  quantity: string | null
  unit: Unit
  optional: boolean
  note: string
}

export type BookEntryRef = { id: number; team: number; status: string; rating: number | null }

// Where a recipe comes from, as the user may see it: the system (PlateMates), one of their
// teams, another team that signs its shared recipes, or the community (anonymous).
export type RecipeAuthor = { kind: 'system' | 'mine' | 'team' | 'community'; name: string | null }

// The original a recipe was imported from and changed (it is a variant of it).
export type RecipeOrigin = { id: number; title: string }

export type Recipe = {
  id: number
  title: string
  description: string
  steps: string[]
  course: Course
  cuisine: number | null
  cuisine_name: string | null
  servings: number
  prep_minutes: number | null
  cook_minutes: number | null
  total_minutes: number | null
  tools: number[]
  season_months: Seasonality
  climate_months: Seasonality
  source_url: string
  visibility: Visibility
  owner_team: number | null
  can_edit: boolean
  book_entries: BookEntryRef[]
  ingredients: RecipeLine[]
  provenance: Record<string, Source>
  derived_from: number | null
  origin: RecipeOrigin | null
  author: RecipeAuthor
  // The web rating read from the pages a system recipe was drafted from (0-5, and votes).
  web_rating: string | null
  web_rating_count: number | null
}

// A recipe on the recipe book screen: in the team's book (`book`), or in the community.
export type RecipeCard = {
  id: number
  title: string
  course: Course
  cuisine_name: string | null
  servings: number
  total_minutes: number | null
  suitable_months: number[]
  visibility: Visibility
  author: RecipeAuthor
  origin: RecipeOrigin | null
  book: { id: number; rating: number | null } | null
  web_rating: string | null
  web_rating_count: number | null
}

export type DraftStatus = 'queued' | 'running' | 'ready' | 'failed' | 'published' | 'discarded'
export type Reliability = 'high' | 'medium' | 'low'

// A system recipe draft (staff): researched on the web, drafted by the LLM, to review.
export type SystemDraft = {
  id: number
  dish: string
  language: string
  status: DraftStatus
  sources: { url: string; site: string; title: string; rating: number | null; rating_count: number | null }[]
  draft: Draft | null
  reliability: Reliability | ''
  agreement: number | null
  web_rating: string | null
  web_rating_count: number | null
  error: string
  recipe: number | null
  requested_by_name: string | null
  created_at: string
  finished_at: string | null
  // Detail only: each draft ingredient's catalog match.
  matches?: IngredientMatch[]
}

// The worker's progress on a draft, sent to staff in real time.
export type SystemDraftEvent = { id: number; dish: string; status: DraftStatus; phase: string; sources?: number }

export type RecipeVariants = {
  original: { id: number; title: string; author: RecipeAuthor } | null
  variants: { id: number; title: string; author: RecipeAuthor }[]
}

export type RecipeSummary = {
  id: number
  title: string
  course: Course
  cuisine_name: string | null
  servings: number
  total_minutes: number | null
  season_months: number[]
  // Ingredients and climate combined; empty = suitable all year.
  suitable_months: number[]
  visibility: Visibility
}

export type Role = 'owner' | 'member'

export type Meal = 'breakfast' | 'lunch' | 'dinner'

// One day of the team's typical week: whether the team eats together at all that day, and how
// many people at each meal. The typical week is Monday first.
export type TypicalDay = { active: boolean } & Record<Meal, number>

// A date of the team calendar: the typical week's counts (`usual`), what applies on that date
// (`people`), and which meals differ from the typical week.
export type CalendarDay = {
  date: string
  active: boolean
  usual: Record<Meal, number>
  people: Record<Meal, number>
  overridden: Meal[]
  note: string
  // Planned meals only (lunch, dinner): breakfast is counted, not planned.
  dishes: Partial<Record<Meal, CalendarDish[]>>
  // Changes to the people proposed by the menu generator, with their reasons: `people` stays
  // as it is until the user accepts them.
  proposed_people: Partial<Record<Meal, number>>
  people_notes: Partial<Record<Meal, string>>
}

// A dish of a meal: a recipe, or a dish named by its title only (`recipe` null), such as a new
// dish the generator suggests. `proposed`: suggested by the generator, not accepted yet.
export type CalendarDish = {
  recipe: number | null
  title: string
  course: Course | ''
  proposed: boolean
  note: string
}

// How a change names a dish: a recipe id, or a title for a dish without a recipe.
export type DishInput = number | { title: string; course: Course | '' }

// A change to a date; every part is optional. `dishes` replaces the listed meals' dishes.
export type CalendarDayChange = {
  people?: Partial<Record<Meal, number>>
  note?: string
  dishes?: Partial<Record<Meal, DishInput[]>>
}

// A rule every team's menus follow, kept in both interface languages. Shipped rules have a
// code and are switched off rather than deleted; rules added by staff have none.
export type SystemRule = {
  id: number
  code: string | null
  text_it: string
  text_en: string
  position: number
  active: boolean
}

// One of the team's standing rules for planning its weeks, in natural language.
export type TeamRule = { id: number; team: number; text: string }

// A week's menu with how to plan it: `instructions` on top of the rules; `use_team_rules`
// false leaves out every team rule, otherwise only `excluded_rules` are left out.
export type WeeklyMenu = {
  id: number
  team: number
  week_start: string
  status: 'draft' | 'approved' | 'archived'
  rationale: string
  instructions: string
  use_team_rules: boolean
  excluded_rules: number[]
}

// An application setting, changed by administrators (`/manage/settings`).
export type ConfigSetting = {
  key: string
  kind: 'bool' | 'int'
  group: string
  default: boolean | number
  minimum: number | null
  maximum: number | null
  value: boolean | number
  is_default: boolean
  updated_at: string | null
  updated_by: string | null
}

// The two-level cache of rules and settings (`/manage/cache`). `process`: the counters of the
// backend process that answered; `shared`: Redis's own figures.
export type CacheStats = {
  process: { memory_hits: number; shared_hits: number; misses: number; errors: number }
  shared: {
    available: boolean
    error?: string
    version?: string
    keys?: number
    used_memory?: string
    max_memory?: string
    hits?: number
    misses?: number
    uptime_seconds?: number
  }
  timeouts: { memory_seconds: number | null; shared_seconds: number | null }
  last_cleared: { at: string; by: string } | null
}

// A generation's progress, sent by the worker through the real-time connection.
export type GenerationPhase =
  | 'queued' | 'preparing' | 'thinking' | 'planning' | 'writing' | 'checking' | 'retrying'
  | 'done' | 'failed'
export type GenerationEvent = {
  id: number
  team: number
  menu: number
  week_start: string
  status: GenerationStatus
  phase: GenerationPhase
  meals_done?: number
  meals_total?: number
  error?: string
}

export type GenerationStatus = 'queued' | 'running' | 'done' | 'failed'

// A request to generate a week's menu, run in the background.
export type MenuGeneration = {
  id: number
  menu: number
  week_start: string
  status: GenerationStatus
  use_week_settings: boolean
  rules: { system?: string[]; team?: string[]; week?: string }
  result: {
    rationale: string
    unplanned: { date: string; meal: Meal }[]
  } | null
  error: string
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export type TeamProfile = {
  id: number
  name: string
  tools: number[]
  typical_week: TypicalDay[]
  max_weekday_minutes: number | null
  notes: string
  // Whether its shared recipes show its name in the community.
  sign_shared_recipes: boolean
  members: Person[]
  my_role: Role | null
}

// Someone who eats at the team's table; not necessarily an app user.
export type Person = { id: number; team: number; name: string; birth_year: number | null }

// An app user with access to the team.
export type TeamMembership = {
  id: number
  team: number
  name: string
  email: string
  role: Role
  is_me: boolean
}

export type Invitation = {
  id: number
  team: number
  token?: string // owners only
  role: Role
  note: string
  state: 'pending' | 'accepted' | 'expired' | 'revoked'
  created_at: string
  expires_at: string
  accepted_at: string | null
  invited_by_name: string | null
  accepted_by_name: string | null
}

export type AssistantMode = 'tell' | 'search' | 'link' | 'photo'

export type DraftLine = {
  name: string
  quantity: string | null
  unit: Unit
  note: string
  optional: boolean
  category: string
  season_months: number[]
}

export type Draft = {
  title: string
  description: string
  course: Course
  cuisine: string
  servings: number
  prep_minutes: number | null
  cook_minutes: number | null
  ingredients: DraftLine[]
  steps: string[]
  climate_months: number[]
  source_url: string
}

export type MatchCandidate = {
  id: number
  name: string
  category: string
  default_unit: Unit
  season_months: number[]
  similarity: number
}

export type IngredientMatch = { match: number | null; exact: boolean; candidates: MatchCandidate[] }

export type SearchResult =
  | {
      kind: 'book' | 'shared'
      recipe: number
      title: string
      course: Course
      total_minutes: number | null
      similarity: number
    }
  | { kind: 'web'; url: string; site: string; title: string; servings: number | null; dish: string }

export type AssistantSession = {
  id: number
  team: number
  mode: AssistantMode
  status: 'open' | 'saved' | 'abandoned'
  recipe: number | null
  draft: Draft | null
  matches: IngredientMatch[]
  attachments: { id: number; transcription: string }[]
  transcript: {
    role: 'user' | 'assistant'
    text: string
    draft?: boolean
    error?: string
    attachment?: number
    results?: SearchResult[]
    notice?: string
  }[]
}

export type BookEntry = {
  id: number
  team: number
  recipe: number
  recipe_summary: RecipeSummary
  status: 'candidate' | 'approved' | 'rejected'
  rating: number | null
  notes: string
}

export class ApiError extends Error {
  status: number
  // Parsed error body: DRF validation errors are {field: [messages]}.
  body: unknown

  constructor(status: number, message: string, body: unknown = null) {
    super(message)
    this.status = status
    this.body = body
  }
}

export function csrfToken(): string {
  return document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] ?? ''
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    credentials: 'same-origin',
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken(),
      // Backend messages (validation errors, choice labels) follow the interface language.
      'Accept-Language': i18n.resolvedLanguage ?? 'it',
      ...init.headers,
    },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(response.status, `${init.method ?? 'GET'} ${path}: ${response.status}`, body)
  }
  return response.status === 204 ? (undefined as T) : response.json()
}

/** Full-page navigation to the backend's OIDC login, which redirects to Keycloak. */
export function loginUrl(options: { next?: string; idp?: IdentityProvider; signup?: boolean } = {}) {
  const params = new URLSearchParams({
    next: options.next ?? '/',
    lang: i18n.resolvedLanguage ?? 'it',
  })
  if (options.idp) params.set('idp', options.idp)
  if (options.signup) params.set('signup', '1')
  return `/oidc/authenticate/?${params}`
}

/** POST multipart form data (files). The browser sets the multipart boundary itself. */
export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: 'POST',
    credentials: 'same-origin',
    body: form,
    headers: { 'X-CSRFToken': csrfToken(), 'Accept-Language': i18n.resolvedLanguage ?? 'it' },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(response.status, `POST ${path}: ${response.status}`, body)
  }
  return response.json()
}
