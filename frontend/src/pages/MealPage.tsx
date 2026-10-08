import AddIcon from '@mui/icons-material/Add'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import DeleteIcon from '@mui/icons-material/DeleteOutlined'
import ZoomInIcon from '@mui/icons-material/ZoomIn'
import {
  Alert,
  Autocomplete,
  Button,
  Card,
  CardContent,
  CircularProgress,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Snackbar,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, Navigate, useParams } from 'react-router'
import { api, type BookEntry, type CalendarDay, type CalendarDayChange, type DishInput, type GenerationEvent, type Meal, type Paginated } from '../api'
import { changeDay, dishInput, fromIso, hasProposal, isIsoDate, isoDate, mondayOf, reviewMeal, snapshot, weekUrl } from '../calendar'
import { DishLine } from '../components/DishLine'
import { RecipeDialog } from '../components/RecipeDialog'
import { PeopleCount } from '../components/PeopleCount'
import { MEALS, useDayTitle, useLabels } from '../labels'
import { useRealtimeEvent } from '../realtime'
import { useTeam } from '../team'

const MAX_PEOPLE = 50

function Section({ title, hint, action, children }: { title: string; hint?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <Card>
      <CardContent>
        <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', mb: hint ? 0.5 : 1.5, gap: 1 }}>
          <Typography variant="h2">{title}</Typography>
          {action}
        </Stack>
        {hint && <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>{hint}</Typography>}
        {children}
      </CardContent>
    </Card>
  )
}

function PeopleSection({ day, meal, owner, onChange }: {
  day: CalendarDay
  meal: Meal
  owner: boolean
  onChange: (change: CalendarDayChange) => Promise<void>
}) {
  const { t } = useTranslation()
  const [value, setValue] = useState(String(day.people[meal]))
  const [busy, setBusy] = useState(false)
  const valid = /^\d+$/.test(value) && Number(value) <= MAX_PEOPLE
  const dirty = valid && Number(value) !== day.people[meal]

  async function save(count: number) {
    setBusy(true)
    await onChange({ people: { [meal]: count } })
    setValue(String(count))
    setBusy(false)
  }

  return (
    <Section title={t('meal.people')} action={<PeopleCount day={day} meal={meal} />}>
      <Stack direction="row" spacing={1.5} sx={{ alignItems: 'flex-start', flexWrap: 'wrap', rowGap: 1.5 }}>
        <TextField label={t('meal.diners')} type="number" value={value} disabled={!owner} error={!valid}
          onChange={(e) => setValue(e.target.value)} sx={{ width: 160 }}
          helperText={t('calendar.usually', { count: day.usual[meal] })}
          slotProps={{ htmlInput: { min: 0, max: MAX_PEOPLE, inputMode: 'numeric' } }} />
        {owner && (
          <Button variant="contained" onClick={() => void save(Number(value))} disabled={busy || !dirty} sx={{ mt: 1 }}>
            {t('common.save')}
          </Button>
        )}
        {owner && day.overridden.includes(meal) && (
          <Button color="secondary" onClick={() => void save(day.usual[meal])} disabled={busy} sx={{ mt: 1 }}>
            {t('meal.backToUsual', { count: day.usual[meal] })}
          </Button>
        )}
      </Stack>
    </Section>
  )
}

function DishesSection({ day, meal, owner, onChange }: {
  day: CalendarDay
  meal: Meal
  owner: boolean
  onChange: (change: CalendarDayChange) => Promise<void>
}) {
  const { t } = useTranslation()
  const labels = useLabels()
  const { team } = useTeam()
  const dishes = day.dishes[meal] ?? []
  const [search, setSearch] = useState('')
  const [options, setOptions] = useState<BookEntry[]>([])
  const [busy, setBusy] = useState(false)
  // Index in `recipes` of the recipe shown in the dialog.
  const [viewing, setViewing] = useState<number | null>(null)

  useEffect(() => {
    if (!owner) return
    const params = new URLSearchParams({ team: String(team.id), status: 'approved' })
    if (search.trim()) params.set('search', search.trim())
    let cancelled = false
    const timer = setTimeout(() => {
      api<Paginated<BookEntry>>(`/recipe-book/?${params}`).then((page) => {
        if (!cancelled) setOptions(page.results)
      })
    }, 250)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [owner, team.id, search])

  async function setDishes(wanted: DishInput[]) {
    setBusy(true)
    await onChange({ dishes: { [meal]: wanted } })
    setBusy(false)
  }

  const planned = new Set(dishes.map((d) => d.recipe))
  const recipes = dishes.flatMap((d) => (d.recipe === null ? [] : [{ recipe: d.recipe, title: d.title }]))
  return (
    <Section title={t('meal.menu')} hint={dishes.length === 0 ? t('meal.menuEmpty') : undefined}>
      {dishes.length > 0 && (
        <List disablePadding sx={{ mb: owner ? 2 : 0 }}>
          {dishes.map((dish, index) => {
            const text = (
              <ListItemText primary={<DishLine dish={dish} />} secondary={dish.note || undefined}
                slotProps={{ primary: { component: 'div' } }} />
            )
            return (
              <ListItem key={index} disablePadding={dish.recipe !== null} divider
                sx={{ pr: (owner ? 6 : 0) + (dish.recipe !== null ? 6 : 0) }}
                secondaryAction={(owner || dish.recipe !== null) && (
                  <Stack direction="row">
                    {dish.recipe !== null && (
                      <Tooltip title={t('meal.viewRecipe')}>
                        <IconButton aria-label={`${t('meal.viewRecipe')}: ${dish.title}`}
                          onClick={() => setViewing(recipes.findIndex((r) => r.recipe === dish.recipe))}>
                          <ZoomInIcon />
                        </IconButton>
                      </Tooltip>
                    )}
                    {owner && (
                      <IconButton edge="end" disabled={busy} aria-label={`${t('meal.removeDish')}: ${dish.title}`}
                        onClick={() => void setDishes(dishes.filter((_, i) => i !== index).map(dishInput))}>
                        <DeleteIcon />
                      </IconButton>
                    )}
                  </Stack>
                )}>
                {dish.recipe !== null ? (
                  <ListItemButton component={RouterLink} to={`/recipes/${dish.recipe}`}>{text}</ListItemButton>
                ) : text}
              </ListItem>
            )
          })}
        </List>
      )}
      {viewing !== null && (
        <RecipeDialog dishes={recipes} initial={viewing} people={day.proposed_people[meal] ?? day.people[meal]}
          onClose={() => setViewing(null)} />
      )}
      {owner && (
        <Autocomplete<BookEntry>
          options={options.filter((entry) => !planned.has(entry.recipe))}
          value={null}
          disabled={busy}
          filterOptions={(x) => x}
          getOptionLabel={(entry) => entry.recipe_summary.title}
          onInputChange={(_, value, reason) => reason !== 'reset' && setSearch(value)}
          onChange={(_, entry) => {
            if (entry) {
              setSearch('')
              void setDishes([...dishes.map(dishInput), entry.recipe])
            }
          }}
          renderOption={({ key, ...props }, entry) => (
            <li key={key} {...props}>
              <ListItemText primary={entry.recipe_summary.title} secondary={labels.course(entry.recipe_summary.course)} />
            </li>
          )}
          noOptionsText={t('meal.noRecipes')}
          renderInput={(params) => (
            <TextField {...params} label={t('meal.addDish')} placeholder={t('book.search')}
              slotProps={{ ...params.slotProps, input: { ...params.slotProps.input, startAdornment: <AddIcon color="action" sx={{ ml: 0.5 }} /> } }} />
          )}
        />
      )}
    </Section>
  )
}

export function MealPage() {
  const { t } = useTranslation()
  const labels = useLabels()
  const { team } = useTeam()
  const { date, meal } = useParams()
  const valid = isIsoDate(date) && MEALS.includes(meal as Meal)
  const [day, setDay] = useState<CalendarDay | null>(null)
  const [notice, setNotice] = useState<{ message: string; undo?: CalendarDayChange } | null>(null)
  const owner = team.role === 'owner'

  useEffect(() => {
    if (!valid) return
    api<CalendarDay[]>(`/calendar/?team=${team.id}&start=${date}&days=1`).then(([loaded]) => setDay(loaded))
  }, [valid, team.id, date])

  // A generation of this week that ends while the page is open brings its proposal here too.
  useRealtimeEvent<GenerationEvent>('generation', (event) => {
    if (!valid || event.team !== team.id || event.status !== 'done') return
    if (event.week_start !== isoDate(mondayOf(fromIso(date)))) return
    api<CalendarDay[]>(`/calendar/?team=${team.id}&start=${date}&days=1`).then(([loaded]) => setDay(loaded))
  })

  const title = useDayTitle(valid ? date : '2026-01-01')
  if (!valid) return <Navigate to="/" replace />
  if (!day || day.date !== date) return <CircularProgress sx={{ display: 'block', mx: 'auto', mt: 6 }} />
  const which = meal as Meal

  async function change(update: CalendarDayChange, message = t('meal.saved')) {
    const before = snapshot(day!, [which])
    try {
      setDay(await changeDay(team.id, date!, update))
      setNotice({ message, undo: before })
    } catch {
      setNotice({ message: t('common.error') })
    }
  }

  async function review(action: 'accept' | 'reject') {
    try {
      await reviewMeal(team.id, date!, which, action)
      const [loaded] = await api<CalendarDay[]>(`/calendar/?team=${team.id}&start=${date}&days=1`)
      setDay(loaded)
      setNotice({ message: t(action === 'accept' ? 'generation.accepted' : 'generation.rejected') })
    } catch {
      setNotice({ message: t('common.error') })
    }
  }

  async function undo(previous: CalendarDayChange) {
    setNotice(null)
    try {
      setDay(await changeDay(team.id, date!, previous))
    } catch {
      setNotice({ message: t('common.error') })
    }
  }

  return (
    <Stack spacing={2.5}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <IconButton component={RouterLink} to={weekUrl(day.date)} aria-label={t('calendar.title')}>
          <ArrowBackIcon />
        </IconButton>
        <Stack sx={{ minWidth: 0 }}>
          <Typography variant="h1">{labels.meal(which)}</Typography>
          <Typography color="text.secondary">{title.weekday} {title.dayMonth}</Typography>
        </Stack>
      </Stack>
      {day.note && <Alert severity="info" icon={false}>{day.note}</Alert>}
      {hasProposal(day, which) && (
        <Alert severity="success" icon={false}
          action={
            <Stack direction="row" spacing={1}>
              <Button color="inherit" size="small" onClick={() => void review('reject')}>{t('generation.reject')}</Button>
              <Button variant="contained" size="small" onClick={() => void review('accept')}>{t('generation.accept')}</Button>
            </Stack>
          }>
          {t('generation.mealProposal')}
          {day.proposed_people[which] !== undefined && (
            <Typography variant="body2" sx={{ mt: 0.5 }}>
              {t('generation.peopleChange', { from: day.people[which], to: day.proposed_people[which] })}
              {day.people_notes[which] && ` — ${day.people_notes[which]}`}
            </Typography>
          )}
        </Alert>
      )}
      {!owner && <Alert severity="info">{t('meal.memberNotice')}</Alert>}
      <PeopleSection key={`${day.people[which]}`} day={day} meal={which} owner={owner} onChange={(u) => change(u)} />
      {day.dishes[which] ? (
        <DishesSection day={day} meal={which} owner={owner} onChange={(u) => change(u)} />
      ) : (
        <Typography variant="body2" color="text.secondary">{t('meal.breakfastHint')}</Typography>
      )}
      <Snackbar open={!!notice} autoHideDuration={notice?.undo ? 6000 : 3000} onClose={() => setNotice(null)}
        message={notice?.message}
        action={notice?.undo && (
          <Button color="inherit" size="small" onClick={() => void undo(notice.undo!)}>{t('calendar.undo')}</Button>
        )} />
    </Stack>
  )
}
