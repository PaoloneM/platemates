import AddIcon from '@mui/icons-material/Add'
import InSeasonIcon from '@mui/icons-material/Grass'
import LockIcon from '@mui/icons-material/LockOutlined'
import SearchIcon from '@mui/icons-material/Search'
import TimerIcon from '@mui/icons-material/TimerOutlined'
import {
  Alert,
  Box,
  Button,
  Card,
  CardActionArea,
  CardContent,
  Chip,
  Fab,
  Grid,
  InputAdornment,
  Rating,
  Skeleton,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, useNavigate } from 'react-router'
import { api, type BookEntry, type Paginated } from '../api'
import { useFamily } from '../family'
import { COURSES, useLabels } from '../labels'

const CURRENT_MONTH = new Date().getMonth() + 1

function inSeason(months: number[]) {
  return months.length === 0 || months.includes(CURRENT_MONTH)
}

function RecipeCard({ entry }: { entry: BookEntry }) {
  const { t } = useTranslation()
  const labels = useLabels()
  const r = entry.recipe_summary
  return (
    <Card sx={{ height: '100%' }}>
      <CardActionArea component={RouterLink} to={`/recipes/${r.id}`} sx={{ height: '100%' }}>
        <CardContent>
          <Stack spacing={1}>
            <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
              <Typography variant="h3" sx={{ flex: 1 }}>
                {r.title}
              </Typography>
              {r.visibility === 'private' && (
                <Tooltip title={t('recipe.private')}>
                  <LockIcon fontSize="small" color="action" />
                </Tooltip>
              )}
            </Stack>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75 }}>
              <Chip size="small" label={labels.course(r.course)} />
              {r.cuisine_name && <Chip size="small" variant="outlined" label={r.cuisine_name} />}
              {inSeason(r.season_months) && r.season_months.length > 0 && (
                <Chip size="small" color="primary" variant="outlined" icon={<InSeasonIcon />}
                  label={t('book.inSeason')} />
              )}
            </Box>
            <Stack direction="row" spacing={2} sx={{ alignItems: 'center', color: 'text.secondary' }}>
              {r.total_minutes != null && (
                <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
                  <TimerIcon fontSize="small" />
                  <Typography variant="body2">{t('recipe.minutes', { count: r.total_minutes })}</Typography>
                </Stack>
              )}
              <Typography variant="body2">{t('recipe.servings', { count: r.servings })}</Typography>
              {entry.rating != null && <Rating size="small" value={entry.rating} readOnly />}
            </Stack>
          </Stack>
        </CardContent>
      </CardActionArea>
    </Card>
  )
}

export function RecipeBookPage() {
  const { t } = useTranslation()
  const labels = useLabels()
  const navigate = useNavigate()
  const { family } = useFamily()
  const [search, setSearch] = useState('')
  const [course, setCourse] = useState<string | null>(null)
  const [entries, setEntries] = useState<BookEntry[] | null>(null)
  const [next, setNext] = useState<string | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    const params = new URLSearchParams({ family: String(family.id), status: 'approved' })
    if (search.trim()) params.set('search', search.trim())
    if (course) params.set('course', course)
    let cancelled = false
    const timer = setTimeout(() => {
      api<Paginated<BookEntry>>(`/recipe-book/?${params}`)
        .then((page) => {
          if (cancelled) return
          setEntries(page.results)
          setNext(page.next)
          setError(false)
        })
        .catch(() => !cancelled && setError(true))
    }, 250)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [family.id, search, course])

  async function loadMore() {
    if (!next) return
    const url = new URL(next)
    const page = await api<Paginated<BookEntry>>(url.pathname.replace(/^\/api/, '') + url.search)
    setEntries((current) => [...(current ?? []), ...page.results])
    setNext(page.next)
  }

  const filtering = !!search.trim() || !!course
  return (
    <Stack spacing={2.5}>
      <Typography variant="h1">{t('book.title')}</Typography>

      <TextField
        placeholder={t('book.search')}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        slotProps={{
          input: {
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon />
              </InputAdornment>
            ),
          },
        }}
      />
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
        {COURSES.map((c) => (
          <Chip
            key={c}
            label={labels.course(c)}
            color={course === c ? 'primary' : 'default'}
            variant={course === c ? 'filled' : 'outlined'}
            onClick={() => setCourse(course === c ? null : c)}
          />
        ))}
      </Box>

      {error && <Alert severity="error">{t('common.error')}</Alert>}

      {entries === null ? (
        <Grid container spacing={2}>
          {[0, 1, 2].map((i) => (
            <Grid key={i} size={{ xs: 12, sm: 6, md: 4 }}>
              <Skeleton variant="rounded" height={120} />
            </Grid>
          ))}
        </Grid>
      ) : entries.length === 0 ? (
        <Stack spacing={2} sx={{ alignItems: 'center', py: 6, textAlign: 'center' }}>
          <Typography variant="h3">{filtering ? t('book.noMatch') : t('book.empty')}</Typography>
          {!filtering && (
            <>
              <Typography color="text.secondary">{t('book.emptyHint')}</Typography>
              <Button variant="contained" startIcon={<AddIcon />} onClick={() => navigate('/recipes/new')}>
                {t('book.addFirst')}
              </Button>
            </>
          )}
        </Stack>
      ) : (
        <>
          <Grid container spacing={2}>
            {entries.map((entry) => (
              <Grid key={entry.id} size={{ xs: 12, sm: 6, md: 4 }}>
                <RecipeCard entry={entry} />
              </Grid>
            ))}
          </Grid>
          {next && (
            <Button onClick={loadMore} sx={{ alignSelf: 'center' }}>
              {t('book.loadMore')}
            </Button>
          )}
        </>
      )}

      <Fab
        color="primary"
        aria-label={t('book.add')}
        onClick={() => navigate('/recipes/new')}
        sx={{ position: 'fixed', right: { xs: 16, sm: 32 }, bottom: { xs: 16, sm: 32 } }}
      >
        <AddIcon />
      </Fab>
    </Stack>
  )
}
