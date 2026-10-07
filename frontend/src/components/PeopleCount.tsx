import PeopleIcon from '@mui/icons-material/PeopleOutlined'
import { Stack, Tooltip, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { CalendarDay, Meal } from '../api'

/** People at a meal, terracotta when the date differs from the typical week. */
export function PeopleCount({ day, meal }: { day: CalendarDay; meal: Meal }) {
  const { t } = useTranslation()
  const count = day.people[meal]
  const changed = day.overridden.includes(meal)
  const value = (
    <Stack direction="row" spacing={0.5} sx={{
      alignItems: 'center', px: 0.75, borderRadius: 1, color: changed ? 'secondary.main' : 'text.secondary',
      bgcolor: (theme) => (changed ? theme.alpha((theme.vars ?? theme).palette.secondary.main, 0.12) : 'transparent'),
    }}>
      <PeopleIcon fontSize="small" />
      <Typography variant="body2" sx={{ fontWeight: 600, color: changed ? 'secondary.main' : count ? 'text.primary' : undefined }}>
        {count}
      </Typography>
    </Stack>
  )
  return (
    <Tooltip title={changed ? t('calendar.usually', { count: day.usual[meal] }) : t('calendar.people', { count })}>
      {value}
    </Tooltip>
  )
}
