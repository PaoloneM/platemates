import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Collapse,
  List,
  ListItemButton,
  ListItemText,
  ListSubheader,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type AuditChange, type AuditEvent, type Paginated, type TeamMembership } from '../api'
import { useLabels } from '../labels'
import { Section } from './Section'

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

/** What the team's people changed, newest first, for the team's owners. */
export function TeamActivity({ team }: { team: number }) {
  const { t, i18n } = useTranslation()
  const [events, setEvents] = useState<AuditEvent[] | null>(null)
  const [next, setNext] = useState<string | null>(null)
  const [people, setPeople] = useState<TeamMembership[]>([])
  const [user, setUser] = useState('')
  const [open, setOpen] = useState<number | null>(null)
  const [error, setError] = useState(false)

  const query = useCallback((page = 1) => {
    const params = new URLSearchParams({ team: String(team), page: String(page) })
    if (user) params.set('user', user)
    return api<Paginated<AuditEvent>>(`/audit-events/?${params}`)
  }, [team, user])

  useEffect(() => {
    query().then((page) => { setEvents(page.results); setNext(page.next) }).catch(() => setError(true))
  }, [query])
  useEffect(() => {
    api<Paginated<TeamMembership>>(`/memberships/?team=${team}`).then((page) => setPeople(page.results)).catch(() => undefined)
  }, [team])

  async function more() {
    const page = Number(new URL(next!, window.location.origin).searchParams.get('page'))
    const loaded = await query(page)
    setEvents((e) => [...(e ?? []), ...loaded.results])
    setNext(loaded.next)
  }

  const day = (iso: string) => {
    const text = new Intl.DateTimeFormat(i18n.resolvedLanguage, { weekday: 'long', day: 'numeric', month: 'long' }).format(new Date(iso))
    return text.charAt(0).toUpperCase() + text.slice(1)
  }
  const time = (iso: string) => new Intl.DateTimeFormat(i18n.resolvedLanguage, { hour: '2-digit', minute: '2-digit' }).format(new Date(iso))
  const groups: [string, AuditEvent[]][] = []
  for (const event of events ?? []) {
    const key = day(event.created_at)
    const last = groups[groups.length - 1]
    if (last && last[0] === key) last[1].push(event)
    else groups.push([key, [event]])
  }

  return (
    <Section id="activity" title={t('audit.title')} hint={t('audit.hint')}
      action={
        <TextField select size="small" label={t('audit.who')} value={user}
          onChange={(e) => { setEvents(null); setUser(e.target.value) }}
          slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}
          sx={{ width: 200, flexShrink: 0, ml: 2 }}>
          <MenuItem value="">{t('audit.everyone')}</MenuItem>
          {people.map((p) => <MenuItem key={p.id} value={String(p.user)}>{p.name}</MenuItem>)}
        </TextField>
      }>
      {error && <Alert severity="error">{t('common.error')}</Alert>}
      {!events ? <CircularProgress size={24} /> : events.length === 0 ? (
        <Typography color="text.secondary">{t('audit.none')}</Typography>
      ) : (
        <List dense disablePadding>
          {groups.map(([label, group]) => (
            <li key={label}>
              <ul style={{ padding: 0 }}>
                <ListSubheader sx={{ px: 0, bgcolor: 'background.paper' }}>{label}</ListSubheader>
                {group.map((event) => (
                  <Box key={event.id} component="li" sx={{ listStyle: 'none' }}>
                    <ListItemButton onClick={() => setOpen(open === event.id ? null : event.id)} sx={{ px: 0, gap: 1.5 }}>
                      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 44, fontVariantNumeric: 'tabular-nums' }}>
                        {time(event.created_at)}
                      </Typography>
                      <ListItemText primary={<Summary event={event} />} />
                      {open === event.id ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                    </ListItemButton>
                    <Collapse in={open === event.id} unmountOnExit>
                      <Stack spacing={1} sx={{ pl: 7, pb: 1.5 }}>
                        {event.changes.map((change) => <ChangeDetail key={`${change.type}-${change.id}`} change={change} />)}
                      </Stack>
                    </Collapse>
                  </Box>
                ))}
              </ul>
            </li>
          ))}
        </List>
      )}
      {next && <Button onClick={() => void more()} sx={{ mt: 1 }}>{t('audit.more')}</Button>}
    </Section>
  )
}

/** "Paolo ha modificato la ricetta «Hummus»". */
function Summary({ event }: { event: AuditEvent }) {
  const { t } = useTranslation()
  const label = useTargetLabel()
  const first = event.changes[0]
  const target = label(event.target_type, event.target_label)
  const specific = t(`audit.action.${event.action}`, { target, defaultValue: '' })
  const generic = first
    ? t(`audit.op.${first.op}`, { what: t(`audit.type.${first.type}`, { defaultValue: first.type }), target })
    : ''
  const others = event.changes.length - 1
  return (
    <>
      <Box component="span" sx={{ fontWeight: 600 }}>{event.user_name}</Box>{' '}
      {specific || generic}
      {others > 0 && !specific && (
        <Typography component="span" variant="body2" color="text.secondary"> {t('audit.andMore', { count: others })}</Typography>
      )}
    </>
  )
}

/** A target as people read it: dates of days and weeks written out. */
function useTargetLabel() {
  const { t, i18n } = useTranslation()
  return (type: string, value: string) => {
    if (!ISO_DATE.test(value)) return value
    const date = new Intl.DateTimeFormat(i18n.resolvedLanguage, { weekday: 'long', day: 'numeric', month: 'short' })
      .format(new Date(`${value}T12:00:00`))
    return type === 'week' || type === 'generation' ? t('audit.weekOf', { date }) : date
  }
}

function ChangeDetail({ change }: { change: AuditChange }) {
  const { t, i18n } = useTranslation()
  const labels = useLabels()
  const label = useTargetLabel()
  const fieldName = (name: string) => {
    const [base, meal] = name.split('.')
    if (meal) {
      const name = labels.meal(meal as never)
      return t(`audit.field.${base}`, { meal: i18n.resolvedLanguage === 'it' ? name.toLowerCase() : name })
    }
    return t(`audit.field.${name}`, { defaultValue: name.replace(/_/g, ' ') })
  }
  const show = (value: unknown): string => {
    if (value === null || value === undefined || value === '') return '—'
    if (Array.isArray(value)) return value.length ? value.map(show).join(', ') : '—'
    if (typeof value === 'boolean') return value ? t('audit.yes') : t('audit.no')
    if (typeof value === 'object') return JSON.stringify(value)
    return String(value)
  }
  return (
    <Box>
      <Typography variant="body2">
        {t(`audit.op.${change.op}`, { what: t(`audit.type.${change.type}`, { defaultValue: change.type }), target: label(change.type, change.label) })}
      </Typography>
      {Object.entries(change.fields ?? {}).map(([name, [before, after]]) => (
        <Typography key={name} variant="body2" color="text.secondary" sx={{ pl: 2, overflowWrap: 'anywhere' }}>
          {fieldName(name)}: {show(before)} → {show(after)}
        </Typography>
      ))}
    </Box>
  )
}
