import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import { Box, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { CalendarDish } from '../api'
import { useLabels } from '../labels'

/** A dish's title and course on one line; a sparkle marks a proposal, "new" a dish without a recipe. */
export function DishLine({ dish }: { dish: CalendarDish }) {
  const { t } = useTranslation()
  const labels = useLabels()
  return (
    <Typography variant="body2" noWrap sx={{ color: dish.proposed ? 'primary.main' : undefined }}>
      {dish.proposed && (
        <AutoAwesomeIcon aria-label={t('generation.proposed')} sx={{ fontSize: 14, mr: 0.5, verticalAlign: '-2px' }} />
      )}
      {dish.title}
      <Typography component="span" variant="caption" color="text.secondary">
        {dish.course && ` · ${labels.course(dish.course)}`}
        {dish.recipe === null && (
          <Box component="span" sx={{ fontStyle: 'italic' }}> · {t('generation.newDish')}</Box>
        )}
      </Typography>
    </Typography>
  )
}
