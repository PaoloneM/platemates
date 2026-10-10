import CloseIcon from '@mui/icons-material/Close'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Stack,
  Tab,
  Tabs,
  Typography,
  useMediaQuery,
} from '@mui/material'
import { useTheme } from '@mui/material/styles'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink } from 'react-router'
import { api, type Recipe } from '../api'
import { useLabels } from '../labels'
import { IngredientList, PeopleStepper, StepList } from './RecipeView'

export type DialogDish = { recipe: number; title: string }

/**
 * A meal's recipes at a glance, without leaving the menu: quantities for the meal's people
 * (changeable here), ingredients and steps. One tab per dish when the meal has several; the
 * full recipe page is a link away. Full screen on phones.
 */
export function RecipeDialog({ dishes, people, initial = 0, onClose }: {
  dishes: DialogDish[]
  people: number
  initial?: number
  onClose: () => void
}) {
  const { t } = useTranslation()
  const labels = useLabels()
  const phone = useMediaQuery(useTheme().breakpoints.down('sm'))
  const [tab, setTab] = useState(initial)
  const [recipes, setRecipes] = useState<Record<number, Recipe | 'error'>>({})
  // The meal's people by default; a meal with nobody at home still shows one portion.
  const [count, setCount] = useState(Math.max(1, people))
  const current = dishes[tab]

  useEffect(() => {
    if (!current || recipes[current.recipe]) return
    api<Recipe>(`/recipes/${current.recipe}/`)
      .then((recipe) => setRecipes((all) => ({ ...all, [current.recipe]: recipe })))
      .catch(() => setRecipes((all) => ({ ...all, [current.recipe]: 'error' })))
  }, [current, recipes])

  if (!current) return null
  const recipe = recipes[current.recipe]

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="md" fullScreen={phone} scroll="paper">
      <DialogTitle sx={{ pr: 6 }}>
        {current.title}
        <IconButton onClick={onClose} aria-label={t('common.close')} sx={{ position: 'absolute', top: 8, right: 8 }}>
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      {dishes.length > 1 && (
        <Tabs value={tab} onChange={(_, value) => setTab(value)} variant="scrollable" sx={{ px: 2, borderBottom: 1, borderColor: 'divider' }}>
          {dishes.map((dish) => <Tab key={dish.recipe} label={dish.title} sx={{ textTransform: 'none' }} />)}
        </Tabs>
      )}
      <DialogContent>
        {recipe === 'error' ? (
          <Alert severity="error">{t('recipe.notFound')}</Alert>
        ) : !recipe ? (
          <CircularProgress sx={{ display: 'block', mx: 'auto', my: 6 }} />
        ) : (
          <Stack spacing={2.5}>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
              <Chip size="small" variant="outlined" label={labels.course(recipe.course)} />
              {recipe.cuisine_name && <Chip size="small" variant="outlined" label={recipe.cuisine_name} />}
              {recipe.total_minutes != null && (
                <Chip size="small" variant="outlined" label={t('recipe.minutes', { count: recipe.total_minutes })} />
              )}
            </Box>
            {recipe.description && <Typography color="text.secondary">{recipe.description}</Typography>}
            <Box sx={{ display: 'grid', gap: 3, gridTemplateColumns: { xs: '1fr', md: '5fr 7fr' }, alignItems: 'start' }}>
              <Box>
                <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                  <Typography variant="h3">{t('recipe.ingredients')}</Typography>
                  <PeopleStepper people={count} onChange={setCount} />
                </Stack>
                <IngredientList recipe={recipe} people={count} />
              </Box>
              <Box>
                <Typography variant="h3" sx={{ mb: 1.5 }}>{t('recipe.steps')}</Typography>
                <StepList recipe={recipe} />
              </Box>
            </Box>
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button component={RouterLink} to={`/recipes/${current.recipe}`} endIcon={<OpenInNewIcon />}>
          {t('recipe.openPage')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
