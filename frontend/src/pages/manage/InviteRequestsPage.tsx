import {
  Alert,
  Button,
  Chip,
  CircularProgress,
  Link,
  Paper,
  Stack,
  Tab,
  Tabs,
  Typography,
} from '@mui/material'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type InviteRequest, type Paginated } from '../../api'

type Filter = 'pending' | 'all'

/**
 * For administrators: who asked for an invitation from the sign-in page. Inviting happens
 * outside this page (a team's invitation link, or a new team): here a request is marked as
 * dealt with, or dismissed.
 */
export function InviteRequestsPage() {
  const { t, i18n } = useTranslation()
  const [filter, setFilter] = useState<Filter>('pending')
  const [requests, setRequests] = useState<InviteRequest[] | null>(null)
  const [error, setError] = useState(false)

  const load = useCallback(() => {
    const query = filter === 'pending' ? '?status=pending' : ''
    return api<Paginated<InviteRequest>>(`/invite-requests/${query}`)
      .then((page) => setRequests(page.results))
      .catch(() => setError(true))
  }, [filter])
  useEffect(() => void load(), [load])

  async function set(request: InviteRequest, status: InviteRequest['status']) {
    await api(`/invite-requests/${request.id}/`, { method: 'PATCH', body: JSON.stringify({ status }) })
    void load()
  }

  const when = (iso: string) =>
    new Intl.DateTimeFormat(i18n.resolvedLanguage, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(iso))

  return (
    <Stack spacing={2}>
      <Typography color="text.secondary">{t('inviteRequests.hint')}</Typography>
      <Tabs value={filter} onChange={(_, value: Filter) => { setRequests(null); setFilter(value) }}>
        <Tab value="pending" label={t('inviteRequests.pending')} />
        <Tab value="all" label={t('inviteRequests.all')} />
      </Tabs>
      {error && <Alert severity="error">{t('common.error')}</Alert>}
      {!requests ? <CircularProgress /> : requests.length === 0 ? (
        <Typography color="text.secondary">{t('inviteRequests.none')}</Typography>
      ) : requests.map((r) => (
        <Paper key={r.id} variant="outlined" sx={{ p: 2 }}>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ alignItems: { sm: 'flex-start' } }}>
            <Stack spacing={0.5} sx={{ flex: 1, minWidth: 0 }}>
              <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
                <Link href={`mailto:${r.email}`} sx={{ fontWeight: 600, overflowWrap: 'anywhere' }}>{r.email}</Link>
                {r.name && <Typography>{r.name}</Typography>}
                {r.language && <Chip size="small" variant="outlined" label={r.language.toUpperCase()} />}
                {r.status !== 'pending' && <Chip size="small" label={t(`inviteRequests.status.${r.status}`)} />}
              </Stack>
              {r.message && <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{r.message}</Typography>}
              <Typography variant="caption" color="text.secondary">
                {when(r.created_at)}
                {r.handled_at && ` · ${t('inviteRequests.handledBy', { who: r.handled_by_name ?? '—', when: when(r.handled_at) })}`}
              </Typography>
            </Stack>
            <Stack direction="row" spacing={1} sx={{ flexShrink: 0 }}>
              {r.status === 'pending' ? (
                <>
                  <Button size="small" color="inherit" onClick={() => void set(r, 'dismissed')}>{t('inviteRequests.dismiss')}</Button>
                  <Button size="small" variant="contained" onClick={() => void set(r, 'handled')}>{t('inviteRequests.handle')}</Button>
                </>
              ) : (
                <Button size="small" onClick={() => void set(r, 'pending')}>{t('inviteRequests.reopen')}</Button>
              )}
            </Stack>
          </Stack>
        </Paper>
      ))}
    </Stack>
  )
}
