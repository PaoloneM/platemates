import { MenuItem, Stack, TextField } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../auth/context'
import { saveLanguage } from '../auth/language'
import { supportedLanguages } from '../i18n'
import { Flag } from './Flag'

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
      slotProps={{
        htmlInput: { 'aria-label': t('app.language') },
        select: {
          renderValue: (code) => (
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
              <Flag language={code as string} />
              <span>{supportedLanguages[code as keyof typeof supportedLanguages]}</span>
            </Stack>
          ),
        },
      }}
    >
      {Object.entries(supportedLanguages).map(([code, name]) => (
        <MenuItem key={code} value={code}>
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
            <Flag language={code} />
            <span>{name}</span>
          </Stack>
        </MenuItem>
      ))}
    </TextField>
  )
}
