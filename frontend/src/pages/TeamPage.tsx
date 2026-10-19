import AddIcon from '@mui/icons-material/Add'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import DeleteIcon from '@mui/icons-material/DeleteOutlined'
import EditIcon from '@mui/icons-material/EditOutlined'
import ShareIcon from '@mui/icons-material/IosShare'
import LogoutIcon from '@mui/icons-material/Logout'
import MailIcon from '@mui/icons-material/MailOutlined'
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Grid,
  IconButton,
  InputAdornment,
  List,
  ListItem,
  ListItemText,
  MenuItem,
  Snackbar,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router'
import {
  api,
  ApiError,
  type Invitation,
  type KitchenTool,
  type Paginated,
  type Person,
  type ReceivedAccessRequest,
  type Role,
  type TeamMembership,
  type TeamProfile,
} from '../api'
import { useAuth } from '../auth/context'
import { TeamActivity } from '../components/TeamActivity'
import { Section } from '../components/Section'
import { useLabels } from '../labels'
import { useTeam } from '../team'

const CURRENT_YEAR = new Date().getFullYear()

const inviteUrl = (token: string) => `${window.location.origin}/invite/${token}`

// -- profile ----------------------------------------------------------------------------------

function ProfileSection({ team, owner, onSaved }: {
  team: TeamProfile
  owner: boolean
  onSaved: (team: TeamProfile) => void
}) {
  const { t } = useTranslation()
  const labels = useLabels()
  const [name, setName] = useState(team.name)
  const [minutes, setMinutes] = useState(team.max_weekday_minutes?.toString() ?? '')
  const [allTools, setAllTools] = useState<KitchenTool[]>([])
  const [tools, setTools] = useState<KitchenTool[]>([])
  const [sign, setSign] = useState(team.sign_shared_recipes)
  const [layout, setLayout] = useState(team.menu_layout)
  const { refresh } = useAuth()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api<KitchenTool[]>('/kitchen-tools/').then((all) => {
      setAllTools(all)
      setTools(all.filter((tool) => team.tools.includes(tool.id)))
    })
  }, [team.tools])

  async function save() {
    setBusy(true)
    setError(null)
    try {
      onSaved(
        await api<TeamProfile>(`/teams/${team.id}/`, {
          method: 'PATCH',
          body: JSON.stringify({
            name,
            max_weekday_minutes: minutes ? Number(minutes) : null,
            tools: tools.map((tool) => tool.id),
            sign_shared_recipes: sign,
            menu_layout: layout,
          }),
        }),
      )
      // The menu screen follows the team's layout from /me.
      void refresh()
    } catch {
      setError(t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Section title={t('team.profile.title')} hint={t('team.profile.hint')}
      action={owner && <Button variant="contained" onClick={() => void save()} disabled={busy || !name.trim()}>{t('common.save')}</Button>}>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      <Grid container spacing={2}>
        <Grid size={12}>
          <TextField label={t('team.profile.name')} value={name} disabled={!owner}
            onChange={(e) => setName(e.target.value)} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6 }}>
          <TextField label={t('team.profile.maxMinutes')} type="number" value={minutes} disabled={!owner}
            onChange={(e) => setMinutes(e.target.value)} helperText={t('team.profile.maxMinutesHint')}
            slotProps={{ htmlInput: { min: 0 }, input: { endAdornment: <InputAdornment position="end">min</InputAdornment> } }} />
        </Grid>
        <Grid size={12}>
          <Autocomplete
            multiple
            disabled={!owner}
            options={[...allTools].sort((a, b) => labels.tool(a).localeCompare(labels.tool(b)))}
            value={tools}
            getOptionLabel={(o) => labels.tool(o)}
            isOptionEqualToValue={(a, b) => a.id === b.id}
            onChange={(_, v) => setTools(v)}
            renderInput={(params) => (
              <TextField {...params} label={t('team.profile.tools')} helperText={t('team.profile.toolsHint')}
                // Tools arrive after the first render: keep the label out of the chips' way.
                slotProps={{ ...params.slotProps, inputLabel: { ...params.slotProps?.inputLabel, shrink: tools.length > 0 || undefined } }} />
            )}
          />
        </Grid>
        <Grid size={12}>
          <FormControlLabel disabled={!owner}
            control={<Switch checked={sign} onChange={(e) => setSign(e.target.checked)} />}
            label={t('team.profile.signRecipes')} />
          <Typography variant="body2" color="text.secondary">
            {sign ? t('team.profile.signedHint', { name }) : t('team.profile.anonymousHint')}
          </Typography>
        </Grid>
        <Grid size={{ xs: 12, sm: 6 }}>
          <TextField select label={t('team.profile.menuLayout')} value={layout} disabled={!owner}
            onChange={(e) => setLayout(e.target.value as TeamProfile['menu_layout'])}
            helperText={t('team.profile.menuLayoutHint')}>
            <MenuItem value="">{t('team.profile.menuLayoutDefault')}</MenuItem>
            <MenuItem value="vertical">{t('calendar.layout.vertical')}</MenuItem>
            <MenuItem value="horizontal">{t('calendar.layout.horizontal')}</MenuItem>
          </TextField>
        </Grid>
      </Grid>
    </Section>
  )
}

// -- people at the table ----------------------------------------------------------------------

function PersonDialog({ team, person, onClose, onSaved }: {
  team: number
  person: Person | null
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useTranslation()
  const [name, setName] = useState(person?.name ?? '')
  const [year, setYear] = useState(person?.birth_year?.toString() ?? '')
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true)
    await api(person ? `/members/${person.id}/` : '/members/', {
      method: person ? 'PATCH' : 'POST',
      body: JSON.stringify({ team, name: name.trim(), birth_year: year ? Number(year) : null }),
    })
    onSaved()
  }

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{person ? t('team.people.edit') : t('team.people.add')}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label={t('team.people.name')} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          <TextField label={t('team.people.birthYear')} type="number" value={year}
            onChange={(e) => setYear(e.target.value)} helperText={t('team.people.birthYearHint')}
            slotProps={{ htmlInput: { min: 1900, max: CURRENT_YEAR } }} />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="contained" onClick={() => void save()} disabled={busy || (!name.trim() && !year)}>
          {t('common.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

function PeopleSection({ team, owner, onChanged }: { team: TeamProfile; owner: boolean; onChanged: () => void }) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState<Person | 'new' | null>(null)

  return (
    <Section title={t('team.people.title')} hint={t('team.people.hint')}
      action={owner && <Button startIcon={<AddIcon />} onClick={() => setEditing('new')}>{t('team.people.add')}</Button>}>
      {team.members.length === 0 ? (
        <Typography color="text.secondary">{t('team.people.none')}</Typography>
      ) : (
        <List dense disablePadding>
          {team.members.map((p) => (
            <ListItem key={p.id} divider disableGutters
              secondaryAction={owner && (
                <>
                  <IconButton size="small" onClick={() => setEditing(p)} aria-label={t('common.edit')}><EditIcon fontSize="small" /></IconButton>
                  <IconButton size="small" aria-label={t('common.delete')}
                    onClick={() => void api(`/members/${p.id}/`, { method: 'DELETE' }).then(onChanged)}>
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </>
              )}>
              <ListItemText
                primary={p.name || t('team.people.unnamed')}
                secondary={p.birth_year ? t('team.people.age', { count: CURRENT_YEAR - p.birth_year, year: p.birth_year }) : undefined}
              />
            </ListItem>
          ))}
        </List>
      )}
      {editing && (
        <PersonDialog team={team.id} person={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)} onSaved={() => { setEditing(null); onChanged() }} />
      )}
    </Section>
  )
}

// -- users and roles --------------------------------------------------------------------------

function UsersSection({ team, owner, onMessage }: {
  team: TeamProfile
  owner: boolean
  onMessage: (message: string) => void
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { refresh } = useAuth()
  const [rows, setRows] = useState<TeamMembership[] | null>(null)
  const [leaving, setLeaving] = useState<TeamMembership | null>(null)

  const load = useCallback(
    () => api<Paginated<TeamMembership>>(`/memberships/?team=${team.id}`).then((page) => setRows(page.results)),
    [team.id],
  )
  useEffect(() => void load(), [load])

  async function setRole(row: TeamMembership, role: Role) {
    try {
      await api(`/memberships/${row.id}/`, { method: 'PATCH', body: JSON.stringify({ role }) })
      if (row.is_me) await refresh()
      void load()
    } catch {
      onMessage(t('team.users.lastOwner'))
    }
  }

  async function remove(row: TeamMembership) {
    try {
      await api(`/memberships/${row.id}/`, { method: 'DELETE' })
      setLeaving(null)
      if (row.is_me) {
        await refresh()
        navigate('/', { replace: true })
      } else void load()
    } catch (e) {
      setLeaving(null)
      onMessage(e instanceof ApiError && e.status === 409 ? t('team.users.lastOwner') : t('common.error'))
    }
  }

  return (
    <Section title={t('team.users.title')} hint={t('team.users.hint')}>
      {!rows ? <CircularProgress size={24} /> : (
        <List dense disablePadding>
          {rows.map((row) => (
            <ListItem key={row.id} divider disableGutters
              secondaryAction={
                <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                  {owner ? (
                    <TextField select size="small" value={row.role} fullWidth={false}
                      onChange={(e) => void setRole(row, e.target.value as Role)}>
                      <MenuItem value="owner">{t('team.role.owner')}</MenuItem>
                      <MenuItem value="member">{t('team.role.member')}</MenuItem>
                    </TextField>
                  ) : (
                    <Chip size="small" label={t(`team.role.${row.role}`)} />
                  )}
                  {row.is_me ? (
                    <Tooltip title={t('team.users.leave')}>
                      <IconButton size="small" onClick={() => setLeaving(row)}><LogoutIcon fontSize="small" /></IconButton>
                    </Tooltip>
                  ) : owner ? (
                    <Tooltip title={t('team.users.remove')}>
                      <IconButton size="small" onClick={() => setLeaving(row)}><DeleteIcon fontSize="small" /></IconButton>
                    </Tooltip>
                  ) : null}
                </Stack>
              }>
              <ListItemText
                primary={<>{row.name}{row.is_me && <Chip size="small" label={t('team.users.you')} sx={{ ml: 1 }} />}</>}
                secondary={row.email}
                sx={{ pr: 22 }}
              />
            </ListItem>
          ))}
        </List>
      )}
      {leaving && (
        <Dialog open onClose={() => setLeaving(null)}>
          <DialogTitle>
            {leaving.is_me ? t('team.users.leaveTitle', { team: team.name }) : t('team.users.removeTitle', { name: leaving.name })}
          </DialogTitle>
          <DialogContent>
            <Typography>{leaving.is_me ? t('team.users.leaveHint') : t('team.users.removeHint')}</Typography>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setLeaving(null)}>{t('common.cancel')}</Button>
            <Button color="error" variant="contained" onClick={() => void remove(leaving)}>
              {leaving.is_me ? t('team.users.leave') : t('team.users.remove')}
            </Button>
          </DialogActions>
        </Dialog>
      )}
    </Section>
  )
}

// -- invitations ------------------------------------------------------------------------------

function InvitationsSection({ team, owner, onMessage }: {
  team: TeamProfile
  owner: boolean
  onMessage: (message: string) => void
}) {
  const { t, i18n } = useTranslation()
  const [rows, setRows] = useState<Invitation[] | null>(null)
  const [role, setRole] = useState<Role>('member')
  const [note, setNote] = useState('')
  const [email, setEmail] = useState('')
  const [created, setCreated] = useState<Invitation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const dateFormat = new Intl.DateTimeFormat(i18n.resolvedLanguage, { day: 'numeric', month: 'short' })

  const load = useCallback(
    () => api<Paginated<Invitation>>(`/invitations/?team=${team.id}`).then((page) => setRows(page.results)),
    [team.id],
  )
  useEffect(() => void load(), [load])

  // With an address, PlateMates emails the invitation; without, it is a link to hand out.
  async function create() {
    setError(null)
    try {
      const invitation = await api<Invitation>('/invitations/', {
        method: 'POST',
        body: JSON.stringify({ team: team.id, role, note: note.trim(), email: email.trim() }),
      })
      setCreated(invitation)
      setNote('')
      setEmail('')
      void load()
    } catch (e) {
      setError(inviteError(e))
    }
  }

  async function resend(invitation: Invitation) {
    try {
      const { email_sent } = await api<{ email_sent: boolean }>(`/invitations/${invitation.id}/resend/`, { method: 'POST' })
      onMessage(email_sent ? t('team.invites.emailSent', { email: invitation.email }) : t('team.invites.emailFailed'))
    } catch (e) {
      onMessage(t(inviteError(e)))
    }
  }

  function inviteError(e: unknown) {
    const body = e instanceof ApiError ? (e.body as { code?: string; email?: string[] } | null) : null
    if (body?.code === 'too_many') return 'team.invites.tooMany'
    if (body?.email) return 'team.invites.badEmail'
    return 'common.error'
  }

  async function copy(token: string) {
    try {
      await navigator.clipboard.writeText(inviteUrl(token))
      onMessage(t('team.invites.copied'))
    } catch {
      onMessage(inviteUrl(token))
    }
  }

  // The phone's share sheet (WhatsApp, Messages, mail...) where available, else the clipboard.
  async function share(token: string) {
    if (navigator.share) {
      await navigator.share({ title: 'PlateMates', text: t('team.invites.shareText', { team: team.name }), url: inviteUrl(token) })
        .catch(() => undefined)
    } else void copy(token)
  }

  const stateColor = { pending: 'primary', accepted: 'success', expired: 'default', revoked: 'default' } as const

  return (
    <Section title={t('team.invites.title')} hint={owner ? t('team.invites.hint') : t('team.invites.memberHint')}>
      {owner && (
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mb: 2 }}>
          <TextField size="small" label={t('team.invites.note')} placeholder={t('team.invites.notePlaceholder')}
            value={note} onChange={(e) => setNote(e.target.value)} />
          <TextField size="small" type="email" label={t('team.invites.email')} placeholder={t('team.invites.emailPlaceholder')}
            value={email} onChange={(e) => setEmail(e.target.value)} />
          <TextField size="small" select label={t('team.invites.role')} value={role} fullWidth={false}
            onChange={(e) => setRole(e.target.value as Role)} sx={{ minWidth: 160 }}>
            <MenuItem value="member">{t('team.role.member')}</MenuItem>
            <MenuItem value="owner">{t('team.role.owner')}</MenuItem>
          </TextField>
          <Button variant="contained" startIcon={email.trim() ? <MailIcon /> : <AddIcon />} onClick={() => void create()} sx={{ flex: 'none' }}>
            {email.trim() ? t('team.invites.send') : t('team.invites.create')}
          </Button>
        </Stack>
      )}
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{t(error)}</Alert>}
      {created?.email && (
        <Alert severity={created.email_sent ? 'success' : 'warning'} sx={{ mb: 2 }} onClose={() => setCreated(null)}>
          {created.email_sent
            ? t('team.invites.emailSent', { email: created.email })
            : t('team.invites.emailFailed')}
        </Alert>
      )}
      {created?.token && !created.email && (
        <Alert severity="success" sx={{ mb: 2 }}
          action={
            <Stack direction="row">
              <IconButton size="small" color="inherit" onClick={() => void copy(created.token!)} aria-label={t('team.invites.copy')}><ContentCopyIcon fontSize="small" /></IconButton>
              <IconButton size="small" color="inherit" onClick={() => void share(created.token!)} aria-label={t('team.invites.share')}><ShareIcon fontSize="small" /></IconButton>
            </Stack>
          }>
          {t('team.invites.created')}
          <Box component="code" sx={{ display: 'block', mt: 0.5, wordBreak: 'break-all', fontSize: 13 }}>
            {inviteUrl(created.token)}
          </Box>
        </Alert>
      )}
      {!rows ? <CircularProgress size={24} /> : rows.length === 0 ? (
        <Typography color="text.secondary">{t('team.invites.none')}</Typography>
      ) : (
        <List dense disablePadding>
          {rows.map((inv) => (
            <ListItem key={inv.id} divider disableGutters
              secondaryAction={owner && inv.state === 'pending' && inv.token && (
                <>
                  {inv.email && (
                    <Tooltip title={t('team.invites.resend')}>
                      <IconButton size="small" onClick={() => void resend(inv)}><MailIcon fontSize="small" /></IconButton>
                    </Tooltip>
                  )}
                  <Tooltip title={t('team.invites.copy')}>
                    <IconButton size="small" onClick={() => void copy(inv.token!)}><ContentCopyIcon fontSize="small" /></IconButton>
                  </Tooltip>
                  <Tooltip title={t('team.invites.share')}>
                    <IconButton size="small" onClick={() => void share(inv.token!)}><ShareIcon fontSize="small" /></IconButton>
                  </Tooltip>
                  <Tooltip title={t('team.invites.revoke')}>
                    <IconButton size="small" onClick={() => void api(`/invitations/${inv.id}/`, { method: 'DELETE' }).then(load)}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </>
              )}>
              <ListItemText
                sx={{ pr: owner ? (inv.email ? 18 : 14) : 0 }}
                primary={
                  <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
                    <span>{inv.note || inv.email || t('team.invites.untitled')}</span>
                    {inv.note && inv.email && <Typography variant="body2" color="text.secondary" component="span">{inv.email}</Typography>}
                    <Chip size="small" color={stateColor[inv.state]} variant="outlined" label={t(`team.invites.state.${inv.state}`)} />
                    {inv.role === 'owner' && <Chip size="small" label={t('team.role.owner')} />}
                    {inv.requested && <Chip size="small" variant="outlined" label={t('team.invites.requested')} />}
                  </Stack>
                }
                secondary={
                  inv.state === 'accepted' && inv.accepted_by_name
                    ? t('team.invites.acceptedBy', { name: inv.accepted_by_name, date: dateFormat.format(new Date(inv.accepted_at!)) })
                    : t('team.invites.createdOn', { date: dateFormat.format(new Date(inv.created_at)), until: dateFormat.format(new Date(inv.expires_at)) })
                }
              />
            </ListItem>
          ))}
        </List>
      )}
    </Section>
  )
}

// -- access requests --------------------------------------------------------------------------

/** Requests from people who asked the signed-in owner, by email, to be let in: accepting one
 * adds them to the team on screen. Shown only when there are some. */
function AccessRequestsSection({ team, onMessage, onAccepted }: {
  team: TeamProfile
  onMessage: (message: string) => void
  onAccepted: () => void
}) {
  const { t, i18n } = useTranslation()
  const [rows, setRows] = useState<ReceivedAccessRequest[]>([])
  const dateFormat = new Intl.DateTimeFormat(i18n.resolvedLanguage, { day: 'numeric', month: 'short' })

  const location = useLocation()
  const load = useCallback(() => api<ReceivedAccessRequest[]>('/access-requests/received/').then(setRows), [])
  useEffect(() => void load().catch(() => undefined), [load])
  // The email's link, /team#requests, lands here once the requests are on screen.
  const shown = rows.length > 0
  useEffect(() => {
    if (shown && location.hash === '#requests') document.getElementById('requests')?.scrollIntoView()
  }, [shown, location.hash])

  async function answer(request: ReceivedAccessRequest, accept: boolean) {
    try {
      await api(`/access-requests/${request.id}/${accept ? 'accept' : 'decline'}/`, {
        method: 'POST',
        body: JSON.stringify(accept ? { team: team.id } : {}),
      })
      const name = request.requester_name ?? request.requester_email
      onMessage(accept ? t('team.requests.accepted', { name, team: team.name }) : t('team.requests.declined', { name }))
      if (accept) onAccepted()
    } catch {
      onMessage(t('common.error'))
    }
    void load()
  }

  if (rows.length === 0) return null
  return (
    <Section id="requests" title={t('team.requests.title')} hint={t('team.requests.hint', { team: team.name })}>
      <List dense disablePadding>
        {rows.map((r) => (
          <ListItem key={r.id} divider disableGutters sx={{ flexWrap: 'wrap', gap: 1 }}>
            <ListItemText
              sx={{ flex: '1 1 240px' }}
              primary={
                <>
                  {r.requester_name ?? r.requester_email}
                  {r.requester_name && (
                    <Typography component="span" variant="body2" color="text.secondary"> · {r.requester_email}</Typography>
                  )}
                </>
              }
              secondary={
                <>
                  {r.message && <Box component="span" sx={{ display: 'block', whiteSpace: 'pre-wrap', fontStyle: 'italic' }}>«{r.message}»</Box>}
                  {dateFormat.format(new Date(r.created_at))}
                </>
              }
            />
            <Stack direction="row" spacing={1}>
              <Button size="small" color="inherit" onClick={() => void answer(r, false)}>{t('team.requests.decline')}</Button>
              <Button size="small" variant="contained" onClick={() => void answer(r, true)}>{t('team.requests.accept')}</Button>
            </Stack>
          </ListItem>
        ))}
      </List>
    </Section>
  )
}

// -- page -------------------------------------------------------------------------------------

/** The current team: profile, people at the table, users and roles, invitations. */
export function TeamPage() {
  const { t } = useTranslation()
  const { refresh } = useAuth()
  const { team: current } = useTeam()
  const [team, setTeam] = useState<TeamProfile | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  // Bumped when someone joins through a request: the users' list reloads.
  const [joined, setJoined] = useState(0)

  const location = useLocation()

  const load = useCallback(() => api<TeamProfile>(`/teams/${current.id}/`).then(setTeam), [current.id])
  useEffect(() => void load(), [load])
  // Links such as /team#week open on a section, once the page has content to scroll to.
  const loaded = team !== null
  useEffect(() => {
    if (loaded && location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView()
  }, [loaded, location.hash])

  if (!team) return <CircularProgress sx={{ display: 'block', mx: 'auto', mt: 6 }} />
  const owner = team.my_role === 'owner'

  return (
    <Stack spacing={3}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'baseline', flexWrap: 'wrap' }}>
        <Typography variant="h1">{team.name}</Typography>
        <Chip size="small" label={t(`team.role.${team.my_role ?? 'member'}`)} />
      </Stack>
      {!owner && <Alert severity="info">{t('team.memberNotice')}</Alert>}
      <ProfileSection key={team.id} team={team} owner={owner}
        onSaved={(saved) => { setTeam(saved); setMessage(t('team.profile.saved')); void refresh() }} />
      <PeopleSection team={team} owner={owner} onChanged={() => void load()} />
      <UsersSection key={joined} team={team} owner={owner} onMessage={setMessage} />
      {owner && <AccessRequestsSection team={team} onMessage={setMessage} onAccepted={() => setJoined((n) => n + 1)} />}
      <InvitationsSection team={team} owner={owner} onMessage={setMessage} />
      {owner && <TeamActivity team={team.id} />}
      <Snackbar open={!!message} autoHideDuration={4000} onClose={() => setMessage(null)} message={message} />
    </Stack>
  )
}
