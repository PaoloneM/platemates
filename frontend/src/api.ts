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
        language: string | null
      }
      families: { id: number; name: string; role: 'owner' | 'member' }[]
    }

export type LoginOptions = { identity_providers: IdentityProvider[] }
export type IdentityProvider = 'google' | 'microsoft' | 'apple'

export type InvitationPreview = {
  family_name: string
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

export type BookEntryRef = { id: number; family: number; status: string; rating: number | null }

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
  owner_family: number | null
  can_edit: boolean
  book_entries: BookEntryRef[]
  ingredients: RecipeLine[]
  provenance: Record<string, Source>
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
  family: number
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
  family: number
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
