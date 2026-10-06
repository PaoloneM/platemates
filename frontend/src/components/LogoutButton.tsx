import { useTranslation } from 'react-i18next'
import { csrfToken } from '../api'

/** Logout must be a POST (CSRF-protected); Django then also ends the Keycloak session. */
export function LogoutButton() {
  const { t } = useTranslation()
  return (
    <form method="post" action="/oidc/logout/" className="inline-form">
      <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken()} />
      <button type="submit" className="button secondary">
        {t('auth.logout')}
      </button>
    </form>
  )
}
