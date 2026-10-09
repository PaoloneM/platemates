import AddIcon from '@mui/icons-material/Add'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import DeleteIcon from '@mui/icons-material/DeleteOutlined'
import EditIcon from '@mui/icons-material/EditOutlined'
import ImportIcon from '@mui/icons-material/ContentCopy'
import LockIcon from '@mui/icons-material/LockOutlined'
import PublicIcon from '@mui/icons-material/PublicOutlined'
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
  Link,
  Rating,
  Stack,
  Typography,
} from '@mui/material'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, useNavigate, useParams } from 'react-router'
import { api, type KitchenTool, type Recipe, type RecipeVariants } from '../api'
import { AuthorChip } from '../components/RecipeAuthor'
import { WebRating } from '../components/WebRating'
import { IngredientList, PeopleStepper, StepList } from '../components/RecipeView'
import { useTeam } from '../team'
import { useDescribeMonths, useLabels } from '../labels'

export function RecipeDetailPage() {
  const { t } = useTranslation()
  const labels = useLabels()
  const describeMonths = useDescribeMonths()
  const navigate = useNavigate()
  const { id } = useParams()
  const { team } = useTeam()
  const [recipe, setRecipe] = useState<Recipe | null>(null)
  const [error, setError] = useState(false)
  const [people, setPeople] = useState<number | null>(null)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const [allTools, setAllTools] = useState<KitchenTool[]>([])
  const [variants, setVariants] = useState<RecipeVariants | null>(null)

  useEffect(() => {
    api<KitchenTool[]>('/kitchen-tools/').then(setAllTools).catch(() => undefined)
  }, [])

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

  if (error) return <Alert severity="error">{t('recipe.notFound')}</Alert>
  if (!recipe || people == null) return <CircularProgress sx={{ display: 'block', mx: 'auto', mt: 6 }} />

  const entry = recipe.book_entries.find((e) => e.team === team.id)
  const tools = allTools.filter((tool) => recipe.tools.includes(tool.id))
  const suitable = recipe.season_months.months.length === 0
    ? recipe.climate_months.months
    : recipe.climate_months.months.length === 0
      ? recipe.season_months.months
      : recipe.season_months.months.filter((m) => recipe.climate_months.months.includes(m))

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
    navigate('/recipes', { replace: true })
  }

  return (
    <Stack spacing={3}>
      <Box>
        <Button component={RouterLink} to="/recipes" startIcon={<ArrowBackIcon />}>
          {t('book.title')}
        </Button>
      </Box>

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ alignItems: { sm: 'flex-start' } }}>
        <Stack spacing={1.5} sx={{ flex: 1 }}>
          <Typography variant="h1">{recipe.title}</Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
            <Chip label={labels.course(recipe.course)} />
            {recipe.cuisine_name && <Chip variant="outlined" label={recipe.cuisine_name} />}
            {recipe.total_minutes != null && (
              <Chip variant="outlined" label={t('recipe.minutes', { count: recipe.total_minutes })} />
            )}
            {recipe.author.kind === 'mine' && (
              <Chip
                variant="outlined"
                icon={recipe.visibility === 'private' ? <LockIcon /> : <PublicIcon />}
                label={recipe.visibility === 'private' ? t('recipe.private') : t('recipe.shared')}
              />
            )}
            <AuthorChip author={recipe.author} size="medium" />
          </Box>
          {recipe.origin && (
            <Typography color="text.secondary">
              {t('community.variantOfPrefix')}{' '}
              <Link component={RouterLink} to={`/recipes/${recipe.origin.id}`}>{recipe.origin.title}</Link>
            </Typography>
          )}
          <WebRating rating={recipe.web_rating} count={recipe.web_rating_count} />
          {recipe.description && <Typography color="text.secondary">{recipe.description}</Typography>}
          {entry && (
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
              <Typography variant="body2" color="text.secondary">
                {t('recipe.yourRating')}
              </Typography>
              <Rating value={entry.rating} onChange={(_, v) => void rate(v)} />
            </Stack>
          )}
        </Stack>
        <Stack direction="row" spacing={1}>
          {recipe.can_edit && (
            <Button variant="contained" startIcon={<EditIcon />} component={RouterLink} to={`/recipes/${recipe.id}/edit`}>
              {t('common.edit')}
            </Button>
          )}
          {!recipe.can_edit && (
            <Button variant="outlined" startIcon={<ImportIcon />} component={RouterLink}
              to={`/recipes/new?from=${recipe.id}`}>
              {t('community.import')}
            </Button>
          )}
          {entry ? (
            <Button color="error" startIcon={<DeleteIcon />} onClick={() => setConfirmRemove(true)}>
              {t('recipe.removeFromBook')}
            </Button>
          ) : (
            <Button variant="outlined" startIcon={<AddIcon />} onClick={() => void addToBook()}>
              {t('recipe.addToBook')}
            </Button>
          )}
        </Stack>
      </Stack>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 5 }}>
          <Card>
            <CardContent>
              <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                <Typography variant="h2">{t('recipe.ingredients')}</Typography>
                <PeopleStepper people={people} onChange={setPeople} />
              </Stack>
              <IngredientList recipe={recipe} people={people} />
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
          <Typography variant="h2" sx={{ mb: 1.5 }}>
            {t('recipe.steps')}
          </Typography>
          <StepList recipe={recipe} />
          {recipe.source_url && (
            <Typography variant="body2" sx={{ mt: 3 }}>
              {t('recipe.source')}:{' '}
              <Link href={recipe.source_url} target="_blank" rel="noopener noreferrer">
                {new URL(recipe.source_url).hostname}
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

      <Dialog open={confirmRemove} onClose={() => setConfirmRemove(false)}>
        <DialogTitle>{t('recipe.removeTitle')}</DialogTitle>
        <DialogContent>
          <Typography>
            {recipe.visibility === 'private' ? t('recipe.removePrivate') : t('recipe.removeShared')}
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
