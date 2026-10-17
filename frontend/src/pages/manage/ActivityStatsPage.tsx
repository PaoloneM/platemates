import {
  Alert,
  CircularProgress,
  Grid,
  LinearProgress,
  Link,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink } from 'react-router'
import { api, type AuditStats } from '../../api'

function Figure({ label, value, children }: { label: string; value: string; children?: React.ReactNode }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, height: '100%' }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h3" sx={{ fontVariantNumeric: 'tabular-nums' }}>{value}</Typography>
      {children}
    </Paper>
  )
}

/** For administrators: how big the teams' activity log is, and which teams fill it. */
export function ActivityStatsPage() {
  const { t, i18n } = useTranslation()
  const [stats, setStats] = useState<AuditStats | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    api<AuditStats>('/audit-stats/').then(setStats).catch(() => setError(true))
  }, [])

  const lang = i18n.resolvedLanguage
  const number = (n: number) => n.toLocaleString(lang)
  const size = (bytes: number) => {
    const units = ['B', 'kB', 'MB', 'GB']
    let value = bytes
    let unit = 0
    while (value >= 1024 && unit < units.length - 1) {
      value /= 1024
      unit += 1
    }
    return `${value.toLocaleString(lang, { maximumFractionDigits: unit ? 1 : 0 })} ${units[unit]}`
  }
  const when = (iso: string) =>
    new Intl.DateTimeFormat(lang, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(iso))

  if (error) return <Alert severity="error">{t('common.error')}</Alert>
  if (!stats) return <CircularProgress />
  const fill = Math.min(100, (100 * stats.total_events) / stats.max_events)

  return (
    <Stack spacing={2}>
      <Typography color="text.secondary">
        {t('activityStats.hint', { days: stats.retention_days, max: number(stats.max_events) })}{' '}
        <Link component={RouterLink} to="/manage/settings">{t('activityStats.settingsLink')}</Link>
      </Typography>
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 4 }}>
          <Figure label={t('activityStats.events')} value={number(stats.total_events)}>
            <LinearProgress variant="determinate" value={fill} sx={{ mt: 1, borderRadius: 1 }} />
            <Typography variant="caption" color="text.secondary">
              {t('activityStats.fill', { percent: Math.round(fill), max: number(stats.max_events) })}
            </Typography>
          </Figure>
        </Grid>
        <Grid size={{ xs: 12, sm: 4 }}>
          <Figure label={t('activityStats.storage')} value={size(stats.table_bytes)} />
        </Grid>
        <Grid size={{ xs: 12, sm: 4 }}>
          <Figure label={t('activityStats.oldest')} value={stats.oldest ? when(stats.oldest) : '—'} />
        </Grid>
      </Grid>
      <Paper variant="outlined" sx={{ overflowX: 'auto' }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t('activityStats.team')}</TableCell>
              <TableCell align="right">{t('activityStats.operations')}</TableCell>
              <TableCell>{t('activityStats.last')}</TableCell>
              <TableCell align="right">{t('activityStats.teamStorage')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {stats.teams.length === 0 && (
              <TableRow><TableCell colSpan={4}><Typography color="text.secondary">{t('activityStats.none')}</Typography></TableCell></TableRow>
            )}
            {stats.teams.map((row) => (
              <TableRow key={row.team}>
                <TableCell>{row.name}</TableCell>
                <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>{number(row.events)}</TableCell>
                <TableCell>{when(row.last)}</TableCell>
                <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>{size(row.bytes)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
      <Typography variant="caption" color="text.secondary">{t('activityStats.storageNote')}</Typography>
    </Stack>
  )
}
