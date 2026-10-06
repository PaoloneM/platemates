import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type KitchenTool } from '../api'

/** Adds a kitchen tool to the shared catalog, from the recipe editor. */
export function ToolDialog({
  initialName,
  onClose,
  onCreated,
}: {
  initialName: string
  onClose: () => void
  onCreated: (tool: KitchenTool) => void
}) {
  const { t } = useTranslation()
  const [name, setName] = useState(initialName)
  const [heats, setHeats] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      onCreated(
        await api<KitchenTool>('/kitchen-tools/', {
          method: 'POST',
          body: JSON.stringify({ name, heats_kitchen: heats }),
        }),
      )
    } catch (e) {
      const body = e instanceof ApiError ? (e.body as Record<string, string[]>) : null
      setError(body?.name ? t('tool.exists') : t('common.error'))
      setBusy(false)
    }
  }

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{t('tool.newTitle')}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            {t('tool.sharedHint')}
          </Typography>
          <TextField
            label={t('tool.name')}
            value={name}
            onChange={(e) => setName(e.target.value)}
            error={!!error}
            helperText={error}
            autoFocus
          />
          <FormControlLabel
            control={<Switch checked={heats} onChange={(e) => setHeats(e.target.checked)} />}
            label={t('tool.heatsKitchen')}
          />
          <Typography variant="body2" color="text.secondary">
            {t('tool.heatsKitchenHint')}
          </Typography>
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
