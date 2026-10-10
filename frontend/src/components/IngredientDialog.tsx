import {
  Alert,
  Autocomplete,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type DraftLine, type Ingredient, type Unit } from '../api'
import { INGREDIENT_CATEGORIES, UNITS, useLabels } from '../labels'
import { SeasonPicker } from './SeasonPicker'

/**
 * Creates an ingredient (from the recipe editor: the team's own, or a system one for a system
 * recipe; from the management section: a system one), or edits one (management section, with
 * its aliases).
 */
export function IngredientDialog({
  team = null,
  initialName = '',
  suggestion,
  ingredient,
  onClose,
  onCreated,
  onSaved,
  withAliases = false,
}: {
  // Creating: the team it is added for; null for a system ingredient (staff).
  team?: number | null
  initialName?: string
  // From an assistant draft: category, unit and season it proposed, to confirm or change.
  suggestion?: DraftLine
  // Present: edit this ingredient instead of creating one.
  ingredient?: Ingredient
  onClose: () => void
  onCreated?: (ingredient: Ingredient) => void
  onSaved?: (ingredient: Ingredient) => void
  withAliases?: boolean
}) {
  const { t } = useTranslation()
  const labels = useLabels()
  const [name, setName] = useState(ingredient?.name ?? initialName)
  const [aliases, setAliases] = useState<string[]>(ingredient?.aliases ?? [])
  const [category, setCategory] = useState(ingredient?.category ?? suggestion?.category ?? 'other')
  const [unit, setUnit] = useState<Unit>(
    ingredient?.default_unit ?? (suggestion && suggestion.unit !== 'tt' ? suggestion.unit : 'g'),
  )
  const [months, setMonths] = useState<number[]>(
    ingredient?.season_months.months ?? suggestion?.season_months ?? [],
  )
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true)
    setError(null)
    const body: Record<string, unknown> = {
      name,
      category,
      default_unit: unit,
      season_months: { months },
    }
    if (!ingredient) body.team = team
    if (withAliases) body.aliases = aliases
    try {
      const saved = await api<Ingredient>(ingredient ? `/ingredients/${ingredient.id}/` : '/ingredients/', {
        method: ingredient ? 'PATCH' : 'POST',
        body: JSON.stringify(body),
      })
      if (ingredient) onSaved?.(saved)
      else onCreated?.(saved)
    } catch (e) {
      const data = e instanceof ApiError ? (e.body as Record<string, string[]>) : null
      setError(data?.name ? t('ingredient.exists') : t('common.error'))
      setBusy(false)
    }
  }

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{ingredient ? t('ingredient.editTitle') : t('ingredient.newTitle')}</DialogTitle>
      <DialogContent>
        <Stack spacing={2.5} sx={{ pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            {ingredient && ingredient.usage_count
              ? t('ingredient.editHint', { count: ingredient.usage_count })
              : (ingredient ? ingredient.team : team) != null
                ? t('ingredient.teamHint')
                : t('ingredient.sharedHint')}
          </Typography>
          {ingredient?.team_name && (
            <Typography variant="body2">{t('ingredient.addedBy', { team: ingredient.team_name })}</Typography>
          )}
          {suggestion && <Alert severity="info">{t('ingredient.suggested')}</Alert>}
          <TextField
            label={t('ingredient.name')}
            value={name}
            onChange={(e) => setName(e.target.value)}
            error={!!error}
            helperText={error ?? t('ingredient.nameHint')}
            autoFocus
          />
          {withAliases && (
            <Autocomplete<string, true, false, true>
              multiple
              freeSolo
              options={[]}
              value={aliases}
              onChange={(_, values) => setAliases(values.map((v) => v.trim().toLowerCase()).filter(Boolean))}
              renderValue={(values, getItemProps) =>
                values.map((value, index) => {
                  const { key, ...itemProps } = getItemProps({ index })
                  return <Chip key={key} label={value} size="small" {...itemProps} />
                })
              }
              renderInput={(params) => (
                <TextField {...params} label={t('ingredient.aliases')} helperText={t('ingredient.aliasesHint')} />
              )}
            />
          )}
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <TextField select label={t('ingredient.category')} value={category}
              onChange={(e) => setCategory(e.target.value)}>
              {INGREDIENT_CATEGORIES.map((c) => (
                <MenuItem key={c} value={c}>
                  {labels.category(c)}
                </MenuItem>
              ))}
            </TextField>
            <TextField select label={t('ingredient.unit')} value={unit}
              onChange={(e) => setUnit(e.target.value as Unit)}>
              {UNITS.map((u) => (
                <MenuItem key={u} value={u}>
                  {labels.unit(u)}
                </MenuItem>
              ))}
            </TextField>
          </Stack>
          <div>
            <Typography variant="subtitle2" gutterBottom>
              {t('ingredient.season')}
            </Typography>
            <SeasonPicker months={months} onChange={setMonths} />
          </div>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="contained" onClick={save} disabled={busy || !name.trim()}>
          {ingredient ? t('common.save') : t('common.add')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
