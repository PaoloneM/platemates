// Thin client for the Django REST API. Same-origin: the dev proxy or nginx forwards /api.

import i18n from './i18n'

export type ServiceHealth = { ok: boolean; error?: string; [key: string]: unknown }
export type Health = Record<string, ServiceHealth>

export type Paginated<T> = { count: number; next: string | null; results: T[] }

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

function csrfToken(): string {
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
