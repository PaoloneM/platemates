import { useTheme } from '@mui/material/styles'

// Same mark as the Keycloak login theme (keycloak/themes/mymenu/login/resources/img/logo.svg).
// Colours go through CSS variables so the mark follows the light/dark scheme.
export function Logo({ size = 56 }: { size?: number }) {
  const theme = useTheme()
  const bg = theme.vars?.palette.primary.main ?? theme.palette.primary.main
  const fg = theme.vars?.palette.primary.contrastText ?? theme.palette.primary.contrastText
  const line = { fill: 'none', stroke: fg, strokeWidth: 2.5, strokeLinecap: 'round' as const }
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} aria-hidden="true" style={{ flex: 'none' }}>
      <circle cx="32" cy="32" r="30" style={{ fill: bg }} />
      <circle cx="32" cy="32" r="17" style={{ fill: 'none', stroke: fg, strokeWidth: 3 }} />
      <path d="M14 14v12a4 4 0 0 0 4 4v20M18 14v10M22 14v12a4 4 0 0 1-4 4" style={line} />
      <path d="M48 50V14c-4 2-6 8-6 14s2 7 6 7" style={{ ...line, strokeLinejoin: 'round' }} />
    </svg>
  )
}
