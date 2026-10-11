import { Box } from '@mui/material'
import { useColorScheme } from '@mui/material/styles'
import { useTranslation } from 'react-i18next'
import { Navigate } from 'react-router'
import { useAuth } from '../auth/context'
import { hasMonitoring } from '../monitoring'

/**
 * Grafana's dashboards (VM, containers, traffic, database and backups, Keycloak, AI usage),
 * embedded in the whole page below the app bar. Same origin, and Grafana signs in silently with
 * the Keycloak session the app already has.
 */
export function MonitoringPage() {
  const { t } = useTranslation()
  const { me } = useAuth()
  const { mode, systemMode } = useColorScheme()
  if (!me?.authenticated || !hasMonitoring(me.user.is_admin)) return <Navigate to="/" replace />
  const theme = (mode === 'system' ? systemMode : mode) === 'dark' ? 'dark' : 'light'
  return (
    <Box component="iframe" title={t('monitoring.title')}
      src={`/grafana/dashboards?tag=platemates&theme=${theme}`}
      sx={{ display: 'block', width: '100%', height: '100%', border: 0 }} />
  )
}
