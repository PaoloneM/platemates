import AddIcon from '@mui/icons-material/Add'
import RemoveIcon from '@mui/icons-material/Remove'
import { Box, Chip, IconButton, List, ListItem, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { Recipe, RecipeLine } from '../api'
import type { LineMark } from '../recipeDiff'
import { formatQuantity, useLabels } from '../labels'

// The parts of a recipe shown both on its page and in the recipe dialog of a meal.

const MARK_COLOR: Record<LineMark, 'success' | 'warning' | 'error'> = {
  added: 'success',
  changed: 'warning',
  removed: 'error',
}

function LineText({ line, factor, mark }: { line: RecipeLine; factor: number; mark?: LineMark }) {
  const { t, i18n } = useTranslation()
  const labels = useLabels()
  let amount = t('unit.tt')
  if (line.unit !== 'tt' && line.quantity != null) {
    const value = formatQuantity(Number(line.quantity) * factor, i18n.resolvedLanguage)
    amount = line.unit === 'pc' ? value : `${value} ${labels.unit(line.unit)}`
  }
  return (
    <Stack direction="row" spacing={2} sx={{ alignItems: 'baseline', width: '100%' }}>
      <Typography sx={{ minWidth: 72, color: 'text.secondary', textAlign: 'right' }}>{amount}</Typography>
      <Box>
        <Typography component="span" sx={{ fontWeight: 500 }}>
          {line.ingredient_name}
        </Typography>
        {line.optional && (
          <Typography component="span" color="text.secondary">
            {` (${t('recipe.optional')})`}
          </Typography>
        )}
        {mark && (
          <Chip size="small" variant="outlined" color={MARK_COLOR[mark]} label={t(`community.mark.${mark}`)}
            sx={{ ml: 1, height: 20, '& .MuiChip-label': { px: 0.75 } }} />
        )}
        {line.note && (
          <Typography variant="body2" color="text.secondary">
            {line.note}
          </Typography>
        )}
      </Box>
    </Stack>
  )
}

/** "– 3 persone +": how many people the quantities are for. */
export function PeopleStepper({ people, onChange }: { people: number; onChange: (people: number) => void }) {
  const { t } = useTranslation()
  return (
    <Stack direction="row" sx={{ alignItems: 'center' }}>
      <IconButton size="small" onClick={() => onChange(Math.max(1, people - 1))} aria-label={t('recipe.fewerPeople')}>
        <RemoveIcon fontSize="small" />
      </IconButton>
      <Typography sx={{ minWidth: 88, textAlign: 'center' }}>{t('recipe.people', { count: people })}</Typography>
      <IconButton size="small" onClick={() => onChange(people + 1)} aria-label={t('recipe.morePeople')}>
        <AddIcon fontSize="small" />
      </IconButton>
    </Stack>
  )
}

/** The ingredients, with quantities for `people` (the recipe is written for `servings`), and
 * optionally how each differs from another version of the recipe. */
export function IngredientList({ recipe, people, marks }: {
  recipe: Recipe
  people: number
  marks?: Record<number, LineMark>
}) {
  const { t } = useTranslation()
  if (recipe.ingredients.length === 0) return <Typography color="text.secondary">{t('recipe.noIngredients')}</Typography>
  const factor = people / recipe.servings
  return (
    <List dense disablePadding>
      {recipe.ingredients.map((line) => (
        <ListItem key={line.id} disableGutters divider>
          <LineText line={line} factor={factor} mark={marks?.[line.ingredient]} />
        </ListItem>
      ))}
    </List>
  )
}

export function StepList({ recipe }: { recipe: Recipe }) {
  const { t } = useTranslation()
  if (recipe.steps.length === 0) return <Typography color="text.secondary">{t('recipe.noSteps')}</Typography>
  return (
    <Stack component="ol" spacing={1.5} sx={{ pl: 2.5, m: 0 }}>
      {recipe.steps.map((step, i) => (
        <Typography component="li" key={i} sx={{ pl: 0.5 }}>
          {step}
        </Typography>
      ))}
    </Stack>
  )
}
