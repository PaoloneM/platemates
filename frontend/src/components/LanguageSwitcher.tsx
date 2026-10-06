import { useTranslation } from 'react-i18next'
import { saveLanguage } from '../auth/language'
import { useAuth } from '../auth/context'
import { supportedLanguages } from '../i18n'

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()

  function change(language: string) {
    void i18n.changeLanguage(language)
    // Signed in: remember it for this user on every device, not just in this browser.
    if (me?.authenticated) void saveLanguage(language)
  }

  return (
    <label className="language">
      <span className="visually-hidden">{t('app.language')}</span>
      <select value={i18n.resolvedLanguage} onChange={(e) => change(e.target.value)}>
        {Object.entries(supportedLanguages).map(([code, name]) => (
          <option key={code} value={code}>
            {name}
          </option>
        ))}
      </select>
    </label>
  )
}
