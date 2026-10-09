import ReviewIcon from '@mui/icons-material/RateReviewOutlined'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Link,
  MenuItem,
  Paper,
  Snackbar,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink } from 'react-router'
import { api, ApiError, type DraftStatus, type Paginated, type Reliability, type SystemDraft, type SystemDraftEvent } from '../../api'
import { WebRating } from '../../components/WebRating'
import { useOnConnect, useRealtimeEvent } from '../../realtime'

const MAX_BATCH = 20

// The lists the page shows, by the statuses they gather.
const VIEWS: Record<string, DraftStatus[]> = {
  review: ['ready'],
  progress: ['queued', 'running'],
  published: ['published'],
  closed: ['failed', 'discarded'],
}
type View = keyof typeof VIEWS

const viewOf = (status: DraftStatus) =>
  (Object.keys(VIEWS) as View[]).find((key) => VIEWS[key].includes(status)) ?? 'review'

const RELIABILITY_COLOR: Record<Reliability, 'success' | 'warning' | 'error'> = {
  high: 'success',
  medium: 'warning',
  low: 'error',
}

function RequestForm({ onQueued }: { onQueued: (drafts: SystemDraft[]) => void }) {
  const { t } = useTranslation()
  const [mode, setMode] = useState<'dishes' | 'theme'>('dishes')
  const [dishes, setDishes] = useState('')
  const [theme, setTheme] = useState('')
  const [count, setCount] = useState(5)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const names = dishes.split('\n').map((d) => d.trim()).filter(Boolean)
  const valid = mode === 'dishes' ? names.length > 0 && names.length <= MAX_BATCH : theme.trim() !== ''

  async function send() {
    setBusy(true)
    setError(null)
    try {
      const body = mode === 'dishes' ? { dishes: names } : { theme: theme.trim(), count }
      onQueued(await api<SystemDraft[]>('/system-drafts/', { method: 'POST', body: JSON.stringify(body) }))
      setDishes('')
      setTheme('')
    } catch (e) {
      setError(e instanceof ApiError && e.status === 503 ? t('drafts.modelDown') : t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={2}>
        <Typography variant="h3">{t('drafts.request')}</Typography>
        <Tabs value={mode} onChange={(_, value) => setMode(value)}>
          <Tab value="dishes" label={t('drafts.byName')} />
          <Tab value="theme" label={t('drafts.byTheme')} />
        </Tabs>
        {mode === 'dishes' ? (
          <TextField multiline minRows={3} value={dishes} onChange={(e) => setDishes(e.target.value)}
            label={t('drafts.dishes')} placeholder={t('drafts.dishesPlaceholder')}
            helperText={t('drafts.dishesHint', { max: MAX_BATCH })} error={names.length > MAX_BATCH} />
        ) : (
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <TextField fullWidth value={theme} onChange={(e) => setTheme(e.target.value)}
              label={t('drafts.theme')} placeholder={t('drafts.themePlaceholder')} helperText={t('drafts.themeHint')} />
            <TextField select value={count} onChange={(e) => setCount(Number(e.target.value))}
              label={t('drafts.count')} sx={{ minWidth: 120 }}>
              {[3, 5, 10, 15, 20].map((n) => <MenuItem key={n} value={n}>{n}</MenuItem>)}
            </TextField>
          </Stack>
        )}
        {error && <Alert severity="error">{error}</Alert>}
        <Box>
          <Button variant="contained" onClick={() => void send()} disabled={busy || !valid}>
            {busy && mode === 'theme' ? t('drafts.thinking') : t('drafts.queue')}
          </Button>
        </Box>
      </Stack>
    </Paper>
  )
}

function DraftRow({ draft, phase, onChanged }: {
  draft: SystemDraft
  phase?: SystemDraftEvent
  onChanged: (draft: SystemDraft) => void
}) {
  const { t, i18n } = useTranslation()
  const [busy, setBusy] = useState(false)
  // Rewording the dish before trying again; null when not editing.
  const [rewording, setRewording] = useState<string | null>(null)

  async function act(action: 'discard' | 'retry' | 'restore', body?: object) {
    setBusy(true)
    try {
      onChanged(await api<SystemDraft>(`/system-drafts/${draft.id}/${action}/`, {
        method: 'POST',
        body: body ? JSON.stringify(body) : undefined,
      }))
      setRewording(null)
    } finally {
      setBusy(false)
    }
  }

  const running = draft.status === 'running' || draft.status === 'queued'
  return (
    <Stack spacing={1} sx={{ p: 2 }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 600, mr: 1 }}>
          {draft.draft?.title || draft.dish}
        </Typography>
        <Chip size="small" label={t(`drafts.status.${draft.status}`)} />
        {draft.reliability && (
          <Chip size="small" variant="outlined" color={RELIABILITY_COLOR[draft.reliability]}
            label={t(`drafts.reliability.${draft.reliability}`)} />
        )}
        <WebRating rating={draft.web_rating} count={draft.web_rating_count} />
        {running && <CircularProgress size={16} />}
        {running && phase && (
          <Typography variant="body2" color="text.secondary">{t(`drafts.phase.${phase.phase}`, { count: phase.sources ?? 0 })}</Typography>
        )}
      </Stack>
      {draft.draft?.title && draft.draft.title !== draft.dish && (
        <Typography variant="body2" color="text.secondary">{t('drafts.asked', { dish: draft.dish })}</Typography>
      )}
      {draft.sources.length > 0 ? (
        <Typography variant="body2" color="text.secondary">
          {t('drafts.sources')}:{' '}
          {draft.sources.map((source, index) => (
            <span key={source.url}>
              {index > 0 && ', '}
              <Link href={source.url} target="_blank" rel="noopener noreferrer">{source.site}</Link>
            </span>
          ))}
          {draft.agreement !== null && ` · ${t('drafts.agreement', { value: Math.round(draft.agreement * 100) })}`}
        </Typography>
      ) : draft.status === 'ready' && (
        <Typography variant="body2" color="error.main">{t('drafts.noSources')}</Typography>
      )}
      {draft.error && <Typography variant="body2" color="error.main" sx={{ overflowWrap: 'anywhere' }}>{draft.error}</Typography>}
      {rewording !== null && (
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ alignItems: { sm: 'flex-start' } }}>
          <TextField size="small" fullWidth autoFocus value={rewording} label={t('drafts.dish')}
            helperText={t('drafts.editRetryHint')} onChange={(e) => setRewording(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && rewording.trim()) void act('retry', { dish: rewording })
              if (e.key === 'Escape') setRewording(null)
            }}
            slotProps={{ htmlInput: { maxLength: 200 } }} />
          <Stack direction="row" spacing={1}>
            <Button variant="contained" disabled={busy || !rewording.trim()} onClick={() => void act('retry', { dish: rewording })}>
              {t('drafts.retry')}
            </Button>
            <Button color="inherit" onClick={() => setRewording(null)}>{t('common.cancel')}</Button>
          </Stack>
        </Stack>
      )}
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        {draft.status === 'ready' && (
          <Button size="small" variant="contained" startIcon={<ReviewIcon />} component={RouterLink} to={`/recipes/new?draft=${draft.id}`}>
            {t('drafts.review')}
          </Button>
        )}
        {draft.status === 'published' && draft.recipe && (
          <Button size="small" component={RouterLink} to={`/recipes/${draft.recipe}`}>{t('drafts.openRecipe')}</Button>
        )}
        {(draft.status === 'ready' || draft.status === 'failed' || draft.status === 'queued') && (
          <Button size="small" color="inherit" disabled={busy} onClick={() => void act('discard')}>{t('drafts.discard')}</Button>
        )}
        {(draft.status === 'failed' || draft.status === 'discarded') && rewording === null && (
          <Button size="small" disabled={busy} onClick={() => setRewording(draft.dish)}>{t('drafts.editRetry')}</Button>
        )}
        {draft.status === 'discarded' && draft.draft && rewording === null && (
          <Button size="small" color="inherit" disabled={busy} onClick={() => void act('restore')}>{t('drafts.restore')}</Button>
        )}
        <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>
          {draft.requested_by_name && `${draft.requested_by_name} · `}
          {new Date(draft.created_at).toLocaleString(i18n.resolvedLanguage, { dateStyle: 'short', timeStyle: 'short' })}
        </Typography>
      </Stack>
    </Stack>
  )
}

/** System recipe drafts, for staff: request them, follow the worker, review and publish. */
export function DraftsPage() {
  const { t } = useTranslation()
  const [view, setView] = useState<View>('review')
  const [drafts, setDrafts] = useState<SystemDraft[] | null>(null)
  const [counts, setCounts] = useState<Record<DraftStatus, number> | null>(null)
  const [phases, setPhases] = useState<Record<number, SystemDraftEvent>>({})
  const [message, setMessage] = useState<string | null>(null)

  const loadCounts = useCallback(() => {
    api<Record<DraftStatus, number>>('/system-drafts/counts/').then(setCounts).catch(() => undefined)
  }, [])

  const load = useCallback(
    () => api<Paginated<SystemDraft>>(`/system-drafts/?status=${VIEWS[view].join(',')}`)
      .then((page) => {
        setDrafts(page.results)
        return page.results
      })
      .catch(() => {
        setMessage(t('common.error'))
        return null
      }),
    [view, t],
  )

  useEffect(() => {
    void load()
    loadCounts()
  }, [load, loadCounts])
  useOnConnect(() => {
    void load()
    loadCounts()
  })

  /** A draft changed status. If it left the list shown and the list is now empty, follow it to
   * its new list; otherwise just refresh what is shown. */
  const moved = useCallback(async (id: number, status: DraftStatus) => {
    loadCounts()
    const shown = drafts?.some((d) => d.id === id)
    const stays = VIEWS[view].includes(status)
    if (!shown && !stays) return
    const remaining = await load()
    if (shown && !stays && remaining?.length === 0) setView(viewOf(status))
  }, [drafts, view, load, loadCounts])

  // The worker's phases arrive live, and so do the changes of status.
  useRealtimeEvent<SystemDraftEvent>('system_draft', (event) => {
    setPhases((all) => ({ ...all, [event.id]: event }))
    const shown = drafts?.find((d) => d.id === event.id)
    if (!shown || shown.status !== event.status) void moved(event.id, event.status)
  })

  const total = (key: View) => (counts ? VIEWS[key].reduce((sum, status) => sum + (counts[status] ?? 0), 0) : null)

  return (
    <Stack spacing={2}>
      <Typography variant="body2" color="text.secondary">{t('drafts.hint')}</Typography>
      <RequestForm onQueued={(queued) => {
        setMessage(t('drafts.queued', { count: queued.length }))
        setView('progress')
        loadCounts()
      }} />
      <Tabs value={view} onChange={(_, value) => setView(value)} variant="scrollable">
        {(Object.keys(VIEWS) as View[]).map((key) => (
          <Tab key={key} value={key} label={
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
              <span>{t(`drafts.view.${key}`)}</span>
              {total(key) !== null && (
                <Chip size="small" label={total(key)} color={key === 'review' && total(key) ? 'primary' : 'default'}
                  sx={{ height: 20, '& .MuiChip-label': { px: 0.75 } }} />
              )}
            </Stack>
          } />
        ))}
      </Tabs>
      {!drafts ? (
        <CircularProgress sx={{ display: 'block', mx: 'auto', mt: 2 }} />
      ) : drafts.length === 0 ? (
        <Typography color="text.secondary">{t('drafts.none')}</Typography>
      ) : (
        <Paper variant="outlined">
          {drafts.map((draft, index) => (
            <Box key={draft.id} sx={{ borderTop: index ? 1 : 0, borderColor: 'divider' }}>
              <DraftRow draft={draft} phase={phases[draft.id]}
                onChanged={(changed) => void moved(changed.id, changed.status)} />
            </Box>
          ))}
        </Paper>
      )}
      <Snackbar open={!!message} autoHideDuration={4000} onClose={() => setMessage(null)} message={message} />
    </Stack>
  )
}
