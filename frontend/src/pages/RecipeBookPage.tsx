import AddIcon from '@mui/icons-material/Add'
import ChangedIcon from '@mui/icons-material/EditOutlined'
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
  MenuItem,
  Pagination,
  Rating,
  Skeleton,
  Snackbar,
  Stack,
  TextField,
  Tooltip,
  Typography,
  useMediaQuery,
} from '@mui/material'
import { useTheme, type SxProps, type Theme } from '@mui/material/styles'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, useLocation, useNavigate } from 'react-router'
import { api, fromThisTab, type Paginated, type RecipeCard as RecipeCardData, type RecipeEvent } from '../api'
import { useFlash, withFlash } from '../flash'
import { useOnConnect, useRealtimeEvent } from '../realtime'
import { AddRecipeFab } from '../components/AddRecipeFab'
import { AuthorChip } from '../components/RecipeAuthor'
import { WebRating } from '../components/WebRating'
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

// What someone else just did to a card: shown over it while it pulses.
type Highlight = 'new' | 'changed'

function RecipeCard({ recipe: r, showInBook, flashSx }: {
  recipe: RecipeCardData
  showInBook: boolean
  flashSx: SxProps<Theme>
}) {
  const { t } = useTranslation()
  const labels = useLabels()
  return (
    <Card sx={withFlash({ height: '100%', position: 'relative' }, flashSx)}>

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
              {/* Chips: outlined for what the recipe is, green outline for what PlateMates says
                  (system recipe, in season), filled for where it stands in the team's book. */}
              <Chip size="small" variant="outlined" label={labels.course(r.course)} />
              {r.cuisine_name && <Chip size="small" variant="outlined" label={r.cuisine_name} />}
              {inSeasonNow(r.suitable_months) && (
                <Chip size="small" color="primary" variant="outlined" icon={<InSeasonIcon />}
                  label={t('book.inSeason')} />
              )}
              {/* The team's version of a community recipe shows where the original comes from. */}
              <AuthorChip author={r.author.kind === 'mine' && r.origin?.author ? r.origin.author : r.author} />
              {r.author.kind === 'mine' && r.origin && (
                <Chip size="small" icon={<ChangedIcon />} label={t('community.changedVersion')} />
              )}
              {showInBook && r.book && (
                <Chip size="small" icon={<CheckIcon />} label={t('community.inBook')} />
              )}
            </Box>
            {r.origin && r.author.kind !== 'mine' && (
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
              <WebRating rating={r.web_rating} count={r.web_rating_count} />
              {r.book?.rating != null && <Rating size="small" value={r.book.rating} readOnly />}
            </Stack>
          </Stack>
        </CardContent>
      </CardActionArea>
    </Card>
  )
}

const ORDERING_KEY = 'platemates.book.ordering'
type Ordering = 'title' | 'recent'
const PAGE_SIZE = 24
// How long a removed card takes to go, and a highlighted one keeps its chip.
const LEAVE_MS = 450
const HIGHLIGHT_MS = 3500

function storedOrdering(): Ordering {
  try {
    return localStorage.getItem(ORDERING_KEY) === 'recent' ? 'recent' : 'title'
  } catch {
    return 'title'
  }
}

export function RecipeBookPage() {
  const { t } = useTranslation()
  const labels = useLabels()
  const navigate = useNavigate()
  const { team } = useTeam()
  const phone = useMediaQuery(useTheme().breakpoints.down('sm'))
  const [search, setSearch] = useState('')
  const [course, setCourse] = useState<string | null>(null)
  const [inSeason, setInSeason] = useState(false)
  const [ordering, setOrdering] = useState<Ordering>(storedOrdering)
  const [page, setPage] = useState(1)
  const [entries, setEntries] = useState<RecipeCardData[] | null>(null)
  const [count, setCount] = useState(0)
  const [scope, setScope] = useState<Scope>(storedScope)
  const [error, setError] = useState(false)
  // Arriving from a recipe someone else deleted while it was open.
  const location = useLocation()
  const [notice, setNotice] = useState<string | null>(
    (location.state as { notice?: string } | null)?.notice === 'recipeDeleted' ? t('book.deletedNotice') : null,
  )
  // Real-time changes made by others: cards going away, cards just added or changed.
  const [leaving, setLeaving] = useState<Set<number>>(new Set())
  const [highlights, setHighlights] = useState<Map<number, Highlight>>(new Map())
  const { flash, flashSx } = useFlash()

  const query = useCallback(() => {
    const params = new URLSearchParams({
      team: String(team.id),
      mine: scope.mine ? '1' : '0',
      community: scope.community ? '1' : '0',
      page: String(page),
    })
    if (search.trim()) params.set('search', search.trim())
    if (course) params.set('course', course)
    if (inSeason) params.set('in_season', '1')
    if (ordering === 'recent') params.set('ordering', 'recent')
    return params
  }, [team.id, scope, page, search, course, inSeason, ordering])

  const load = useCallback(
    () => api<Paginated<RecipeCardData>>(`/recipes/browse/?${query()}`).then((result) => {
      setEntries(result.results)
      setCount(result.count)
      setError(false)
      return result.results
    }),
    [query],
  )

  useEffect(() => {
    let cancelled = false
    const timer = setTimeout(() => {
      load().catch(() => !cancelled && setError(true))
    }, 250)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [load])

  // Someone added, changed or removed a recipe this page may show: read the page again; a
  // card that goes fades out first, a new or changed one pulses under its chip. Not in the
  // tab that made the change, which updates quietly.
  useRealtimeEvent<RecipeEvent>('recipe', (event) => {
    if (event.team !== undefined && event.team !== team.id) return
    const mine = fromThisTab(event.origin)
    const shown = entries?.some((r) => r.id === event.recipe) ?? false
    const goes = event.action === 'deleted' || (event.action === 'book_removed' && !scope.community)
    if (goes && shown && !mine) {
      setLeaving((s) => new Set(s).add(event.recipe))
      setTimeout(() => {
        void load().finally(() => setLeaving((s) => { const n = new Set(s); n.delete(event.recipe); return n }))
      }, LEAVE_MS)
      return
    }
    void load().then((results) => {
      if (mine || goes || !results.some((r) => r.id === event.recipe)) return
      const kind: Highlight = event.action === 'updated' && shown ? 'changed' : 'new'
      setHighlights((h) => new Map(h).set(event.recipe, kind))
      flash([String(event.recipe)])
      setTimeout(() => setHighlights((h) => { const n = new Map(h); n.delete(event.recipe); return n }), HIGHLIGHT_MS)
    }).catch(() => undefined)
  })
  useOnConnect(() => void load().catch(() => undefined))

  function toggle(key: keyof Scope) {
    const next = { ...scope, [key]: !scope[key] }
    if (!next.mine && !next.community) return
    setScope(next)
    setPage(1)
    try {
      localStorage.setItem(SCOPE_KEY, JSON.stringify(next))
    } catch {
      // Not remembered: the choice still holds on this page.
    }
  }

  function order(value: Ordering) {
    setOrdering(value)
    setPage(1)
    try {
      localStorage.setItem(ORDERING_KEY, value)
    } catch {
      // Not remembered: the choice still holds on this page.
    }
  }

  const pages = Math.max(1, Math.ceil(count / PAGE_SIZE))
  const filtering = !!search.trim() || !!course || inSeason
  return (
    <Stack spacing={2.5}>
      <Typography variant="h1" sx={{ color: 'primary.main' }}>{t('book.title')}</Typography>

      <TextField
        placeholder={t('book.search')}
        value={search}
        onChange={(e) => { setSearch(e.target.value); setPage(1) }}
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
      <Stack direction="row" sx={{ alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
        {(['mine', 'community'] as const).map((key) => (
          <Chip key={key} label={t(`community.scope.${key}`)} onClick={() => toggle(key)}
            color={scope[key] ? 'primary' : 'default'} variant={scope[key] ? 'filled' : 'outlined'}
            icon={scope[key] ? <CheckIcon /> : undefined} aria-pressed={scope[key]} />
        ))}
        <Box sx={{ flex: 1 }} />
        <TextField select size="small" fullWidth={false} value={ordering} onChange={(e) => order(e.target.value as Ordering)}
          slotProps={{ htmlInput: { 'aria-label': t('book.ordering.label') } }} sx={{ width: 150 }}>
          <MenuItem value="title">{t('book.ordering.title')}</MenuItem>
          <MenuItem value="recent">{t('book.ordering.recent')}</MenuItem>
        </TextField>
        {pages > 1 && (
          <Pagination size="small" count={pages} page={page} onChange={(_, value) => setPage(value)}
            siblingCount={phone ? 0 : 1} boundaryCount={1} />
        )}
      </Stack>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
        {/* What PlateMates says (green outline), like the cards' own "in season" chip. */}
        <Chip
          icon={<InSeasonIcon />}
          label={t('book.inSeasonFilter')}
          color="primary"
          variant={inSeason ? 'filled' : 'outlined'}
          aria-pressed={inSeason}
          onClick={() => { setInSeason(!inSeason); setPage(1) }}
        />
        {COURSES.map((c) => (
          <Chip
            key={c}
            label={labels.course(c)}
            color={course === c ? 'primary' : 'default'}
            variant={course === c ? 'filled' : 'outlined'}
            onClick={() => { setCourse(course === c ? null : c); setPage(1) }}
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
              <Grid key={recipe.id} size={{ xs: 12, sm: 6, md: 4 }} sx={{
                position: 'relative',
                transition: `opacity ${LEAVE_MS}ms ease, transform ${LEAVE_MS}ms ease`,
                ...(leaving.has(recipe.id) && { opacity: 0, transform: 'scale(0.9)' }),
              }}>
                <RecipeCard recipe={recipe} showInBook={scope.community} flashSx={flashSx(String(recipe.id))} />
                {/* Over the card's top edge, like a label: it covers none of the card's own icons. */}
                {highlights.has(recipe.id) && (
                  <Chip size="small" color="primary" label={t(`book.highlight.${highlights.get(recipe.id)}`)}
                    sx={{ position: 'absolute', top: -11, right: 16, zIndex: 1, boxShadow: 2, pointerEvents: 'none' }} />
                )}
              </Grid>
            ))}
          </Grid>
          {pages > 1 && (
            <Pagination count={pages} page={page} onChange={(_, value) => { setPage(value); window.scrollTo({ top: 0 }) }}
              siblingCount={phone ? 0 : 1} sx={{ alignSelf: 'center' }} />
          )}
        </>
      )}

      <AddRecipeFab />
      <Snackbar open={!!notice} autoHideDuration={5000} onClose={() => setNotice(null)} message={notice} />
    </Stack>
  )
}
