import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  FormControlLabel,
  MenuItem,
  Paper,
  Snackbar,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type IngredientProposal } from '../../api'
import { SeasonPicker } from '../../components/SeasonPicker'
import { INGREDIENT_CATEGORIES, useLabels } from '../../labels'

type View = 'pending' | 'approved' | 'rejected'

function ProposalRow({ proposal, selected, onSelect, onChanged }: {
  proposal: IngredientProposal
  selected: boolean
  onSelect: (selected: boolean) => void
  onChanged: (proposal: IngredientProposal) => void
}) {
  const { t } = useTranslation()
  const labels = useLabels()
  const [error, setError] = useState(false)
  const pending = proposal.status === 'pending'

  async function patch(change: Partial<IngredientProposal>) {
    setError(false)
    try {
      onChanged(await api<IngredientProposal>(`/ingredient-proposals/${proposal.id}/`, {
        method: 'PATCH',
        body: JSON.stringify(change),
      }))
    } catch {
      setError(true)
    }
  }

  return (
    <Stack spacing={1} sx={{ p: 2 }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
        {pending && <Checkbox checked={selected} onChange={(e) => onSelect(e.target.checked)} sx={{ ml: -1 }} />}
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{proposal.name}</Typography>
        {proposal.waiting > 0 && (
          <Chip size="small" color="primary" variant="outlined"
            label={t('proposals.waiting', { count: proposal.waiting })} />
        )}
        {!pending && proposal.ingredient_name && (
          <Chip size="small" label={t('proposals.became', { name: proposal.ingredient_name })} />
        )}
      </Stack>
      {proposal.used_by.length > 0 && (
        <Typography variant="body2" color="text.secondary">
          {t('proposals.usedBy', { dishes: proposal.used_by.join(', ') })}
        </Typography>
      )}
      {pending && (
        <>
          <ToggleButtonGroup size="small" exclusive value={proposal.action}
            onChange={(_, action) => action && void patch(
              action === 'alias' && !proposal.alias_of && proposal.candidates[0]
                ? { action, alias_of: proposal.candidates[0].id }
                : { action },
            )}>
            <ToggleButton value="new">{t('proposals.new')}</ToggleButton>
            <ToggleButton value="alias" disabled={proposal.candidates.length === 0}>{t('proposals.alias')}</ToggleButton>
          </ToggleButtonGroup>
          {proposal.action === 'alias' ? (
            <TextField select size="small" fullWidth={false} label={t('proposals.aliasOf')} value={proposal.alias_of ?? ''}
              sx={{ maxWidth: 320 }} onChange={(e) => void patch({ alias_of: Number(e.target.value) })}>
              {proposal.candidates.map((c) => (
                <MenuItem key={c.id} value={c.id}>{c.name} ({labels.category(c.category)})</MenuItem>
              ))}
            </TextField>
          ) : (
            <Stack spacing={1}>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ alignItems: { sm: 'center' } }}>
                <TextField select size="small" fullWidth={false} label={t('proposals.category')} value={proposal.category}
                  sx={{ minWidth: 220 }} onChange={(e) => void patch({ category: e.target.value })}>
                  {INGREDIENT_CATEGORIES.map((c) => <MenuItem key={c} value={c}>{labels.category(c)}</MenuItem>)}
                </TextField>
                <TextField select size="small" fullWidth={false} label={t('proposals.unit')} value={proposal.default_unit}
                  sx={{ minWidth: 140 }} onChange={(e) => void patch({ default_unit: e.target.value as IngredientProposal['default_unit'] })}>
                  {(['g', 'ml', 'pc'] as const).map((u) => <MenuItem key={u} value={u}>{labels.unit(u)}</MenuItem>)}
                </TextField>
                <FormControlLabel sx={{ whiteSpace: 'nowrap' }} label={t('proposals.basic')}
                  control={<Switch checked={proposal.basic} onChange={(e) => void patch({ basic: e.target.checked })} />} />
              </Stack>
              <SeasonPicker months={proposal.season_months} onChange={(months) => void patch({ season_months: months })} />
            </Stack>
          )}
        </>
      )}
      {error && <Alert severity="error">{t('common.error')}</Alert>}
    </Stack>
  )
}

/**
 * Ingredient names campaign drafts use and the catalog lacks, with what the model proposes for
 * each. Staff check them in one place and approve them together; approving publishes the
 * drafts that were waiting only for them.
 */
export function IngredientProposalsPage() {
  const { t } = useTranslation()
  const [view, setView] = useState<View>('pending')
  const [proposals, setProposals] = useState<IngredientProposal[] | null>(null)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const load = useCallback(
    () => api<IngredientProposal[]>(`/ingredient-proposals/?status=${view}`).then((list) => {
      setProposals(list)
      setSelected(new Set())
    }),
    [view],
  )
  useEffect(() => void load().catch(() => setMessage(t('common.error'))), [load, t])

  async function decide(action: 'approve' | 'reject') {
    setBusy(true)
    try {
      const result = await api<{ published: number } | undefined>(`/ingredient-proposals/${action}/`, {
        method: 'POST',
        body: JSON.stringify({ ids: [...selected] }),
      })
      setMessage(action === 'approve'
        ? t('proposals.approved', { count: selected.size, published: result?.published ?? 0 })
        : t('proposals.rejected', { count: selected.size }))
      await load()
    } catch {
      setMessage(t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  const all = proposals ?? []
  return (
    <Stack spacing={2}>
      <Typography variant="body2" color="text.secondary">{t('proposals.hint')}</Typography>
      <Tabs value={view} onChange={(_, value) => { setProposals(null); setView(value) }}>
        <Tab value="pending" label={t('proposals.view.pending')} />
        <Tab value="approved" label={t('proposals.view.approved')} />
        <Tab value="rejected" label={t('proposals.view.rejected')} />
      </Tabs>
      {view === 'pending' && all.length > 0 && (
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
          <FormControlLabel label={t('proposals.selectAll', { count: all.length })} control={
            <Checkbox checked={selected.size === all.length} indeterminate={selected.size > 0 && selected.size < all.length}
              onChange={(e) => setSelected(e.target.checked ? new Set(all.map((p) => p.id)) : new Set())} />
          } />
          <Box sx={{ flex: 1 }} />
          <Button color="inherit" disabled={busy || selected.size === 0} onClick={() => void decide('reject')}>
            {t('proposals.reject')}
          </Button>
          <Button variant="contained" disabled={busy || selected.size === 0} onClick={() => void decide('approve')}>
            {t('proposals.approve', { count: selected.size })}
          </Button>
        </Stack>
      )}
      {!proposals ? (
        <CircularProgress sx={{ display: 'block', mx: 'auto' }} />
      ) : all.length === 0 ? (
        <Typography color="text.secondary">{t('proposals.none')}</Typography>
      ) : (
        <Paper variant="outlined">
          {all.map((proposal, index) => (
            <Box key={proposal.id} sx={{ borderTop: index ? 1 : 0, borderColor: 'divider' }}>
              <ProposalRow proposal={proposal} selected={selected.has(proposal.id)}
                onSelect={(on) => setSelected((s) => {
                  const next = new Set(s)
                  if (on) next.add(proposal.id)
                  else next.delete(proposal.id)
                  return next
                })}
                onChanged={(changed) => setProposals((list) => (list ?? []).map((p) => (p.id === changed.id ? changed : p)))} />
            </Box>
          ))}
        </Paper>
      )}
      <Snackbar open={!!message} autoHideDuration={5000} onClose={() => setMessage(null)} message={message} />
    </Stack>
  )
}
