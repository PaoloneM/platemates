import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { api, type Me } from '../api'
import { AuthContext } from './context'
import { syncLanguage } from './language'

/** Loads `/api/me/` (which also sets the CSRF cookie) and shares it with the whole app. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(
    () =>
      api<Me>('/me/').then(
        (data) => {
          syncLanguage(data)
          setMe(data)
          setError(null)
        },
        (e: Error) => setError(e.message),
      ),
    [],
  )

  useEffect(() => {
    let cancelled = false
    api<Me>('/me/').then(
      (data) => {
        if (cancelled) return
        syncLanguage(data)
        setMe(data)
      },
      (e: Error) => !cancelled && setError(e.message),
    )
    return () => {
      cancelled = true
    }
  }, [])

  return <AuthContext.Provider value={{ me, error, refresh: load }}>{children}</AuthContext.Provider>
}
