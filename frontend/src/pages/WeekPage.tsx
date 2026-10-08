import DeleteIcon from '@mui/icons-material/DeleteOutlined'
import EditIcon from '@mui/icons-material/EditOutlined'
import LockIcon from '@mui/icons-material/LockOutlined'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  IconButton,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Snackbar,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink } from 'react-router'
import { api, type Meal, type Paginated, type SystemRule, type TeamProfile, type TeamRule } from '../api'
import { useAuth } from '../auth/context'
import { Section } from '../components/Section'
import { MEALS, useLabels } from '../labels'
import { useTeam } from '../team'

// -- meal pattern -----------------------------------------------------------------------------

const MAX_PEOPLE = 50

// While editing, counts are kept as typed; they become numbers on save.
type DraftDay = { active: boolean } & Record<Meal, string>

function PatternSection({ team, owner, onSaved }: {
  team: TeamProfile
  owner: boolean
  onSaved: (team: TeamProfile) => void
}) {
  const { t } = useTranslation()
  const labels = useLabels()
  const [days, setDays] = useState<DraftDay[]>(() =>
    team.typical_week.map((day) => ({
      active: day.active,
      breakfast: String(day.breakfast),
      lunch: String(day.lunch),
      dinner: String(day.dinner),
    })),
  )
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const valid = days.every((day) =>
    MEALS.every((meal) => /^\d+$/.test(day[meal]) && Number(day[meal]) <= MAX_PEOPLE),
  )

  function change(index: number, patch: Partial<DraftDay>) {
    setDays((current) => current.map((day, i) => (i === index ? { ...day, ...patch } : day)))
  }

  async function save() {
    setBusy(true)
    setError(null)
    try {
      onSaved(
        await api<TeamProfile>(`/teams/${team.id}/`, {
          method: 'PATCH',
          body: JSON.stringify({
            typical_week: days.map((day) => ({
              active: day.active,
              breakfast: Number(day.breakfast),
              lunch: Number(day.lunch),
              dinner: Number(day.dinner),
            })),
          }),
        }),
      )
    } catch {
      setError(t('week.pattern.invalid'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Section title={t('week.pattern.title')} hint={t('week.pattern.hint')}
      action={owner && <Button variant="contained" onClick={() => void save()} disabled={busy || !valid}>{t('common.save')}</Button>}>
      {(error || !valid) && <Alert severity="error" sx={{ mb: 2 }}>{error ?? t('week.pattern.invalid')}</Alert>}
      <Table size="small" sx={{ '& td, & th': { px: { xs: 0.5, sm: 1.5 } } }}>
        <TableHead>
          <TableRow>
            <TableCell>{t('week.pattern.day')}</TableCell>
            <TableCell align="center">{t('week.pattern.active')}</TableCell>
            {MEALS.map((meal) => (
              <TableCell key={meal} align="center">{labels.meal(meal)}</TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {days.map((day, index) => (
            <TableRow key={index}>
              <TableCell>
                <Box component="span" sx={{ display: { xs: 'none', sm: 'inline' } }}>{labels.weekday(index)}</Box>
                <Box component="span" sx={{ display: { xs: 'inline', sm: 'none' } }}>{labels.weekdayShort(index)}</Box>
              </TableCell>
              <TableCell align="center">
                <Switch checked={day.active} disabled={!owner} size="small"
                  onChange={(e) => change(index, { active: e.target.checked })}
                  slotProps={{ input: { 'aria-label': `${labels.weekday(index)}: ${t('week.pattern.active')}` } }} />
              </TableCell>
              {MEALS.map((meal) => (
                <TableCell key={meal} align="center">
                  <TextField size="small" type="number" value={day[meal]}
                    disabled={!owner || !day.active}
                    onChange={(e) => change(index, { [meal]: e.target.value })}
                    error={!/^\d+$/.test(day[meal]) || Number(day[meal]) > MAX_PEOPLE}
                    sx={{ width: { xs: 56, sm: 88 } }}
                    slotProps={{ htmlInput: { min: 0, max: MAX_PEOPLE, inputMode: 'numeric',
                      'aria-label': `${labels.weekday(index)}, ${labels.meal(meal)}` } }} />
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Section>
  )
}

// -- team rules -------------------------------------------------------------------------------

const MAX_RULE = 300

function RuleRow({ rule, owner, onSaved, onDelete }: {
  rule: TeamRule
  owner: boolean
  onSaved: (rule: TeamRule) => void
  onDelete: () => void
}) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function save() {
    if (draft === null) return
    setBusy(true)
    try {
      onSaved(await api<TeamRule>(`/team-rules/${rule.id}/`, { method: 'PATCH', body: JSON.stringify({ text: draft }) }))
      setDraft(null)
    } finally {
      setBusy(false)
    }
  }

  if (draft !== null) {
    return (
      <ListItem disableGutters>
        <Stack direction="row" spacing={1} sx={{ width: '100%', alignItems: 'flex-start' }}>
          <TextField size="small" fullWidth multiline autoFocus value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void save() }
              if (e.key === 'Escape') setDraft(null)
            }}
            slotProps={{ htmlInput: { maxLength: MAX_RULE, 'aria-label': t('week.rules.edit') } }} />
          <Button onClick={() => void save()} disabled={busy || !draft.trim()}>{t('common.save')}</Button>
          <Button color="inherit" onClick={() => setDraft(null)}>{t('common.cancel')}</Button>
        </Stack>
      </ListItem>
    )
  }
  return (
    <ListItem disableGutters
      secondaryAction={owner && (
        <Stack direction="row">
          <Tooltip title={t('common.edit')}>
            <IconButton aria-label={t('week.rules.edit')} onClick={() => setDraft(rule.text)}><EditIcon /></IconButton>
          </Tooltip>
          <Tooltip title={t('common.delete')}>
            <IconButton aria-label={t('week.rules.delete')} onClick={onDelete}><DeleteIcon /></IconButton>
          </Tooltip>
        </Stack>
      )}
      sx={{ pr: owner ? 12 : 0 }}>
      <ListItemText primary={rule.text} />
    </ListItem>
  )
}

function RulesSection({ teamId, owner, onMessage }: {
  teamId: number
  owner: boolean
  onMessage: (message: string) => void
}) {
  const { t } = useTranslation()
  const [rules, setRules] = useState<TeamRule[] | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api<Paginated<TeamRule>>(`/team-rules/?team=${teamId}`).then((page) => setRules(page.results))
  }, [teamId])

  async function add() {
    const sent = text
    setBusy(true)
    try {
      const rule = await api<TeamRule>('/team-rules/', { method: 'POST', body: JSON.stringify({ team: teamId, text: sent }) })
      setRules((list) => [...(list ?? []), rule])
      // Keep whatever was typed while saving.
      setText((current) => (current === sent ? '' : current))
    } catch {
      onMessage(t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  async function remove(rule: TeamRule) {
    try {
      await api(`/team-rules/${rule.id}/`, { method: 'DELETE' })
      setRules((list) => list?.filter((r) => r.id !== rule.id) ?? null)
      onMessage(t('week.rules.deleted'))
    } catch {
      onMessage(t('common.error'))
    }
  }

  return (
    <Section title={t('week.rules.title')} hint={t('week.rules.hint')}>
      {!rules ? (
        <CircularProgress size={24} />
      ) : (
        <>
          {rules.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic', mb: owner ? 2 : 0 }}>
              {t('week.rules.empty')}
            </Typography>
          ) : (
            <List dense disablePadding sx={{ mb: owner ? 2 : 0 }}>
              {rules.map((rule) => (
                <RuleRow key={rule.id} rule={rule} owner={owner}
                  onSaved={(saved) => setRules((list) => list?.map((r) => (r.id === saved.id ? saved : r)) ?? null)}
                  onDelete={() => void remove(rule)} />
              ))}
            </List>
          )}
          {owner && (
            <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
              <TextField size="small" fullWidth multiline value={text} label={t('week.rules.new')}
                placeholder={t('week.rules.placeholder')}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (text.trim() && !busy) void add() }
                }}
                slotProps={{ htmlInput: { maxLength: MAX_RULE }, inputLabel: { shrink: true } }} />
              <Button variant="contained" onClick={() => void add()} disabled={busy || !text.trim()}>{t('common.add')}</Button>
            </Stack>
          )}
        </>
      )}
    </Section>
  )
}

// -- system rules -----------------------------------------------------------------------------

function SystemRulesSection() {
  const { t } = useTranslation()
  const labels = useLabels()
  const [rules, setRules] = useState<SystemRule[] | null>(null)
  const { me } = useAuth()
  // Staff also get the switched-off rules, for the management section: only active ones apply.
  useEffect(() => void api<SystemRule[]>('/system-rules/').then((all) => setRules(all.filter((r) => r.active))), [])
  return (
    <Section title={t('week.system.title')} hint={t('week.system.hint')}
      action={me?.authenticated && me.user.is_staff && (
        <Button component={RouterLink} to="/manage/rules" size="small">{t('week.system.manage')}</Button>
      )}>
      {!rules ? (
        <CircularProgress size={24} />
      ) : (
        <List dense disablePadding>
          {rules.map((rule) => (
            <ListItem key={rule.id} disableGutters>
              <ListItemIcon sx={{ minWidth: 36 }}><LockIcon fontSize="small" color="disabled" /></ListItemIcon>
              <ListItemText primary={labels.systemRule(rule)} />
            </ListItem>
          ))}
        </List>
      )}
    </Section>
  )
}

// -- page -------------------------------------------------------------------------------------

/** The typical week: how many people at each meal, and the rules that guide menu planning. */
export function WeekPage() {
  const { t } = useTranslation()
  const { team: current } = useTeam()
  const [team, setTeam] = useState<TeamProfile | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => void api<TeamProfile>(`/teams/${current.id}/`).then(setTeam), [current.id])

  if (!team) return <CircularProgress sx={{ display: 'block', mx: 'auto', mt: 6 }} />
  const owner = team.my_role === 'owner'

  return (
    <Stack spacing={3}>
      <Typography variant="h1">{t('week.title')}</Typography>
      {!owner && <Alert severity="info">{t('week.memberNotice')}</Alert>}
      <PatternSection key={team.id} team={team} owner={owner}
        onSaved={(saved) => { setTeam(saved); setMessage(t('week.pattern.saved')) }} />
      <RulesSection key={`rules-${team.id}`} teamId={team.id} owner={owner} onMessage={setMessage} />
      <SystemRulesSection />
      <Snackbar open={!!message} autoHideDuration={4000} onClose={() => setMessage(null)} message={message} />
    </Stack>
  )
}
