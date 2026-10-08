import RestoreIcon from '@mui/icons-material/RestartAlt'
import {
  Alert,
  Button,
  CircularProgress,
  IconButton,
  Paper,
  Snackbar,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type ConfigSetting } from '../../api'

// Keys are dotted ("menu.thinking"); translation keys use the same path under `settings.item`.
const itemKey = (key: string) => `settings.item.${key.replace('.', '_')}`

function SettingRow({ setting, onSaved, onError }: {
  setting: ConfigSetting
  onSaved: (saved: ConfigSetting) => void
  onError: (message: string) => void
}) {
  const { t, i18n } = useTranslation()
  const [draft, setDraft] = useState(String(setting.value))
  const [busy, setBusy] = useState(false)

  async function send(init: RequestInit) {
    setBusy(true)
    try {
      const saved = await api<ConfigSetting>(`/config/${setting.key}/`, init)
      setDraft(String(saved.value))
      onSaved(saved)
    } catch (error) {
      const detail = error instanceof ApiError ? (error.body as { value?: string[] } | null)?.value?.[0] : undefined
      onError(detail ?? t('common.error'))
    } finally {
      setBusy(false)
    }
  }
  const save = (value: boolean | number) => send({ method: 'PUT', body: JSON.stringify({ value }) })

  const number = Number(draft)
  const validNumber = /^\d+$/.test(draft)
    && (setting.minimum === null || number >= setting.minimum)
    && (setting.maximum === null || number <= setting.maximum)
  const format = (value: boolean | number) =>
    typeof value === 'boolean' ? t(value ? 'settings.on' : 'settings.off') : value.toLocaleString(i18n.resolvedLanguage)

  return (
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ p: 2, alignItems: { sm: 'center' } }}>
      <Stack sx={{ flex: 1, minWidth: 0 }} spacing={0.5}>
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{t(`${itemKey(setting.key)}.label`)}</Typography>
        <Typography variant="body2" color="text.secondary">{t(`${itemKey(setting.key)}.hint`)}</Typography>
        <Typography variant="caption" color="text.secondary">
          {setting.is_default
            ? t('settings.isDefault')
            : t('settings.changed', {
                default: format(setting.default),
                who: setting.updated_by ?? '—',
                date: setting.updated_at ? new Date(setting.updated_at).toLocaleDateString(i18n.resolvedLanguage) : '',
              })}
        </Typography>
      </Stack>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flex: 'none' }}>
        {setting.kind === 'bool' ? (
          <Switch checked={setting.value as boolean} disabled={busy}
            onChange={(e) => void save(e.target.checked)}
            slotProps={{ input: { 'aria-label': t(`${itemKey(setting.key)}.label`) } }} />
        ) : (
          <>
            <TextField size="small" type="number" value={draft} error={!validNumber} disabled={busy}
              onChange={(e) => setDraft(e.target.value)} sx={{ width: 140 }}
              helperText={setting.minimum !== null && setting.maximum !== null
                ? `${format(setting.minimum)} – ${format(setting.maximum)}` : undefined}
              slotProps={{ htmlInput: { min: setting.minimum ?? undefined, max: setting.maximum ?? undefined, inputMode: 'numeric',
                'aria-label': t(`${itemKey(setting.key)}.label`) } }} />
            <Button variant="contained" disabled={busy || !validNumber || number === setting.value}
              onClick={() => void save(number)}>{t('common.save')}</Button>
          </>
        )}
        <Tooltip title={t('settings.reset', { value: format(setting.default) })}>
          <span>
            <IconButton aria-label={t('settings.reset', { value: format(setting.default) })}
              disabled={busy || setting.is_default} onClick={() => void send({ method: 'DELETE' })}>
              <RestoreIcon />
            </IconButton>
          </span>
        </Tooltip>
      </Stack>
    </Stack>
  )
}

/** Application settings, for administrators: changed live, stored in the database. */
export function SettingsPage() {
  const { t } = useTranslation()
  const [settings, setSettings] = useState<ConfigSetting[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    api<ConfigSetting[]>('/config/').then(setSettings).catch(() => setFailed(true))
  }, [])

  if (failed) return <Alert severity="error">{t('common.error')}</Alert>
  if (!settings) return <CircularProgress sx={{ display: 'block', mx: 'auto', mt: 4 }} />
  const groups = [...new Set(settings.map((s) => s.group))]

  return (
    <Stack spacing={3}>
      <Typography variant="body2" color="text.secondary">{t('settings.hint')}</Typography>
      {groups.map((group) => (
        <Stack key={group} spacing={1}>
          <Typography variant="h2">{t(`settings.group.${group}`)}</Typography>
          <Paper variant="outlined">
            {settings.filter((s) => s.group === group).map((setting, index) => (
              <Stack key={setting.key} sx={{ borderTop: index ? 1 : 0, borderColor: 'divider' }}>
                <SettingRow setting={setting}
                  onSaved={(saved) => {
                    setSettings((list) => list?.map((s) => (s.key === saved.key ? saved : s)) ?? null)
                    setMessage(t('settings.saved'))
                  }}
                  onError={setMessage} />
              </Stack>
            ))}
          </Paper>
        </Stack>
      ))}
      <Snackbar open={!!message} autoHideDuration={4000} onClose={() => setMessage(null)} message={message} />
    </Stack>
  )
}
