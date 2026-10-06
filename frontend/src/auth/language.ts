import { api, type Me } from '../api'
import i18n from '../i18n'

/**
 * The interface language is a per-user preference stored by the backend, so it follows the user
 * across devices. Signed out, the browser's last choice (localStorage) or language is used; once
 * signed in, the saved preference wins. A user without one adopts the current language.
 */
export function syncLanguage(me: Me) {
  if (!me.authenticated) return
  const saved = me.user.language
  if (saved) {
    if (saved !== i18n.resolvedLanguage) void i18n.changeLanguage(saved)
  } else {
    void saveLanguage(i18n.resolvedLanguage ?? 'it')
  }
}

export function saveLanguage(language: string) {
  return api('/me/', { method: 'PATCH', body: JSON.stringify({ language }) }).catch(() => {
    // A failed save only means the choice is not remembered on other devices.
  })
}
