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

export type Recipe = {
  id: number
  title: string
  course: string
  servings: number
  total_minutes: number | null
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
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
    throw new ApiError(response.status, `${init.method ?? 'GET'} ${path}: ${response.status}`)
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
