import { Box, Button, Chip, Stack } from '@mui/material'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { isSeasonAligned, SEASON_MONTHS, SEASONS, useLabels } from '../labels'

/**
 * Seasonality editor with two modes: by season (default) or, in advanced mode, by month.
 * `months` empty means all year. Opens in month mode when the value is not made of whole seasons.
 */
export function SeasonPicker({
  months,
  onChange,
  disabled = false,
}: {
  months: number[]
  onChange: (months: number[]) => void
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const labels = useLabels()
  // Month mode is forced whenever the value is not made of whole seasons (it may change after
  // mounting, e.g. a derived season updating as ingredients are added); otherwise it is the
  // user's choice.
  const aligned = isSeasonAligned(months)
  const [monthChosen, setMonthChosen] = useState(false)
  const byMonth = monthChosen || !aligned
  const allYear = months.length === 0
  const selected = new Set(allYear ? [] : months)

  function emit(next: Set<number>) {
    // Every month selected is "all year", stored as an empty list.
    onChange(next.size === 12 ? [] : [...next].sort((a, b) => a - b))
  }

  function toggleSeason(season: keyof typeof SEASON_MONTHS) {
    const next = new Set(selected)
    const on = SEASON_MONTHS[season].every((m) => next.has(m))
    SEASON_MONTHS[season].forEach((m) => (on ? next.delete(m) : next.add(m)))
    emit(next)
  }

  function toggleMonth(month: number) {
    const next = new Set(selected)
    if (next.has(month)) next.delete(month)
    else next.add(month)
    emit(next)
  }

  return (
    <Stack spacing={1}>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
        <Chip
          label={t('season.allYear')}
          color={allYear ? 'primary' : 'default'}
          variant={allYear ? 'filled' : 'outlined'}
          onClick={() => onChange([])}
          disabled={disabled}
        />
        {byMonth
          ? Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
              <Chip
                key={m}
                label={labels.month(m)}
                color={selected.has(m) ? 'primary' : 'default'}
                variant={selected.has(m) ? 'filled' : 'outlined'}
                onClick={() => toggleMonth(m)}
                disabled={disabled}
              />
            ))
          : SEASONS.map((s) => {
              const on = SEASON_MONTHS[s].every((m) => selected.has(m))
              return (
                <Chip
                  key={s}
                  label={labels.season(s)}
                  color={on ? 'primary' : 'default'}
                  variant={on ? 'filled' : 'outlined'}
                  onClick={() => toggleSeason(s)}
                  disabled={disabled}
                />
              )
            })}
      </Box>
      <Box>
        <Button
          size="small"
          onClick={() => setMonthChosen(!byMonth)}
          disabled={disabled || !aligned}
        >
          {byMonth ? t('season.bySeason') : t('season.advanced')}
        </Button>
      </Box>
    </Stack>
  )
}
