import DarkIcon from '@mui/icons-material/DarkModeOutlined'
import LightIcon from '@mui/icons-material/LightModeOutlined'
import PaletteIcon from '@mui/icons-material/PaletteOutlined'
import SystemIcon from '@mui/icons-material/SettingsBrightnessOutlined'
import { ListItemIcon, Stack, ToggleButton, ToggleButtonGroup, Tooltip } from '@mui/material'
import { useColorScheme } from '@mui/material/styles'
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type ThemeChoice } from '../api'
import { useAuth } from '../auth/context'

// Light, dark, or "system" (the device's own setting, which can change during the day). The
// choice is a per-user preference saved by the backend, like the language, so it follows the
// user across devices; MUI also keeps it in the browser, so the next visit starts right.

const MODES: { mode: ThemeChoice; icon: React.JSX.Element }[] = [
  { mode: 'light', icon: <LightIcon fontSize="small" /> },
  { mode: 'system', icon: <SystemIcon fontSize="small" /> },
  { mode: 'dark', icon: <DarkIcon fontSize="small" /> },
]

/** Applies the signed-in user's saved theme. Renders nothing. */
export function ThemeSync() {
  const { me } = useAuth()
  const { setMode } = useColorScheme()
  const saved = me?.authenticated ? me.user.theme : null
  useEffect(() => {
    if (saved) setMode(saved)
  }, [saved, setMode])
  return null
}

/** The theme switch of the user menu. */
export function ThemeModeSwitch() {
  const { t } = useTranslation()
  const { mode, setMode } = useColorScheme()

  function choose(value: ThemeChoice | null) {
    if (!value) return
    setMode(value)
    void api('/me/', { method: 'PATCH', body: JSON.stringify({ theme: value }) }).catch(() => {
      // A failed save only means the choice is not remembered on other devices.
    })
  }

  return (
    // Laid out as a menu item: the icon in the same column as the flags and the other icons.
    <Stack direction="row" sx={{ px: 2, py: 0.75, alignItems: 'center' }}>
      <ListItemIcon>
        <Tooltip title={t('shell.theme')}>
          <PaletteIcon fontSize="small" />
        </Tooltip>
      </ListItemIcon>
      <ToggleButtonGroup size="small" exclusive value={mode ?? 'system'} onChange={(_, value) => choose(value)}
        aria-label={t('shell.theme')}>
        {MODES.map(({ mode: value, icon }) => (
          <Tooltip key={value} title={t(`shell.mode.${value}`)}>
            <ToggleButton value={value} aria-label={t(`shell.mode.${value}`)}>{icon}</ToggleButton>
          </Tooltip>
        ))}
      </ToggleButtonGroup>
    </Stack>
  )
}
