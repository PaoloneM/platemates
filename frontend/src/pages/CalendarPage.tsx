import ChevronLeftIcon from '@mui/icons-material/ChevronLeft'
import ArrowDropDownIcon from '@mui/icons-material/ArrowDropDown'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import DeleteIcon from '@mui/icons-material/DeleteOutlined'
import NoteIcon from '@mui/icons-material/StickyNote2Outlined'
import SettingsIcon from '@mui/icons-material/SettingsOutlined'
import {
  Alert,
  Box,
  Button,
  ButtonBase,
  Card,
  CardActionArea,
  CardActions,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Popover,
  Snackbar,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { AdapterDateFns } from '@mui/x-date-pickers/AdapterDateFns'
import { DateCalendar } from '@mui/x-date-pickers/DateCalendar'
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider'
import { PickerDay, type PickerDayProps } from '@mui/x-date-pickers/PickerDay'
import type { Theme } from '@mui/material/styles'
import { enGB, it } from 'date-fns/locale'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, useSearchParams } from 'react-router'
import { api, type CalendarDay, type CalendarDayChange, type Meal, type MenuGeneration } from '../api'
import {
  addDays,
  changeDay,
  cleared,
  fromIso,
  isIsoDate,
  isoDate,
  generateMenu,
  generationActive,
  hasProposal,
  latestGeneration,
  mealInUse,
  reviewProposals,
  mealUrl,
  mondayOf,
  snapshot,
} from '../calendar'
import { DishLine } from '../components/DishLine'
import { GenerationBanner } from '../components/GenerationBanner'
import { MenuFab } from '../components/MenuFab'
import { PeopleCount } from '../components/PeopleCount'
import { MEALS, useDayTitle, useLabels } from '../labels'
import { useTeam } from '../team'

const MAX_PEOPLE = 50
const POLL_MS = 3000

function MealCard({ day, meal, owner, onClear, onReview }: {
  day: CalendarDay
  meal: Meal
  owner: boolean
  onClear: () => void
  onReview: (action: 'accept' | 'reject') => void
}) {
  const { t } = useTranslation()
  const labels = useLabels()
  const dishes = day.dishes[meal]
  const nobody = day.people[meal] === 0 && day.proposed_people[meal] === undefined
  const proposal = hasProposal(day, meal)
  return (
    <Card sx={{
      position: 'relative', height: '100%', display: 'flex', flexDirection: 'column', opacity: nobody ? 0.6 : 1,
      ...(proposal && { outline: '1px dashed', outlineColor: 'primary.main', outlineOffset: -1 }),
    }}>
      <CardActionArea component={RouterLink} to={mealUrl(day.date, meal)}
        sx={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'stretch', justifyContent: 'flex-start', p: 1.5, pr: owner ? 6 : 1.5 }}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 0.75 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{labels.meal(meal)}</Typography>
          <PeopleCount day={day} meal={meal} />
        </Stack>
        {nobody ? (
          <Typography variant="body2" color="text.secondary">{t('calendar.nobodyHome')}</Typography>
        ) : !dishes ? (
          <Typography variant="body2" color="text.secondary">{t('calendar.countedOnly')}</Typography>
        ) : dishes.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>{t('calendar.noDishes')}</Typography>
        ) : (
          <Stack spacing={0.25}>
            {dishes.map((dish, index) => <DishLine key={index} dish={dish} />)}
          </Stack>
        )}
      </CardActionArea>
      {proposal && (
        <CardActions sx={{ pt: 0, px: 1, justifyContent: 'flex-end' }}>
          <Button size="small" color="inherit" onClick={() => onReview('reject')}
            aria-label={`${t('generation.reject')}: ${labels.meal(meal)}`}>{t('generation.reject')}</Button>
          <Button size="small" onClick={() => onReview('accept')}
            aria-label={`${t('generation.accept')}: ${labels.meal(meal)}`}>{t('generation.accept')}</Button>
        </CardActions>
      )}
      {owner && mealInUse(day, meal) && (
        <Tooltip title={t('calendar.clearMeal')}>
          <IconButton size="small" onClick={onClear} aria-label={`${t('calendar.clearMeal')}: ${labels.meal(meal)}`}
            sx={{ position: 'absolute', top: 8, right: 8 }}>
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      )}
    </Card>
  )
}

function DayRow({ day, today, owner, onConfigure, onClear, onReview }: {
  day: CalendarDay
  today: boolean
  owner: boolean
  onConfigure: () => void
  onClear: (meals: Meal[]) => void
  onReview: (meal: Meal, action: 'accept' | 'reject') => void
}) {
  const { t } = useTranslation()
  const { weekday, dayMonth } = useDayTitle(day.date)
  const title = (
    <Stack direction="row" spacing={1} sx={{ alignItems: 'baseline' }}>
      <Typography variant="h3" sx={{ color: today ? 'primary.main' : undefined }}>{weekday}</Typography>
      <Typography variant="body2" color={today ? 'primary.main' : 'text.secondary'}>
        {today ? t('calendar.today', { date: dayMonth }) : dayMonth}
      </Typography>
    </Stack>
  )
  return (
    <Box component="section" aria-label={`${weekday} ${dayMonth}`}>
      <Stack direction="row" sx={{ alignItems: 'center', gap: 0.5, mb: 1, flexWrap: 'wrap' }}>
        {owner ? (
          <ButtonBase onClick={onConfigure} sx={{ borderRadius: 1, px: 0.5, mx: -0.5 }}>{title}</ButtonBase>
        ) : title}
        {owner && (
          <>
            <Tooltip title={t('calendar.configureDay')}>
              <IconButton size="small" onClick={onConfigure} aria-label={`${t('calendar.configureDay')}: ${weekday} ${dayMonth}`}>
                <SettingsIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            {MEALS.some((meal) => mealInUse(day, meal)) && (
              <Tooltip title={t('calendar.clearDay')}>
                <IconButton size="small" onClick={() => onClear(MEALS.filter((meal) => mealInUse(day, meal)))}
                  aria-label={`${t('calendar.clearDay')}: ${weekday} ${dayMonth}`}>
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
          </>
        )}
        {day.note && (
          <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center', color: 'text.secondary', ml: 1, minWidth: 0 }}>
            <NoteIcon sx={{ fontSize: 16 }} />
            <Typography variant="body2" sx={{ fontStyle: 'italic', overflowWrap: 'anywhere' }}>{day.note}</Typography>
          </Stack>
        )}
      </Stack>
      <Box sx={{ display: 'grid', gap: 1.5, gridTemplateColumns: { xs: '1fr', sm: 'repeat(auto-fill, minmax(280px, 1fr))' } }}>
        {MEALS.map((meal) => (
          <MealCard key={meal} day={day} meal={meal} owner={owner} onClear={() => onClear([meal])}
            onReview={(action) => onReview(meal, action)} />
        ))}
      </Box>
    </Box>
  )
}

function DayDialog({ team, day, onClose, onSaved }: {
  team: number
  day: CalendarDay
  onClose: () => void
  onSaved: (day: CalendarDay) => void
}) {
  const { t } = useTranslation()
  const labels = useLabels()
  const { weekday, dayMonth } = useDayTitle(day.date)
  const [people, setPeople] = useState<Record<Meal, string>>(() => ({
    breakfast: String(day.people.breakfast),
    lunch: String(day.people.lunch),
    dinner: String(day.people.dinner),
  }))
  const [note, setNote] = useState(day.note)
  const [error, setError] = useState(false)
  const [busy, setBusy] = useState(false)
  const validCount = (value: string) => /^\d+$/.test(value) && Number(value) <= MAX_PEOPLE
  const valid = MEALS.every((meal) => validCount(people[meal]))

  async function send(request: () => Promise<CalendarDay>) {
    setBusy(true)
    setError(false)
    try {
      onSaved(await request())
    } catch {
      setError(true)
      setBusy(false)
    }
  }

  const save = () => send(() => changeDay(team, day.date, {
    people: Object.fromEntries(MEALS.map((meal) => [meal, Number(people[meal])])),
    note: note.trim(),
  }))
  const reset = () => send(() => api<CalendarDay>(`/calendar/${day.date}/?team=${team}`, { method: 'DELETE' }))

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{weekday} {dayMonth}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            {day.active ? t('calendar.dialogHint') : t('calendar.dialogHintDayOff')}
          </Typography>
          {error && <Alert severity="error">{t('common.error')}</Alert>}
          {MEALS.map((meal) => {
            const changed = Number(people[meal]) !== day.usual[meal]
            return (
              <TextField key={meal} label={labels.meal(meal)} type="number" value={people[meal]}
                onChange={(e) => setPeople((current) => ({ ...current, [meal]: e.target.value }))}
                error={!validCount(people[meal])}
                color={changed ? 'secondary' : undefined} focused={changed || undefined}
                helperText={t('calendar.usually', { count: day.usual[meal] })}
                slotProps={{ htmlInput: { min: 0, max: MAX_PEOPLE, inputMode: 'numeric' } }} />
            )
          })}
          <TextField label={t('calendar.note')} value={note} onChange={(e) => setNote(e.target.value)}
            helperText={t('calendar.noteHint')} slotProps={{ htmlInput: { maxLength: 200 } }} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ flexWrap: 'wrap' }}>
        {(day.overridden.length > 0 || day.note) && (
          <Button color="secondary" onClick={() => void reset()} disabled={busy} sx={{ mr: 'auto' }}>
            {t('calendar.reset')}
          </Button>
        )}
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="contained" onClick={() => void save()} disabled={busy || !valid}>{t('common.save')}</Button>
      </DialogActions>
    </Dialog>
  )
}

/** Arrows to move by a week, "Today" on the side today lies on, and the week's dates opening a
 * month calendar to jump to any date. Nothing moves when "Today" appears: both slots keep their
 * width. */
function WeekBar({ monday, thisMonday, onChange }: {
  monday: Date
  thisMonday: Date
  onChange: (monday: Date) => void
}) {
  const { t, i18n } = useTranslation()
  const sunday = addDays(monday, 6)
  // Phones get short month names, so the dates fit between the arrows.
  const format = (month: 'long' | 'short') => {
    const date = new Intl.DateTimeFormat(i18n.resolvedLanguage, { day: 'numeric', month })
    return t('calendar.week', { start: date.format(monday), end: date.format(sunday) })
  }
  const title = format('long')
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const offset = monday.getTime() - thisMonday.getTime()
  const todayButton = (visible: boolean) => (
    <Button size="small" variant="outlined" onClick={() => onChange(thisMonday)} tabIndex={visible ? 0 : -1}
      aria-hidden={!visible} sx={{ visibility: visible ? 'visible' : 'hidden', minWidth: 0, flexShrink: 0 }}>
      {t('calendar.today_button')}
    </Button>
  )
  const inWeek = (date: Date) => date >= monday && date <= sunday

  return (
    <Stack direction="row" sx={{ alignItems: 'center', gap: { xs: 0.5, sm: 1 } }}>
      <IconButton onClick={() => onChange(addDays(monday, -7))} aria-label={t('calendar.previous')}>
        <ChevronLeftIcon />
      </IconButton>
      {todayButton(offset > 0)}
      <Box sx={{ flex: 1, minWidth: 0, textAlign: 'center' }}>
        <Button onClick={(e) => setAnchor(e.currentTarget)} color="inherit" endIcon={<ArrowDropDownIcon />}
          aria-label={`${title}: ${t('calendar.pickDate')}`} aria-haspopup="dialog"
          sx={{ typography: 'h2', px: 1.5, maxWidth: '100%' }}>
          <Box component="span" sx={{ display: { xs: 'none', sm: 'inline' } }}>{title}</Box>
          <Box component="span" sx={{ display: { xs: 'inline', sm: 'none' }, whiteSpace: 'nowrap' }}>{format('short')}</Box>
        </Button>
      </Box>
      {todayButton(offset < 0)}
      <IconButton onClick={() => onChange(addDays(monday, 7))} aria-label={t('calendar.next')}>
        <ChevronRightIcon />
      </IconButton>
      <Popover open={!!anchor} anchorEl={anchor} onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }} transformOrigin={{ vertical: 'top', horizontal: 'center' }}>
        <LocalizationProvider dateAdapter={AdapterDateFns} adapterLocale={i18n.resolvedLanguage === 'en' ? enGB : it}>
          <DateCalendar
            // The week on screen: the calendar opens on its month; the whole week is highlighted.
            value={monday}
            showDaysOutsideCurrentMonth
            onChange={(date: Date | null) => {
              if (!date) return
              setAnchor(null)
              onChange(mondayOf(date))
            }}
            slots={{ day: WeekDay }}
            slotProps={{ day: { inWeek } as Partial<PickerDayProps> }}
          />
        </LocalizationProvider>
      </Popover>
    </Stack>
  )
}

/** A day of the month calendar; the days of the week on screen are highlighted together. */
function WeekDay(props: PickerDayProps & { inWeek?: (date: Date) => boolean }) {
  const { inWeek, day, ...rest } = props
  const highlighted = !rest.outsideCurrentMonth && !!inWeek?.(day as Date)
  return (
    <PickerDay {...rest} day={day} selected={false} sx={{
      ...(highlighted && {
        bgcolor: (theme: Theme) => theme.alpha((theme.vars ?? theme).palette.primary.main, 0.16),
        color: 'primary.main',
        fontWeight: 600,
      }),
    }} />
  )
}

type Notice = { message: string; undo?: { date: string; change: CalendarDayChange } }

export function CalendarPage() {
  const { t } = useTranslation()
  const labels = useLabels()
  const { team } = useTeam()
  const owner = team.role === 'owner'
  const [days, setDays] = useState<CalendarDay[] | null>(null)
  const [configuring, setConfiguring] = useState<CalendarDay | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [params, setParams] = useSearchParams()
  // Read once per visit: "today" does not need to follow the clock while the page is open.
  const [today] = useState(() => new Date())
  const week = params.get('week')
  const monday = mondayOf(isIsoDate(week) ? fromIso(week) : today)
  const start = isoDate(monday)
  const thisMonday = mondayOf(today)
  const todayIso = isoDate(today)

  // The latest generation, with the week it belongs to: another week's is never shown.
  const [loadedGeneration, setLoadedGeneration] = useState<{ week: string; generation: MenuGeneration | null } | null>(null)
  const generation = loadedGeneration?.week === start ? loadedGeneration.generation : null
  const setGeneration = useCallback(
    (value: MenuGeneration | null) => setLoadedGeneration({ week: start, generation: value }),
    [start],
  )
  const [reviewing, setReviewing] = useState(false)

  const loadDays = useCallback(
    () => api<CalendarDay[]>(`/calendar/?team=${team.id}&start=${start}&days=7`).then(setDays),
    [team.id, start],
  )
  useEffect(() => void loadDays(), [loadDays])

  useEffect(() => {
    latestGeneration(team.id, start).then(setGeneration)
  }, [team.id, start, setGeneration])

  // While the week is being generated, check every few seconds; once it ends, show the result.
  const active = generationActive(generation)
  const generationId = generation?.id
  useEffect(() => {
    if (!active || generationId === undefined) return
    const timer = setInterval(async () => {
      const latest = await latestGeneration(team.id, start).catch(() => null)
      if (!latest || latest.id !== generationId || generationActive(latest)) return
      setGeneration(latest)
      void loadDays()
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [active, generationId, team.id, start, loadDays, setGeneration])

  const pending = !!days?.some((day) => MEALS.some((meal) => hasProposal(day, meal)))

  async function generate(useWeekSettings: boolean) {
    if (pending && !window.confirm(t('generation.replaceConfirm'))) return
    try {
      setGeneration(await generateMenu(team.id, start, useWeekSettings))
    } catch {
      setNotice({ message: t('common.error') })
    }
  }

  async function review(action: 'accept' | 'reject', meals?: { date: string; meal: Meal }[]) {
    if (!generation) return
    setReviewing(true)
    try {
      await reviewProposals(generation.menu, action, meals)
      await loadDays()
      setNotice({ message: t(action === 'accept' ? 'generation.accepted' : 'generation.rejected') })
    } catch {
      setNotice({ message: t('common.error') })
    } finally {
      setReviewing(false)
    }
  }

  const replace = (saved: CalendarDay) =>
    setDays((list) => list?.map((d) => (d.date === saved.date ? saved : d)) ?? null)

  async function clear(day: CalendarDay, meals: Meal[]) {
    try {
      replace(await changeDay(team.id, day.date, cleared(day, meals)))
      const weekday = labels.weekday((fromIso(day.date).getDay() + 6) % 7)
      setNotice({
        message: meals.length === 1
          ? t('calendar.mealCleared', { meal: labels.meal(meals[0]), day: weekday })
          : t('calendar.dayCleared', { day: weekday }),
        undo: { date: day.date, change: snapshot(day, meals) },
      })
    } catch {
      setNotice({ message: t('common.error') })
    }
  }

  async function undo(action: NonNullable<Notice['undo']>) {
    setNotice(null)
    try {
      replace(await changeDay(team.id, action.date, action.change))
    } catch {
      setNotice({ message: t('common.error') })
    }
  }

  const goTo = (date: Date) =>
    setParams(isoDate(date) === isoDate(thisMonday) ? {} : { week: isoDate(date) })

  const current = days?.[0]?.date === start ? days : null

  return (
    <Stack spacing={2}>
      <Stack direction="row" sx={{ alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
        <Typography variant="h1" sx={{ flex: 1, minWidth: 0 }}>{t('calendar.title')}</Typography>
        <Button component={RouterLink} to="/week" size="small">{t('calendar.editWeek')}</Button>
      </Stack>
      <WeekBar monday={monday} thisMonday={thisMonday} onChange={goTo} />
      <GenerationBanner generation={generation} pending={pending} busy={reviewing}
        onAcceptAll={() => void review('accept')} onRejectAll={() => void review('reject')}
        onRetry={() => void generate(generation?.use_week_settings ?? false)} />
      {!current ? (
        <CircularProgress sx={{ display: 'block', mx: 'auto', mt: 4 }} />
      ) : (
        <Stack spacing={3}>
          {current.map((day) => (
            <DayRow key={day.date} day={day} today={day.date === todayIso} owner={owner}
              onConfigure={() => setConfiguring(day)} onClear={(meals) => void clear(day, meals)}
              onReview={(meal, action) => void review(action, [{ date: day.date, meal }])} />
          ))}
        </Stack>
      )}
      <Typography variant="body2" color="text.secondary">
        {owner ? t('calendar.hintOwner') : t('calendar.hint')}
      </Typography>
      {configuring && (
        <DayDialog team={team.id} day={configuring} onClose={() => setConfiguring(null)}
          onSaved={(saved) => {
            replace(saved)
            setConfiguring(null)
            setNotice({ message: t('calendar.saved') })
          }} />
      )}
      <MenuFab weekStart={start} generating={active} onGenerate={(useWeek) => void generate(useWeek)}
        onSaved={() => setNotice({ message: t('plan.saved') })} />
      <Snackbar open={!!notice} autoHideDuration={notice?.undo ? 6000 : 3000} onClose={() => setNotice(null)}
        message={notice?.message}
        action={notice?.undo && (
          <Button color="inherit" size="small" onClick={() => void undo(notice.undo!)}>{t('calendar.undo')}</Button>
        )} />
    </Stack>
  )
}
