import AddIcon from '@mui/icons-material/Add'
import ArrowDownIcon from '@mui/icons-material/ArrowDownward'
import ArrowUpIcon from '@mui/icons-material/ArrowUpward'
import DeleteIcon from '@mui/icons-material/DeleteOutlined'
import EditIcon from '@mui/icons-material/EditOutlined'
import {
  Alert,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  List,
  ListItem,
  ListItemText,
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
import { api, type SystemRule } from '../../api'
import { useLabels } from '../../labels'

const MAX_RULE = 300

type Draft = { text_it: string; text_en: string; active: boolean }

function RuleDialog({ rule, position, onClose, onSaved }: {
  rule: SystemRule | null
  // Where a new rule goes: after the last one.
  position: number
  onClose: () => void
  onSaved: (rule: SystemRule) => void
}) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState<Draft>(() =>
    rule ? { text_it: rule.text_it, text_en: rule.text_en, active: rule.active } : { text_it: '', text_en: '', active: true },
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const valid = draft.text_it.trim() !== '' && draft.text_en.trim() !== ''

  async function save() {
    setBusy(true)
    setError(false)
    try {
      onSaved(
        rule
          ? await api<SystemRule>(`/system-rules/${rule.id}/`, { method: 'PATCH', body: JSON.stringify(draft) })
          : await api<SystemRule>('/system-rules/', { method: 'POST', body: JSON.stringify({ ...draft, position }) }),
      )
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{rule ? t('manage.rules.edit') : t('manage.rules.new')}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {error && <Alert severity="error">{t('common.error')}</Alert>}
          <TextField label={t('manage.rules.textIt')} multiline fullWidth autoFocus value={draft.text_it}
            onChange={(e) => setDraft({ ...draft, text_it: e.target.value })}
            slotProps={{ htmlInput: { maxLength: MAX_RULE } }} />
          <TextField label={t('manage.rules.textEn')} multiline fullWidth value={draft.text_en}
            onChange={(e) => setDraft({ ...draft, text_en: e.target.value })}
            slotProps={{ htmlInput: { maxLength: MAX_RULE } }} />
          <FormControlLabel label={t('manage.rules.active')}
            control={<Switch checked={draft.active} onChange={(e) => setDraft({ ...draft, active: e.target.checked })} />} />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="contained" onClick={() => void save()} disabled={busy || !valid}>{t('common.save')}</Button>
      </DialogActions>
    </Dialog>
  )
}

/** The system rules, for staff: edited live, ordered, switched on and off. */
export function SystemRulesPage() {
  const { t } = useTranslation()
  const labels = useLabels()
  const [rules, setRules] = useState<SystemRule[] | null>(null)
  const [editing, setEditing] = useState<SystemRule | 'new' | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => void api<SystemRule[]>('/system-rules/').then(setRules), [])

  const replace = (saved: SystemRule) =>
    setRules((list) => {
      const others = (list ?? []).filter((r) => r.id !== saved.id)
      return [...others, saved].sort((a, b) => a.position - b.position || a.id - b.id)
    })

  /** Swap a rule with its neighbour; positions are renumbered in steps of 10 to stay distinct. */
  async function move(index: number, offset: -1 | 1) {
    if (!rules) return
    const order = [...rules]
    ;[order[index], order[index + offset]] = [order[index + offset], order[index]]
    const renumbered = order.map((rule, i) => ({ ...rule, position: (i + 1) * 10 }))
    const changed = renumbered.filter((rule) => rule.position !== rules.find((r) => r.id === rule.id)!.position)
    setRules(renumbered)
    try {
      await Promise.all(changed.map((rule) =>
        api(`/system-rules/${rule.id}/`, { method: 'PATCH', body: JSON.stringify({ position: rule.position }) })))
    } catch {
      setMessage(t('common.error'))
      api<SystemRule[]>('/system-rules/').then(setRules)
    }
  }

  async function remove(rule: SystemRule) {
    if (!window.confirm(t('manage.rules.deleteConfirm', { text: labels.systemRule(rule) }))) return
    try {
      await api(`/system-rules/${rule.id}/`, { method: 'DELETE' })
      setRules((list) => list?.filter((r) => r.id !== rule.id) ?? null)
      setMessage(t('manage.rules.deleted'))
    } catch {
      setMessage(t('common.error'))
    }
  }

  if (!rules) return <CircularProgress sx={{ display: 'block', mx: 'auto', mt: 4 }} />
  const last = rules.length ? rules[rules.length - 1].position : 0

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={2} sx={{ alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <Typography variant="body2" color="text.secondary">{t('manage.rules.hint')}</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setEditing('new')} sx={{ flex: 'none' }}>
          {t('manage.rules.new')}
        </Button>
      </Stack>
      <Paper variant="outlined">
        <List disablePadding>
          {rules.map((rule, index) => (
            <ListItem key={rule.id} divider={index < rules.length - 1}
              sx={{ alignItems: 'flex-start', gap: 1, flexWrap: { xs: 'wrap', sm: 'nowrap' } }}>
              <ListItemText primary={labels.systemRule(rule)} sx={{ '& .MuiListItemText-primary': { opacity: rule.active ? 1 : 0.6 } }}
                secondary={
                  <Stack component="span" direction="row" spacing={1} sx={{ mt: 0.5 }}>
                    {!rule.active && <Chip component="span" size="small" label={t('manage.rules.inactive')} />}
                    {rule.code && <Chip component="span" size="small" variant="outlined" label={t('manage.rules.shipped')} />}
                  </Stack>
                }
                slotProps={{ secondary: { component: 'span' } }} />
              <Stack direction="row" sx={{ flex: 'none', ml: 'auto' }}>
                <Tooltip title={t('manage.rules.moveUp')}>
                  <span><IconButton aria-label={t('manage.rules.moveUp')} disabled={index === 0} onClick={() => void move(index, -1)}><ArrowUpIcon /></IconButton></span>
                </Tooltip>
                <Tooltip title={t('manage.rules.moveDown')}>
                  <span><IconButton aria-label={t('manage.rules.moveDown')} disabled={index === rules.length - 1} onClick={() => void move(index, 1)}><ArrowDownIcon /></IconButton></span>
                </Tooltip>
                <Tooltip title={t('common.edit')}>
                  <IconButton aria-label={t('manage.rules.edit')} onClick={() => setEditing(rule)}><EditIcon /></IconButton>
                </Tooltip>
                {!rule.code && (
                  <Tooltip title={t('common.delete')}>
                    <IconButton aria-label={t('common.delete')} onClick={() => void remove(rule)}><DeleteIcon /></IconButton>
                  </Tooltip>
                )}
              </Stack>
            </ListItem>
          ))}
        </List>
      </Paper>
      {editing && (
        <RuleDialog rule={editing === 'new' ? null : editing} position={last + 10} onClose={() => setEditing(null)}
          onSaved={(saved) => { replace(saved); setEditing(null); setMessage(t('manage.rules.saved')) }} />
      )}
      <Snackbar open={!!message} autoHideDuration={4000} onClose={() => setMessage(null)} message={message} />
    </Stack>
  )
}
