import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/DeleteOutlined'
import DownloadIcon from '@mui/icons-material/FileDownloadOutlined'
import PauseIcon from '@mui/icons-material/PauseOutlined'
import PlayIcon from '@mui/icons-material/PlayArrowOutlined'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  LinearProgress,
  Paper,
  Stack,
  Switch,
  FormControlLabel,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink } from 'react-router'
import { api, ApiError, type Campaign, type CampaignTarget, type Paginated, type SourceSite } from '../../api'
import { useAuth } from '../../auth/context'
import { useOnConnect, useRealtimeEvent } from '../../realtime'

function CampaignCard({ campaign, onChanged }: { campaign: Campaign; onChanged: (c: Campaign) => void }) {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const [busy, setBusy] = useState(false)
  const totals = Object.values(campaign.progress).reduce(
    (sum, p) => ({
      count: sum.count + p.count,
      published: sum.published + p.published,
      automatic: sum.automatic + p.automatic,
      ready: sum.ready + p.ready,
      waiting: sum.waiting + p.waiting_ingredients,
    }),
    { count: 0, published: 0, automatic: 0, ready: 0, waiting: 0 },
  )

  async function setStatus(action: 'pause' | 'resume') {
    setBusy(true)
    try {
      onChanged(await api<Campaign>(`/campaigns/${campaign.id}/${action}/`, { method: 'POST' }))
    } finally {
      setBusy(false)
    }
  }

  // Exporting is the transfer API's, administrators only.
  const canExport = me?.authenticated && me.user.is_admin && campaign.recipe_ids.length > 0
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={1.5}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
          <Typography variant="h3" sx={{ mr: 1 }}>{campaign.name}</Typography>
          <Chip size="small" color={campaign.status === 'running' ? 'primary' : 'default'}
            label={t(`campaigns.status.${campaign.status}`)} />
          {campaign.status === 'running' && <CircularProgress size={16} />}
          <Box sx={{ flex: 1 }} />
          {campaign.status === 'running' ? (
            <Button size="small" startIcon={<PauseIcon />} disabled={busy} onClick={() => void setStatus('pause')}>
              {t('campaigns.pause')}
            </Button>
          ) : (
            <Button size="small" startIcon={<PlayIcon />} disabled={busy} onClick={() => void setStatus('resume')}>
              {campaign.status === 'done' ? t('campaigns.restart') : t('campaigns.resume')}
            </Button>
          )}
          {canExport && (
            <Button size="small" startIcon={<DownloadIcon />}
              href={`/api/transfer/export/?scope=recipes&ids=${campaign.recipe_ids.join(',')}`}>
              {t('campaigns.export', { count: campaign.recipe_ids.length })}
            </Button>
          )}
        </Stack>
        <Typography variant="body2" color="text.secondary">
          {t('campaigns.summary', {
            published: totals.published, count: totals.count, automatic: totals.automatic,
          })}
          {' · '}
          {new Date(campaign.created_at).toLocaleDateString(i18n.resolvedLanguage)}
        </Typography>
        {(totals.ready > 0 || totals.waiting > 0) && (
          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
            {totals.ready > 0 && (
              <Button size="small" variant="outlined" component={RouterLink} to="/manage/drafts">
                {t('campaigns.toReview', { count: totals.ready })}
              </Button>
            )}
            {totals.waiting > 0 && (
              <Button size="small" variant="outlined" component={RouterLink} to="/manage/ingredient-proposals">
                {t('campaigns.waitingIngredients', { count: totals.waiting })}
              </Button>
            )}
          </Stack>
        )}
        {campaign.targets.map((target) => {
          const p = campaign.progress[target.key]
          if (!p) return null
          const running = p.queued + p.running
          return (
            <Box key={target.key}>
              <Stack direction="row" spacing={1} sx={{ alignItems: 'baseline' }}>
                <Typography variant="body2" sx={{ flex: 1, minWidth: 0 }} noWrap title={target.theme}>
                  {target.theme}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ flex: 'none' }}>
                  {p.published} / {target.count}
                </Typography>
              </Stack>
              <LinearProgress variant="buffer" value={Math.min(100, (p.published / target.count) * 100)}
                valueBuffer={Math.min(100, ((p.published + p.ready) / target.count) * 100)} sx={{ my: 0.5 }} />
              <Typography variant="caption" color="text.secondary">
                {[
                  p.ready && t('campaigns.part.ready', { count: p.ready }),
                  running && t('campaigns.part.running', { count: running }),
                  p.failed && t('campaigns.part.failed', { count: p.failed }),
                  campaign.notes[target.key] === 'exhausted' && t('campaigns.part.exhausted'),
                ].filter(Boolean).join(' · ')}
              </Typography>
            </Box>
          )
        })}
      </Stack>
    </Paper>
  )
}

function NewCampaign({ onCreated }: { onCreated: (c: Campaign) => void }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [brief, setBrief] = useState('')
  const [targets, setTargets] = useState<CampaignTarget[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function start() {
    // A ready-made plan, to adjust: everyday Italian recipes and some from elsewhere.
    setName(t('campaigns.defaults.name'))
    setBrief(t('campaigns.defaults.brief'))
    setTargets(t('campaigns.defaults.targets', { returnObjects: true }) as CampaignTarget[])
    setOpen(true)
  }

  const change = (index: number, patch: Partial<CampaignTarget>) =>
    setTargets((all) => all.map((target, i) => (i === index ? { ...target, ...patch } : target)))
  const total = targets.reduce((sum, target) => sum + (Number(target.count) || 0), 0)

  async function create() {
    setBusy(true)
    setError(null)
    try {
      onCreated(await api<Campaign>('/campaigns/', {
        method: 'POST',
        body: JSON.stringify({ name: name.trim(), brief: brief.trim(), targets }),
      }))
      setOpen(false)
    } catch (e) {
      setError(e instanceof ApiError && e.status === 400 ? t('campaigns.invalid') : t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return <Box><Button variant="contained" startIcon={<AddIcon />} onClick={start}>{t('campaigns.new')}</Button></Box>
  }
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={2}>
        <Typography variant="h3">{t('campaigns.new')}</Typography>
        <TextField label={t('campaigns.name')} value={name} onChange={(e) => setName(e.target.value)}
          slotProps={{ htmlInput: { maxLength: 120 } }} />
        <TextField label={t('campaigns.brief')} helperText={t('campaigns.briefHint')} multiline minRows={2}
          value={brief} onChange={(e) => setBrief(e.target.value)} />
        <Typography variant="subtitle2">{t('campaigns.targets', { count: total })}</Typography>
        {targets.map((target, index) => (
          <Stack key={index} direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ alignItems: { sm: 'center' } }}>
            <TextField size="small" label={t('campaigns.key')} value={target.key} sx={{ width: { sm: 140 } }}
              onChange={(e) => change(index, { key: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '') })} />
            <TextField size="small" label={t('campaigns.theme')} value={target.theme} fullWidth
              onChange={(e) => change(index, { theme: e.target.value })} />
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
              <TextField size="small" type="number" label={t('campaigns.count')} value={target.count} sx={{ width: 100 }}
                onChange={(e) => change(index, { count: Number(e.target.value) })}
                slotProps={{ htmlInput: { min: 1, max: 500 } }} />
              <IconButton aria-label={t('common.delete')} onClick={() => setTargets((all) => all.filter((_, i) => i !== index))}>
                <DeleteIcon fontSize="small" />
              </IconButton>
            </Stack>
          </Stack>
        ))}
        <Box>
          <Button size="small" startIcon={<AddIcon />}
            onClick={() => setTargets((all) => [...all, { key: `t${all.length + 1}`, theme: '', count: 10 }])}>
            {t('campaigns.addTarget')}
          </Button>
        </Box>
        {error && <Alert severity="error">{error}</Alert>}
        <Stack direction="row" spacing={1}>
          <Button variant="contained" disabled={busy || !name.trim() || targets.length === 0} onClick={() => void create()}>
            {t('campaigns.start')}
          </Button>
          <Button color="inherit" onClick={() => setOpen(false)}>{t('common.cancel')}</Button>
        </Stack>
      </Stack>
    </Paper>
  )
}

/** The sites the web search prefers (trusted) or never uses (blocked). */
function Sites() {
  const { t } = useTranslation()
  const [sites, setSites] = useState<SourceSite[]>([])
  const [domain, setDomain] = useState('')
  const [trusted, setTrusted] = useState(true)
  const [error, setError] = useState(false)

  const load = useCallback(() => api<SourceSite[]>('/source-sites/').then(setSites), [])
  useEffect(() => void load().catch(() => undefined), [load])

  async function add() {
    setError(false)
    try {
      await api('/source-sites/', { method: 'POST', body: JSON.stringify({ domain, trusted }) })
      setDomain('')
      void load()
    } catch {
      setError(true)
    }
  }

  const list = (kind: boolean) => (
    <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1 }}>
      {sites.filter((s) => s.trusted === kind).map((s) => (
        <Tooltip key={s.id} title={s.note}>
          <Chip label={s.domain} color={kind ? 'success' : 'default'} variant="outlined"
            onDelete={() => void api(`/source-sites/${s.id}/`, { method: 'DELETE' }).then(load)} />
        </Tooltip>
      ))}
    </Stack>
  )

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={1.5}>
        <Typography variant="h3">{t('campaigns.sites.title')}</Typography>
        <Typography variant="body2" color="text.secondary">{t('campaigns.sites.hint')}</Typography>
        <Typography variant="subtitle2">{t('campaigns.sites.trusted')}</Typography>
        {list(true)}
        <Typography variant="subtitle2">{t('campaigns.sites.blocked')}</Typography>
        {list(false)}
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ alignItems: { sm: 'center' } }}>
          <TextField size="small" label={t('campaigns.sites.domain')} placeholder="ricette.it" value={domain}
            error={error} onChange={(e) => setDomain(e.target.value)} />
          <FormControlLabel control={<Switch checked={trusted} onChange={(e) => setTrusted(e.target.checked)} />}
            label={trusted ? t('campaigns.sites.asTrusted') : t('campaigns.sites.asBlocked')} />
          <Button disabled={!domain.trim()} onClick={() => void add()}>{t('campaigns.sites.add')}</Button>
        </Stack>
      </Stack>
    </Paper>
  )
}

/**
 * Campaigns, for staff: fill the catalog with many system recipes at once. The worker plans
 * dishes for each target, drafts them from trusted recipe sites and publishes on its own the
 * drafts that meet the bar; the rest go to Drafts, and unknown ingredients to Ingredient
 * proposals.
 */
export function CampaignsPage() {
  const { t } = useTranslation()
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null)

  const load = useCallback(
    () => api<Paginated<Campaign>>('/campaigns/').then((page) => setCampaigns(page.results)).catch(() => undefined),
    [],
  )
  useEffect(() => void load(), [load])
  useOnConnect(() => void load())
  // Drafts change all the time while a campaign runs: refresh at most every few seconds.
  const pending = useRef<number | null>(null)
  useRealtimeEvent('system_draft', () => {
    if (pending.current === null) {
      pending.current = window.setTimeout(() => {
        pending.current = null
        void load()
      }, 3000)
    }
  })
  useEffect(() => () => { if (pending.current !== null) window.clearTimeout(pending.current) }, [])

  const replace = (changed: Campaign) =>
    setCampaigns((all) => (all ?? []).map((c) => (c.id === changed.id ? changed : c)))

  return (
    <Stack spacing={2}>
      <Typography variant="body2" color="text.secondary">{t('campaigns.hint')}</Typography>
      <NewCampaign onCreated={(created) => setCampaigns((all) => [created, ...(all ?? [])])} />
      {!campaigns ? (
        <CircularProgress sx={{ display: 'block', mx: 'auto' }} />
      ) : campaigns.length === 0 ? (
        <Typography color="text.secondary">{t('campaigns.none')}</Typography>
      ) : (
        campaigns.map((c) => <CampaignCard key={c.id} campaign={c} onChanged={replace} />)
      )}
      <Sites />
    </Stack>
  )
}
