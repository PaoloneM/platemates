import CartIcon from '@mui/icons-material/AddShoppingCartOutlined'
import AddIcon from '@mui/icons-material/Add'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import CheckIcon from '@mui/icons-material/Check'
import DeleteIcon from '@mui/icons-material/DeleteOutlined'
import EditIcon from '@mui/icons-material/EditOutlined'
import LockIcon from '@mui/icons-material/LockOutlined'
import PublicIcon from '@mui/icons-material/PublicOutlined'
import PromoteIcon from '@mui/icons-material/UpgradeOutlined'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  IconButton,
  Link,
  Rating,
  Stack,
  Tab,
  Tabs,
  Tooltip,
  Typography,
  useMediaQuery,
  useTheme,
} from '@mui/material'
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, Navigate, useNavigate, useParams, useSearchParams } from 'react-router'
import { api, fromThisTab, type KitchenTool, type Recipe, type RecipeEvent, type RecipeVariants } from '../api'
import { useAuth } from '../auth/context'
import { useNewShoppingList } from '../components/NewShoppingList'
import { AuthorChip } from '../components/RecipeAuthor'
import { WebRating } from '../components/WebRating'
import { IngredientList, PeopleStepper, StepList } from '../components/RecipeView'
import { compareIngredients } from '../recipeDiff'
import { useTeam } from '../team'
import { useFlash, withFlash } from '../flash'
import { useOnConnect, useRealtimeEvent } from '../realtime'
import { useDescribeMonths, useLabels } from '../labels'

type Tab = 'mine' | 'original'

/** Which part of the page shows a recipe's field, for highlighting a change to it. */
function recipePart(field: string): string {
  if (['ingredients', 'servings', 'tools', 'season_months', 'climate_months'].includes(field)) return 'ingredients'
  if (field === 'steps' || field === 'description') return field
  return 'header'
}

// A page action: a labelled button, or an icon with a tooltip in compact mode.
type Action = {
  key: string
  label: string
  icon: ReactNode
  to?: string
  onClick?: () => void
  color?: 'primary' | 'error'
  primary?: boolean
}

function ActionBar({ actions, compact }: { actions: Action[]; compact: boolean }) {
  return (
    // Right-aligned, in a fixed order: the last action keeps its place when an earlier one is
    // missing or changes label (switching tab, phone layout).
    <Stack direction="row" spacing={compact ? 0.5 : 1}
      sx={{ flexWrap: 'wrap', rowGap: 1, justifyContent: 'flex-end', alignItems: 'center', flexShrink: 0 }}>
      {actions.map((action) => {
        const link = action.to ? { component: RouterLink, to: action.to } : { onClick: action.onClick }
        return compact ? (
          <Tooltip key={action.key} title={action.label}>
            <IconButton aria-label={action.label} color={action.color ?? 'primary'} {...link}>
              {action.icon}
            </IconButton>
          </Tooltip>
        ) : (
          <Button key={action.key} variant={action.primary ? 'contained' : 'outlined'}
            color={action.color ?? 'primary'} startIcon={action.icon} {...link}>
            {action.label}
          </Button>
        )
      })}
    </Stack>
  )
}

/**
 * A recipe, as the team sees it:
 * - its own recipe: edit it, remove it from the book;
 * - a community recipe not in the book: add it to the book (staff may also edit the original);
 * - a community recipe in the book: two tabs, "your version" (the default) and "original". The
 *   version is the original itself until the team changes it ("edit" then creates the team's
 *   copy); after that it is the team's copy, and the original's page leads here,
 *   on "your version". Removing it
 *   from the book warns that the changes would be lost.
 */
export function RecipeDetailPage() {
  const { t } = useTranslation()
  const labels = useLabels()
  const describeMonths = useDescribeMonths()
  const navigate = useNavigate()
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const { team } = useTeam()
  const { me } = useAuth()
  const phone = useMediaQuery(useTheme().breakpoints.down('sm'))
  const compactMode = me?.authenticated ? me.settings['ui.compact_actions'] : undefined
  const compact = compactMode === 'always' || (compactMode === 'mobile' && phone)
  const [recipe, setRecipe] = useState<Recipe | null>(null)
  const [error, setError] = useState(false)
  const [people, setPeople] = useState<number | null>(null)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const shopping = useNewShoppingList()
  const [allTools, setAllTools] = useState<KitchenTool[]>([])
  const [variants, setVariants] = useState<RecipeVariants | null>(null)
  // The original of the team's copy, shown in the second tab.
  const [original, setOriginal] = useState<Recipe | null>(null)
  const tab: Tab = params.get('tab') === 'original' ? 'original' : 'mine'
  const setTab = (value: Tab) => setParams(value === 'original' ? { tab: 'original' } : {}, { replace: true })

  useEffect(() => {
    api<KitchenTool[]>('/kitchen-tools/').then(setAllTools).catch(() => undefined)
  }, [])

  // Someone changed this recipe or its original: read them again, then show which parts.
  const [originalRound, setOriginalRound] = useState(0)
  const { flash, flashSx } = useFlash()

  // The team's copy of a community recipe: its original is the second tab.
  const originId = recipe?.author.kind === 'mine' ? recipe.origin?.id : undefined
  useEffect(() => {
    if (originId === undefined) return
    let cancelled = false
    api<Recipe>(`/recipes/${originId}/`)
      .then((r) => !cancelled && setOriginal(r))
      .catch(() => !cancelled && setOriginal(null))
    return () => {
      cancelled = true
    }
  }, [originId, originalRound])

  useEffect(() => {
    api<RecipeVariants>(`/recipes/${id}/variants/`).then(setVariants).catch(() => setVariants(null))
  }, [id])

  useEffect(() => {
    api<Recipe>(`/recipes/${id}/`)
      .then((r) => {
        setRecipe(r)
        setPeople(r.servings)
      })
      .catch(() => setError(true))
  }, [id])

  // Reading the recipe again keeps the people chosen for the quantities.
  const reload = useCallback(
    () => api<Recipe>(`/recipes/${id}/`).then((r) => {
      setRecipe(r)
      setOriginalRound((n) => n + 1)
    }),
    [id],
  )
  useRealtimeEvent<RecipeEvent>('recipe', (event) => {
    if (!recipe || (event.recipe !== recipe.id && event.recipe !== recipe.origin?.id)) return
    void reload().then(() => {
      if (!fromThisTab(event.origin)) flash([...new Set(event.fields.map(recipePart))])
    }).catch(() => undefined)
  })
  useOnConnect(() => void reload().catch(() => undefined))

  if (error) return <Alert severity="error">{t('recipe.notFound')}</Alert>
  if (!recipe || people == null) return <CircularProgress sx={{ display: 'block', mx: 'auto', mt: 6 }} />
  // The original of a recipe the team has changed: the team's page for it is its version.
  if (recipe.author.kind !== 'mine' && recipe.my_version) {
    return <Navigate to={`/recipes/${recipe.my_version.id}`} replace />
  }

  const entry = recipe.book_entries.find((e) => e.team === team.id)
  // When the recipe is the team's changed copy: its original, once loaded.
  const originalOfCopy = recipe.author.kind === 'mine' && recipe.origin
    ? (original?.id === recipe.origin.id ? original : null) : null
  const isCopy = originalOfCopy !== null
  const reference = recipe.author.kind !== 'mine' && !!entry
  const tabbed = isCopy || reference
  // In the tabs: the team's version, and the original (the same recipe until it is changed).
  const theOriginal = originalOfCopy ?? recipe
  const shown = tabbed && tab === 'original' ? theOriginal : recipe
  const diff = originalOfCopy ? compareIngredients(recipe, originalOfCopy) : null
  const tools = allTools.filter((tool) => shown.tools.includes(tool.id))
  const suitable = shown.season_months.months.length === 0
    ? shown.climate_months.months
    : shown.climate_months.months.length === 0
      ? shown.season_months.months
      : shown.season_months.months.filter((m) => shown.climate_months.months.includes(m))

  async function rate(value: number | null) {
    if (!entry) return
    await api(`/recipe-book/${entry.id}/`, { method: 'PATCH', body: JSON.stringify({ rating: value }) })
    setRecipe((r) => r && {
      ...r,
      book_entries: r.book_entries.map((e) => (e.id === entry.id ? { ...e, rating: value } : e)),
    })
  }

  async function addToBook() {
    const created = await api<{ id: number }>('/recipe-book/', {
      method: 'POST',
      body: JSON.stringify({ team: team.id, recipe: recipe!.id, status: 'approved' }),
    })
    setRecipe((r) => r && {
      ...r,
      book_entries: [...r.book_entries, { id: created.id, team: team.id, status: 'approved', rating: null }],
    })
  }

  async function removeFromBook() {
    if (!entry) return
    await api(`/recipe-book/${entry.id}/`, { method: 'DELETE' })
    // The team's copy is gone with it: back to the original, still in the community.
    navigate(originalOfCopy ? `/recipes/${originalOfCopy.id}` : '/recipes', { replace: true })
  }

  // Changing the team's version: its copy, or the first change, which creates the copy.
  const editMine = isCopy ? `/recipes/${recipe.id}/edit` : `/recipes/new?from=${recipe.id}`
  const canEditOriginal = tabbed ? theOriginal.can_edit : recipe.can_edit
  // Always "edit" first, then "remove" or "add": only the edit action depends on the tab.
  const actions: Action[] = []
  // First, left of the others: a shopping list for the recipe on screen (the tab's), for the
  // people chosen beside the ingredients.
  const shopFor = people ?? shown.servings
  actions.push({
    key: 'shopping', icon: <CartIcon />, label: t('shopping.forRecipe'),
    onClick: () => void shopping.create({
      recipe: shown.id, people: shopFor, title: t('shopping.recipeTitle', { title: shown.title, count: shopFor }),
    }),
  })
  if (tabbed && tab === 'mine') {
    actions.push({
      key: 'edit', to: editMine, icon: <EditIcon />, primary: true,
      label: canEditOriginal ? t('community.editMineStaff') : t('common.edit'),
    })
  } else if (recipe.author.kind === 'mine' && !tabbed) {
    actions.push({ key: 'edit', to: `/recipes/${recipe.id}/edit`, icon: <EditIcon />, primary: true, label: t('common.edit') })
  } else if (canEditOriginal) {
    actions.push({ key: 'edit', to: `/recipes/${theOriginal.id}/edit`, icon: <EditIcon />, label: t('community.editOriginal') })
  }
  // Staff: the recipe on screen (a team's, or a team's version) becomes a system recipe,
  // reviewed in the editor first.
  const promotable = tabbed && tab === 'original' ? theOriginal : recipe
  if (me?.authenticated && me.user.is_staff && promotable.author.kind !== 'system') {
    actions.push({
      key: 'promote', to: `/recipes/new?promote=${promotable.id}`, icon: <PromoteIcon />,
      label: t('community.promote'),
    })
  }
  if (entry) {
    actions.push({
      key: 'remove', color: 'error', icon: <DeleteIcon />, label: t('recipe.removeFromBook'),
      onClick: () => setConfirmRemove(true),
    })
  } else if (recipe.author.kind !== 'mine') {
    actions.push({ key: 'add', icon: <AddIcon />, primary: true, label: t('recipe.addToBook'), onClick: () => void addToBook() })
  }
  // Compact mode: the icons sit beside the tabs, or beside the title on a page without tabs.
  const actionBar = <ActionBar actions={actions} compact={compact} />

  return (
    <Stack spacing={3}>
      <Box>
        <Button component={RouterLink} to="/recipes" startIcon={<ArrowBackIcon />}>
          {t('book.title')}
        </Button>
      </Box>

      <Stack direction={compact ? 'row' : { xs: 'column', sm: 'row' }} spacing={2}
        sx={{ alignItems: compact ? 'flex-start' : { sm: 'flex-start' } }}>
        {/* The header describes the recipe the team has (its version): it stays put across tabs. */}
        <Stack spacing={1.5} sx={withFlash({ flex: 1, minWidth: 0, borderRadius: 1 }, flashSx('header'))}>
          <Typography variant="h1">{recipe.title}</Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
            <Chip variant="outlined" label={labels.course(recipe.course)} />
            {recipe.cuisine_name && <Chip variant="outlined" label={recipe.cuisine_name} />}
            {recipe.total_minutes != null && (
              <Chip variant="outlined" label={t('recipe.minutes', { count: recipe.total_minutes })} />
            )}
            {recipe.author.kind === 'mine' && !isCopy && (
              <Chip
                variant="outlined"
                icon={recipe.visibility === 'private' ? <LockIcon /> : <PublicIcon />}
                label={recipe.visibility === 'private' ? t('recipe.private') : t('recipe.shared')}
              />
            )}
            <AuthorChip author={theOriginal.author} size="medium" />
            {tabbed && (
              <Chip icon={isCopy ? <EditIcon /> : <CheckIcon />}
                label={isCopy ? t('community.changedVersion') : t('community.sameAsOriginal')} />
            )}
          </Box>
          {recipe.origin && !isCopy && (
            <Typography color="text.secondary">
              {t('community.variantOfPrefix')}{' '}
              <Link component={RouterLink} to={`/recipes/${recipe.origin.id}`}>{recipe.origin.title}</Link>
            </Typography>
          )}
          <WebRating rating={theOriginal.web_rating} count={theOriginal.web_rating_count} />
          {entry && (
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
              <Typography variant="body2" color="text.secondary">
                {t('recipe.yourRating')}
              </Typography>
              <Rating value={entry.rating} onChange={(_, v) => void rate(v)} />
            </Stack>
          )}
        </Stack>
        {!(compact && tabbed) && actionBar}
      </Stack>

      {!tabbed && recipe.description && (
        <Typography color="text.secondary" sx={withFlash({ borderRadius: 1 }, flashSx('description'))}>{recipe.description}</Typography>
      )}
      {tabbed && (
        <Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, borderBottom: 1, borderColor: 'divider' }}>
            <Tabs value={tab} onChange={(_, value) => setTab(value)} sx={{ flex: 1, minWidth: 0 }}>
              <Tab value="mine" label={t('community.yourVersion')} />
              <Tab value="original" label={t('community.original')} />
            </Tabs>
            {compact && actionBar}
          </Box>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
            {tab === 'original'
              ? t('community.originalHint')
              : !isCopy
                ? t('community.notChangedYet')
                : diff && Object.keys(diff.inVariant).length + Object.keys(diff.inOriginal).length === 0 && diff.sameSteps
                  ? t('community.noDifferences')
                  : t('community.differencesHint')}
          </Typography>
          {/* What the tabs switch: the description, the ingredients and the steps. */}
          {shown.description && (
            <Typography color="text.secondary" sx={withFlash({ mt: 1.5, borderRadius: 1 }, flashSx('description'))}>{shown.description}</Typography>
          )}
        </Box>
      )}

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 5 }}>
          <Card sx={flashSx('ingredients')}>
            <CardContent>
              <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                <Typography variant="h2">{t('recipe.ingredients')}</Typography>
                <PeopleStepper people={people} onChange={setPeople} />
              </Stack>
              <IngredientList recipe={shown} people={people}
                marks={diff ? (shown === recipe ? diff.inVariant : diff.inOriginal) : undefined} />
              <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
                {t('recipe.season')}: {describeMonths(suitable)}
              </Typography>
              {tools.length > 0 && (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                  {t('recipe.tools')}: {tools.map(labels.tool).join(', ')}
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, md: 7 }}>
<Box sx={withFlash({ borderRadius: 1 }, flashSx('steps'))}>
                    <Typography variant="h2" sx={{ mb: 1.5 }}>
              {t('recipe.steps')}
            </Typography>
            {diff && !diff.sameSteps && (
              <Chip size="small" variant="outlined" color="warning" label={t('community.stepsDiffer')} sx={{ mb: 1.5 }} />
            )}
            <StepList recipe={shown} />
          </Box>
          {shown.source_url && (
            <Typography variant="body2" sx={{ mt: 3 }}>
              {t('recipe.source')}:{' '}
              <Link href={shown.source_url} target="_blank" rel="noopener noreferrer">
                {new URL(shown.source_url).hostname}
              </Link>
            </Typography>
          )}
        </Grid>
      </Grid>

      {variants && variants.variants.length > 0 && (
        <Stack spacing={1}>
          <Typography variant="h2">{t('community.variants', { count: variants.variants.length })}</Typography>
          <Typography variant="body2" color="text.secondary">
            {recipe.origin ? t('community.variantsOfOriginalHint') : t('community.variantsHint')}
          </Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
            {variants.variants.map((variant) => (
              <Chip key={variant.id} component={RouterLink} to={`/recipes/${variant.id}`} clickable
                label={variant.author.kind === 'team' || variant.author.kind === 'mine'
                  ? `${variant.title} · ${variant.author.name}` : variant.title} />
            ))}
          </Box>
        </Stack>
      )}

      {shopping.snackbar}
      <Dialog open={confirmRemove} onClose={() => setConfirmRemove(false)}>
        <DialogTitle>{t('recipe.removeTitle')}</DialogTitle>
        <DialogContent>
          <Typography>
            {isCopy
              ? t('community.removeChanged')
              : reference
                ? t('community.removeReference')
                : recipe.visibility === 'private' ? t('recipe.removePrivate') : t('recipe.removeShared')}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmRemove(false)}>{t('common.cancel')}</Button>
          <Button color="error" variant="contained" onClick={() => void removeFromBook()}>
            {t('recipe.removeFromBook')}
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  )
}
