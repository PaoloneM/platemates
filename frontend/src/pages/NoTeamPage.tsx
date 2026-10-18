import GroupAddIcon from '@mui/icons-material/GroupAddOutlined'
import MailIcon from '@mui/icons-material/MailOutlined'
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  IconButton,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import {
  api,
  ApiError,
  csrfToken,
  type AccessRequest,
  type PendingInvitation,
  type TeamRequest,
} from '../api'
import { useAuth } from '../auth/context'
import { AuthLayout } from '../components/AuthLayout'

// How often the page looks for answers (an owner accepting, a team created).
const REFRESH_MS = 30_000

type Ask = 'owner' | 'team'

/**
 * Signed in, but not in any team yet. Invitations sent to the user's address come first; then
 * two ways in: asking a team owner, by their email, to be let in, or asking the
 * administrators for a team of one's own. The page follows the answers and moves on as soon
 * as the user is in a team.
 */
export function NoTeamPage() {
  const { t } = useTranslation()
  const { me, refresh } = useAuth()
  const email = me?.authenticated ? me.user.email : ''
  const [invitations, setInvitations] = useState<PendingInvitation[]>([])
  const [access, setAccess] = useState<AccessRequest[]>([])
  const [teams, setTeams] = useState<TeamRequest[]>([])
  const [ask, setAsk] = useState<Ask>('owner')

  const load = useCallback(
    () =>
      Promise.all([
        api<PendingInvitation[]>('/invitations/mine/'),
        api<AccessRequest[]>('/access-requests/'),
        api<TeamRequest[]>('/team-requests/'),
      ]).then(([i, a, r]) => {
        setInvitations(i)
        setAccess(a)
        setTeams(r)
      }),
    [],
  )

  useEffect(() => {
    void load().catch(() => undefined)
    const timer = window.setInterval(() => {
      void refresh()
      void load().catch(() => undefined)
    }, REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [load, refresh])

  const waitingTeam = teams.some((r) => r.status === 'pending')

  return (
    <AuthLayout wide>
      <Typography variant="h1">{t('noTeam.title')}</Typography>
      <Typography>{t('noTeam.body', { email })}</Typography>

      {invitations.map((inv) => <InvitationCard key={inv.token} invitation={inv} />)}

      <Paper variant="outlined" sx={{ width: '100%', textAlign: 'left', borderRadius: 3 }}>
        <Tabs value={ask} onChange={(_, value: Ask) => setAsk(value)} variant="fullWidth">
          <Tab value="owner" icon={<MailIcon />} iconPosition="start" label={t('noTeam.askOwner.tab')} />
          <Tab value="team" icon={<GroupAddIcon />} iconPosition="start" label={t('noTeam.askTeam.tab')} />
        </Tabs>
        <Divider />
        <Box sx={{ p: 2 }}>
          {ask === 'owner'
            ? <AskOwner onSent={() => void load()} />
            : <AskTeam waiting={waitingTeam} onSent={() => void load()} />}
        </Box>
      </Paper>

      <MyRequests access={access} teams={teams} onChanged={() => void load()} />

      <form method="post" action="/oidc/logout/">
        <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken()} />
        <Button variant="text" color="inherit" type="submit">{t('auth.logout')}</Button>
      </form>
    </AuthLayout>
  )
}

function InvitationCard({ invitation }: { invitation: PendingInvitation }) {
  const { t } = useTranslation()
  const { refresh } = useAuth()
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  async function accept() {
    setBusy(true)
    try {
      await api(`/invitations/by-token/${encodeURIComponent(invitation.token)}/`, { method: 'POST' })
      await refresh()
    } catch {
      setFailed(true)
      setBusy(false)
    }
  }

  return (
    <Paper variant="outlined" sx={{ width: '100%', p: 2, borderRadius: 3, borderColor: 'primary.main' }}>
      <Stack spacing={1.5} sx={{ alignItems: 'center' }}>
        <Typography variant="h3">
          {invitation.invited_by_name
            ? t('auth.invitedBy', { name: invitation.invited_by_name, team: invitation.team_name })
            : t('auth.invitedTo', { team: invitation.team_name })}
        </Typography>
        {failed && <Alert severity="error">{t('invite.error.generic')}</Alert>}
        <Button variant="contained" onClick={() => void accept()} disabled={busy}>{t('invite.accept')}</Button>
      </Stack>
    </Paper>
  )
}

/** The error key for a refused request. */
function requestError(e: unknown): string {
  const body = e instanceof ApiError ? (e.body as { code?: string; owner_email?: string[] } | null) : null
  if (body?.code === 'too_many') return 'noTeam.error.tooMany'
  if (body?.code === 'already_pending') return 'noTeam.error.alreadyPending'
  if (body?.owner_email) return 'noTeam.error.badEmail'
  return 'common.error'
}

function AskOwner({ onSent }: { onSent: () => void }) {
  const { t } = useTranslation()
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState('')
  const [state, setState] = useState<{ sent?: string; error?: string }>({})
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      await api('/access-requests/', {
        method: 'POST',
        body: JSON.stringify({ owner_email: email.trim(), message: message.trim() }),
      })
      setState({ sent: email.trim() })
      setEmail('')
      setMessage('')
      onSent()
    } catch (e) {
      setState({ error: requestError(e) })
    }
    setBusy(false)
  }

  return (
    <Stack component="form" spacing={1.5} onSubmit={(e) => void submit(e)}>
      <Typography variant="body2" color="text.secondary">{t('noTeam.askOwner.hint')}</Typography>
      {state.sent && <Alert severity="success">{t('noTeam.askOwner.sent', { email: state.sent })}</Alert>}
      {state.error && <Alert severity="error">{t(state.error)}</Alert>}
      <TextField size="small" type="email" required label={t('noTeam.askOwner.email')} value={email}
        onChange={(e) => setEmail(e.target.value)} />
      <TextField size="small" multiline minRows={2} label={t('noTeam.message')} value={message}
        onChange={(e) => setMessage(e.target.value)} slotProps={{ htmlInput: { maxLength: 500 } }} />
      <Button type="submit" variant="contained" disabled={busy || !email.trim()} sx={{ alignSelf: 'flex-end' }}>
        {t('noTeam.askOwner.send')}
      </Button>
    </Stack>
  )
}

function AskTeam({ waiting, onSent }: { waiting: boolean; onSent: () => void }) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api('/team-requests/', {
        method: 'POST',
        body: JSON.stringify({ team_name: name.trim(), message: message.trim() }),
      })
      setName('')
      setMessage('')
      onSent()
    } catch (e) {
      setError(requestError(e))
    }
    setBusy(false)
  }

  if (waiting) return <Alert severity="info">{t('noTeam.askTeam.waiting')}</Alert>
  return (
    <Stack component="form" spacing={1.5} onSubmit={(e) => void submit(e)}>
      <Typography variant="body2" color="text.secondary">{t('noTeam.askTeam.hint')}</Typography>
      {error && <Alert severity="error">{t(error)}</Alert>}
      <TextField size="small" required label={t('noTeam.askTeam.name')} placeholder={t('noTeam.askTeam.namePlaceholder')}
        value={name} onChange={(e) => setName(e.target.value)} slotProps={{ htmlInput: { maxLength: 100 } }} />
      <TextField size="small" multiline minRows={2} label={t('noTeam.message')} value={message}
        onChange={(e) => setMessage(e.target.value)} slotProps={{ htmlInput: { maxLength: 500 } }} />
      <Button type="submit" variant="contained" disabled={busy || !name.trim()} sx={{ alignSelf: 'flex-end' }}>
        {t('noTeam.askTeam.send')}
      </Button>
    </Stack>
  )
}

/** What the user asked, and how it went; a waiting request can be withdrawn. */
function MyRequests({ access, teams, onChanged }: {
  access: AccessRequest[]
  teams: TeamRequest[]
  onChanged: () => void
}) {
  const { t } = useTranslation()
  if (access.length === 0 && teams.length === 0) return null

  async function withdraw(path: string) {
    await api(path, { method: 'DELETE' }).catch(() => undefined)
    onChanged()
  }

  const color = { pending: 'primary', accepted: 'success', handled: 'success', declined: 'default', dismissed: 'default' } as const
  const rows = [
    ...access.map((r) => ({
      key: `a${r.id}`,
      label: t('noTeam.mine.toOwner', { email: r.owner_email }),
      status: r.status,
      detail: r.team_name ? t('noTeam.mine.joined', { team: r.team_name }) : '',
      path: `/access-requests/${r.id}/`,
    })),
    ...teams.map((r) => ({
      key: `t${r.id}`,
      label: t('noTeam.mine.team', { team: r.team_name }),
      status: r.status,
      detail: r.created_team_name ? t('noTeam.mine.created', { team: r.created_team_name }) : '',
      path: `/team-requests/${r.id}/`,
    })),
  ]

  return (
    <Stack spacing={1} sx={{ width: '100%', textAlign: 'left' }}>
      <Typography variant="h3">{t('noTeam.mine.title')}</Typography>
      {rows.map((row) => (
        <Stack key={row.key} direction="row" spacing={1} sx={{ alignItems: 'center' }}>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>{row.label}</Typography>
            {row.detail && <Typography variant="caption" color="text.secondary">{row.detail}</Typography>}
          </Box>
          <Chip size="small" variant="outlined" color={color[row.status]} label={t(`noTeam.mine.status.${row.status}`)} />
          {row.status === 'pending' && (
            <Tooltip title={t('noTeam.mine.withdraw')}>
              <IconButton size="small" onClick={() => void withdraw(row.path)}><CloseIcon fontSize="small" /></IconButton>
            </Tooltip>
          )}
        </Stack>
      ))}
    </Stack>
  )
}
