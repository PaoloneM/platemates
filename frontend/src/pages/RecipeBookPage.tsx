import AddIcon from '@mui/icons-material/Add'
import CheckIcon from '@mui/icons-material/Check'
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
import { api, type Paginated, type RecipeCard as RecipeCardData } from '../api'
import { AddRecipeFab } from '../components/AddRecipeFab'
import { AuthorChip } from '../components/RecipeAuthor'
import { useTeam } from '../team'
import { COURSES, useLabels } from '../labels'

const CURRENT_MONTH = new Date().getMonth() + 1

/** Seasonal now: the recipe has a season at all, and the current month is in it. */
function inSeasonNow(months: number[]) {
  return months.length > 0 && months.includes(CURRENT_MONTH)
}

type Scope = { mine: boolean; community: boolean }
const SCOPE_KEY = 'platemates.book.scope'

function storedScope(): Scope {
  try {
    const value = JSON.parse(localStorage.getItem(SCOPE_KEY) ?? '')
    if (value && (value.mine || value.community)) return { mine: !!value.mine, community: !!value.community }
  } catch {
    // Not remembered: start from the recipe book.
  }
  return { mine: true, community: false }
}

function RecipeCard({ recipe: r, showInBook }: { recipe: RecipeCardData; showInBook: boolean }) {
  const { t } = useTranslation()
  const labels = useLabels()
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
              {inSeasonNow(r.suitable_months) && (
                <Chip size="small" color="primary" variant="outlined" icon={<InSeasonIcon />}
                  label={t('book.inSeason')} />
              )}
              <AuthorChip author={r.author} />
              {showInBook && r.book && <Chip size="small" icon={<CheckIcon />} label={t('community.inBook')} />}
            </Box>
            {r.origin && (
              <Typography variant="body2" color="text.secondary">
                {t('community.variantOf', { title: r.origin.title })}
              </Typography>
            )}
            <Stack direction="row" spacing={2} sx={{ alignItems: 'center', color: 'text.secondary' }}>
              {r.total_minutes != null && (
                <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
                  <TimerIcon fontSize="small" />
                  <Typography variant="body2">{t('recipe.minutes', { count: r.total_minutes })}</Typography>
                </Stack>
              )}
              <Typography variant="body2">{t('recipe.servings', { count: r.servings })}</Typography>
              {r.book?.rating != null && <Rating size="small" value={r.book.rating} readOnly />}
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
  const { team } = useTeam()
  const [search, setSearch] = useState('')
  const [course, setCourse] = useState<string | null>(null)
  const [entries, setEntries] = useState<RecipeCardData[] | null>(null)
  const [scope, setScope] = useState<Scope>(storedScope)
  const [next, setNext] = useState<string | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    const params = new URLSearchParams({
      team: String(team.id),
      mine: scope.mine ? '1' : '0',
      community: scope.community ? '1' : '0',
    })
    if (search.trim()) params.set('search', search.trim())
    if (course) params.set('course', course)
    let cancelled = false
    const timer = setTimeout(() => {
      api<Paginated<RecipeCardData>>(`/recipes/browse/?${params}`)
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
  }, [team.id, search, course, scope])

  /** Switch one source on or off; at least one stays on. */
  function toggle(key: keyof Scope) {
    const next = { ...scope, [key]: !scope[key] }
    if (!next.mine && !next.community) return
    setScope(next)
    try {
      localStorage.setItem(SCOPE_KEY, JSON.stringify(next))
    } catch {
      // Not remembered: the choice still holds on this page.
    }
  }

  async function loadMore() {
    if (!next) return
    const url = new URL(next)
    const page = await api<Paginated<RecipeCardData>>(url.pathname.replace(/^\/api/, '') + url.search)
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
      <Stack direction="row" spacing={1}>
        {(['mine', 'community'] as const).map((key) => (
          <Chip key={key} label={t(`community.scope.${key}`)} onClick={() => toggle(key)}
            color={scope[key] ? 'primary' : 'default'} variant={scope[key] ? 'filled' : 'outlined'}
            icon={scope[key] ? <CheckIcon /> : undefined} aria-pressed={scope[key]} />
        ))}
      </Stack>
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
          <Typography variant="h3">
            {filtering ? t('book.noMatch') : scope.mine ? t('book.empty') : t('community.empty')}
          </Typography>
          {!filtering && scope.mine && (
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
            {entries.map((recipe) => (
              <Grid key={recipe.id} size={{ xs: 12, sm: 6, md: 4 }}>
                <RecipeCard recipe={recipe} showInBook={scope.community} />
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

      <AddRecipeFab />
    </Stack>
  )
}
