import { MenuItem, TextField } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../auth/context'
import { saveLanguage } from '../auth/language'
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
    <TextField
      select
      size="small"
      fullWidth={false}
      value={i18n.resolvedLanguage}
      onChange={(e) => change(e.target.value)}
      slotProps={{ htmlInput: { 'aria-label': t('app.language') } }}
    >
      {Object.entries(supportedLanguages).map(([code, name]) => (
        <MenuItem key={code} value={code}>
          {name}
        </MenuItem>
      ))}
    </TextField>
  )
}
