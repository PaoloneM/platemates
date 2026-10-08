import DeleteSweepIcon from '@mui/icons-material/DeleteSweepOutlined'
import RefreshIcon from '@mui/icons-material/Refresh'
import { Alert, Button, CircularProgress, Grid, Paper, Snackbar, Stack, Typography } from '@mui/material'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type CacheStats } from '../../api'

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <Stack spacing={0.25}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h3" sx={{ fontVariantNumeric: 'tabular-nums' }}>{value}</Typography>
    </Stack>
  )
}

function Panel({ title, hint, children }: { title: string; hint: string; children: React.ReactNode }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, height: '100%' }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{title}</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>{hint}</Typography>
      <Grid container spacing={2}>{children}</Grid>
    </Paper>
  )
}

const rate = (hits: number, misses: number) =>
  hits + misses ? `${Math.round((100 * hits) / (hits + misses))}%` : '—'

/** The cache of rules and settings, for administrators: figures and a button to empty it. */
export function CachePage() {
  const { t, i18n } = useTranslation()
  const [stats, setStats] = useState<CacheStats | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const number = (n: number | null | undefined) => (n === null || n === undefined ? '—' : n.toLocaleString(i18n.resolvedLanguage))
  const duration = (seconds: number | null) => {
    if (seconds === null || seconds === undefined) return '—'
    if (seconds < 120) return t('cache.seconds', { count: seconds })
    if (seconds < 7200) return t('cache.minutes', { count: Math.round(seconds / 60) })
    if (seconds < 172800) return t('cache.hours', { count: Math.round(seconds / 3600) })
    return t('cache.days', { count: Math.round(seconds / 86400) })
  }

  const load = useCallback(() => api<CacheStats>('/cache/').then(setStats).catch(() => setMessage(t('common.error'))), [t])
  useEffect(() => void load(), [load])

  async function clear() {
    if (!window.confirm(t('cache.clearConfirm'))) return
    setBusy(true)
    try {
      setStats(await api<CacheStats>('/cache/clear/', { method: 'POST' }))
      setMessage(t('cache.cleared'))
    } catch {
      setMessage(t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  if (!stats) return <CircularProgress sx={{ display: 'block', mx: 'auto', mt: 4 }} />
  const { shared, process } = stats
  const cleared = stats.last_cleared
  return (
    <Stack spacing={2}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ alignItems: { sm: 'flex-start' }, justifyContent: 'space-between' }}>
        <Typography variant="body2" color="text.secondary">{t('cache.hint')}</Typography>
        <Stack direction="row" spacing={1} sx={{ flex: 'none' }}>
          <Button startIcon={<RefreshIcon />} onClick={() => void load()} disabled={busy}>{t('cache.refresh')}</Button>
          <Button variant="contained" color="secondary" startIcon={<DeleteSweepIcon />} onClick={() => void clear()} disabled={busy}>
            {t('cache.clear')}
          </Button>
        </Stack>
      </Stack>
      {!shared.available && <Alert severity="warning">{t('cache.redisDown')}{shared.error && ` (${shared.error})`}</Alert>}
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 6 }}>
          <Panel title={t('cache.shared')} hint={t('cache.sharedHint', { ttl: duration(stats.timeouts.shared_seconds) })}>
            <Grid size={6}><Figure label={t('cache.keys')} value={number(shared.keys)} /></Grid>
            <Grid size={6}><Figure label={t('cache.memory')} value={shared.used_memory ? `${shared.used_memory}${shared.max_memory ? ` / ${shared.max_memory}` : ''}` : '—'} /></Grid>
            <Grid size={6}><Figure label={t('cache.hitRate')} value={rate(shared.hits ?? 0, shared.misses ?? 0)} /></Grid>
            <Grid size={6}><Figure label={t('cache.hitsMisses')} value={`${number(shared.hits)} / ${number(shared.misses)}`} /></Grid>
            <Grid size={6}><Figure label={t('cache.uptime')} value={duration(shared.uptime_seconds ?? null)} /></Grid>
            <Grid size={6}><Figure label={t('cache.version')} value={shared.version ?? '—'} /></Grid>
          </Panel>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Panel title={t('cache.process')} hint={t('cache.processHint', { ttl: duration(stats.timeouts.memory_seconds) })}>
            <Grid size={6}><Figure label={t('cache.memoryHits')} value={number(process.memory_hits)} /></Grid>
            <Grid size={6}><Figure label={t('cache.sharedHits')} value={number(process.shared_hits)} /></Grid>
            <Grid size={6}><Figure label={t('cache.loads')} value={number(process.misses)} /></Grid>
            <Grid size={6}><Figure label={t('cache.errors')} value={number(process.errors)} /></Grid>
          </Panel>
        </Grid>
      </Grid>
      <Typography variant="body2" color="text.secondary">
        {cleared
          ? t('cache.lastCleared', {
              date: new Date(cleared.at).toLocaleString(i18n.resolvedLanguage, { dateStyle: 'medium', timeStyle: 'short' }),
              by: cleared.by.startsWith('automatic: ') ? t('cache.automatic') : cleared.by || '—',
            })
          : t('cache.neverCleared')}
      </Typography>
      <Snackbar open={!!message} autoHideDuration={4000} onClose={() => setMessage(null)} message={message} />
    </Stack>
  )
}
