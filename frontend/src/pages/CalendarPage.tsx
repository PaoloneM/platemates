import ChevronLeftIcon from '@mui/icons-material/ChevronLeft'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import PeopleIcon from '@mui/icons-material/PeopleOutlined'
import {
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Divider,
  IconButton,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, useSearchParams } from 'react-router'
import { api, type TeamProfile, type TypicalDay } from '../api'
import { MEALS, useLabels } from '../labels'
import { useTeam } from '../team'

// Dates are calendar days, not instants: always built and formatted in local time.
function mondayOf(date: Date): Date {
  const monday = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7))
  return monday
}

function addDays(date: Date, days: number): Date {
  const result = new Date(date)
  result.setDate(result.getDate() + days)
  return result
}

function isoDate(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function parseWeek(value: string | null, fallback: Date): Date {
  const match = value?.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  const date = match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : fallback
  return mondayOf(Number.isNaN(date.getTime()) ? fallback : date)
}

function DayCard({ date, day, today }: { date: Date; day: TypicalDay; today: boolean }) {
  const { t, i18n } = useTranslation()
  const labels = useLabels()
  const weekday = (date.getDay() + 6) % 7
  const dayMonth = new Intl.DateTimeFormat(i18n.resolvedLanguage, { day: 'numeric', month: 'short' }).format(date)

  return (
    <Card sx={{
      height: '100%', opacity: day.active ? 1 : 0.6,
      borderColor: today ? 'primary.main' : undefined, borderWidth: today ? 2 : undefined,
    }}>
      <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
        <Stack direction={{ xs: 'row', md: 'column' }} sx={{ alignItems: { xs: 'baseline', md: 'flex-start' }, gap: { xs: 1, md: 0 }, mb: 1 }}>
          <Typography variant="h3" sx={{ color: today ? 'primary.main' : undefined }}>
            {labels.weekday(weekday)}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {today ? t('calendar.today', { date: dayMonth }) : dayMonth}
          </Typography>
        </Stack>
        <Divider sx={{ mb: 1 }} />
        {day.active ? (
          <Stack spacing={0.75}>
            {MEALS.map((meal) => (
              <Stack key={meal} direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', gap: 1 }}>
                <Typography variant="body2">{labels.meal(meal)}</Typography>
                {day[meal] > 0 ? (
                  <Tooltip title={t('calendar.people', { count: day[meal] })}>
                    <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
                      <PeopleIcon fontSize="small" color="action" />
                      <Typography variant="body2" sx={{ fontWeight: 600, minWidth: 16, textAlign: 'right' }}>
                        {day[meal]}
                      </Typography>
                    </Stack>
                  </Tooltip>
                ) : (
                  <Typography variant="body2" color="text.secondary" aria-label={t('calendar.nobody')}
                    sx={{ minWidth: 16, textAlign: 'right' }}>
                    –
                  </Typography>
                )}
              </Stack>
            ))}
          </Stack>
        ) : (
          <Typography variant="body2" color="text.secondary">{t('calendar.dayOff')}</Typography>
        )}
      </CardContent>
    </Card>
  )
}

export function CalendarPage() {
  const { t, i18n } = useTranslation()
  const { team: current } = useTeam()
  const [team, setTeam] = useState<TeamProfile | null>(null)
  const [params, setParams] = useSearchParams()
  // Read once per visit: "today" does not need to follow the clock while the page is open.
  const [today] = useState(() => new Date())
  const monday = parseWeek(params.get('week'), today)
  const thisMonday = mondayOf(today)
  const todayIso = isoDate(today)

  useEffect(() => {
    api<TeamProfile>(`/teams/${current.id}/`).then(setTeam)
  }, [current.id])

  const goTo = (date: Date) =>
    setParams(isoDate(date) === isoDate(thisMonday) ? {} : { week: isoDate(date) })

  const range = new Intl.DateTimeFormat(i18n.resolvedLanguage, { day: 'numeric', month: 'long' })
  const title = t('calendar.week', { start: range.format(monday), end: range.format(addDays(monday, 6)) })

  return (
    <Stack spacing={2}>
      <Stack direction="row" sx={{ alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
        <Typography variant="h1" sx={{ flex: 1, minWidth: 0 }}>{t('calendar.title')}</Typography>
        {team?.my_role === 'owner' && (
          <Button component={RouterLink} to="/team#week" size="small">{t('calendar.editWeek')}</Button>
        )}
      </Stack>
      <Stack direction="row" sx={{ alignItems: 'center', gap: 1 }}>
        <IconButton onClick={() => goTo(addDays(monday, -7))} aria-label={t('calendar.previous')}>
          <ChevronLeftIcon />
        </IconButton>
        <Typography variant="h2" sx={{ flex: 1, textAlign: 'center' }}>{title}</Typography>
        <IconButton onClick={() => goTo(addDays(monday, 7))} aria-label={t('calendar.next')}>
          <ChevronRightIcon />
        </IconButton>
      </Stack>
      {isoDate(monday) !== isoDate(thisMonday) && (
        <Box sx={{ textAlign: 'center' }}>
          <Button size="small" onClick={() => goTo(thisMonday)}>{t('calendar.thisWeek')}</Button>
        </Box>
      )}
      {!team ? (
        <CircularProgress sx={{ display: 'block', mx: 'auto', mt: 4 }} />
      ) : (
        <Box sx={{
          display: 'grid', gap: 1.5,
          gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)', lg: 'repeat(7, 1fr)' },
        }}>
          {team.typical_week.map((day, index) => {
            const date = addDays(monday, index)
            return <DayCard key={index} date={date} day={day} today={isoDate(date) === todayIso} />
          })}
        </Box>
      )}
      <Typography variant="body2" color="text.secondary">{t('calendar.hint')}</Typography>
    </Stack>
  )
}
