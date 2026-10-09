import StarIcon from '@mui/icons-material/Star'
import { Stack, Tooltip, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'

/** "★ 4,3 · 309 voti in rete": how a recipe is rated on the pages it was drafted from. */
export function WebRating({ rating, count }: { rating: string | null; count: number | null }) {
  const { t, i18n } = useTranslation()
  if (rating === null || !count) return null
  const value = Number(rating).toLocaleString(i18n.resolvedLanguage, { maximumFractionDigits: 1 })
  return (
    <Tooltip title={t('drafts.webRatingHint')}>
      <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center', color: 'text.secondary' }}>
        <StarIcon fontSize="small" sx={{ color: 'warning.main' }} />
        <Typography variant="body2">
          {t('drafts.webRating', { value, count, formattedCount: count.toLocaleString(i18n.resolvedLanguage) })}
        </Typography>
      </Stack>
    </Tooltip>
  )
}
