import {
  Alert,
  Button,
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

/** Adds an ingredient to the shared catalog, from the recipe editor. */
export function IngredientDialog({
  initialName,
  suggestion,
  onClose,
  onCreated,
}: {
  initialName: string
  // From an assistant draft: category, unit and season it proposed, to confirm or change.
  suggestion?: DraftLine
  onClose: () => void
  onCreated: (ingredient: Ingredient) => void
}) {
  const { t } = useTranslation()
  const labels = useLabels()
  const [name, setName] = useState(initialName)
  const [category, setCategory] = useState(suggestion?.category ?? 'other')
  const [unit, setUnit] = useState<Unit>(
    suggestion && suggestion.unit !== 'tt' ? suggestion.unit : 'g',
  )
  const [months, setMonths] = useState<number[]>(suggestion?.season_months ?? [])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      const created = await api<Ingredient>('/ingredients/', {
        method: 'POST',
        body: JSON.stringify({
          name,
          category,
          default_unit: unit,
          season_months: { months },
        }),
      })
      onCreated(created)
    } catch (e) {
      const body = e instanceof ApiError ? (e.body as Record<string, string[]>) : null
      setError(body?.name?.[0] ?? t('common.error'))
      setBusy(false)
    }
  }

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t('ingredient.newTitle')}</DialogTitle>
      <DialogContent>
        <Stack spacing={2.5} sx={{ pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            {t('ingredient.sharedHint')}
          </Typography>
          {suggestion && <Alert severity="info">{t('ingredient.suggested')}</Alert>}
          <TextField
            label={t('ingredient.name')}
            value={name}
            onChange={(e) => setName(e.target.value)}
            error={!!error}
            helperText={error ?? t('ingredient.nameHint')}
            autoFocus
          />
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <TextField
              select
              label={t('ingredient.category')}
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              {INGREDIENT_CATEGORIES.map((c) => (
                <MenuItem key={c} value={c}>
                  {labels.category(c)}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label={t('ingredient.unit')}
              value={unit}
              onChange={(e) => setUnit(e.target.value as Unit)}
            >
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
          {t('common.add')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
