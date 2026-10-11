import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Radio,
  RadioGroup,
  Typography,
} from '@mui/material'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type ShoppingApp } from '../api'
import { useAuth } from '../auth/context'

const APPS: ShoppingApp[] = ['listonic']

/** The user's choice of a shopping list app to send items to (none by default). */
export function ShoppingAppDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const { me, refresh } = useAuth()
  const current = me?.authenticated ? me.user.shopping_app ?? '' : ''
  const [value, setValue] = useState<string>(current)
  const [saving, setSaving] = useState(false)

  async function save() {
    setSaving(true)
    try {
      await api('/me/', { method: 'PATCH', body: JSON.stringify({ shopping_app: value }) })
      await refresh()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="xs"
      slotProps={{ transition: { onEnter: () => setValue(current) } }}>
      <DialogTitle>{t('shoppingApp.title')}</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>{t('shoppingApp.hint')}</Typography>
        <RadioGroup value={value} onChange={(e) => setValue(e.target.value)}>
          <FormControlLabel value="" control={<Radio />} label={t('shoppingApp.none')} />
          {APPS.map((app) => (
            <FormControlLabel key={app} value={app} control={<Radio />} label={t(`shoppingApp.app.${app}`)} />
          ))}
        </RadioGroup>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="contained" disabled={saving} onClick={() => void save()}>{t('common.save')}</Button>
      </DialogActions>
    </Dialog>
  )
}
