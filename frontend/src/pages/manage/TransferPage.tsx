import DownloadIcon from '@mui/icons-material/FileDownloadOutlined'
import UploadIcon from '@mui/icons-material/FileUploadOutlined'
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  LinearProgress,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  api,
  apiDownload,
  ApiError,
  apiUpload,
  type ImportJob,
  type ImportJobEvent,
  type ImportReport,
  type TransferChoices,
} from '../../api'
import { useOnConnect, useRealtimeEvent } from '../../realtime'

type Scope = 'team' | 'recipes' | 'system' | 'ingredients'
type RecipeChoice = TransferChoices['recipes'][number]

function errorOf(error: unknown, fallback: string): string {
  const body = error instanceof ApiError ? (error.body as Record<string, string> | null) : null
  return (body && Object.values(body)[0]) || fallback
}

function ExportPanel({ choices }: { choices: TransferChoices }) {
  const { t } = useTranslation()
  const [scope, setScope] = useState<Scope>('team')
  const [team, setTeam] = useState<number | ''>(choices.teams[0]?.id ?? '')
  const [recipes, setRecipes] = useState<RecipeChoice[]>([])
  const [search, setSearch] = useState('')
  const [found, setFound] = useState<RecipeChoice[]>([])
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (scope !== 'recipes' || !search.trim()) return
    const timer = setTimeout(() => {
      api<TransferChoices>(`/transfer/choices/?search=${encodeURIComponent(search.trim())}`)
        .then((c) => setFound(c.recipes))
        .catch(() => undefined)
    }, 250)
    return () => clearTimeout(timer)
  }, [scope, search])

  const query =
    scope === 'team' ? `scope=team&team=${team}`
      : scope === 'recipes' ? `scope=recipes&ids=${recipes.map((r) => r.id).join(',')}`
        : scope === 'ingredients' ? 'scope=ingredients&owner=system'
          : 'scope=system'
  const ready = scope === 'team' ? team !== '' : scope === 'recipes' ? recipes.length > 0 : true

  async function download() {
    setBusy(true)
    setMessage(null)
    try {
      const name = await apiDownload(`/transfer/export/?${query}`)
      setMessage({ ok: true, text: t('transfer.exported', { name }) })
    } catch (error) {
      setMessage({ ok: false, text: errorOf(error, t('common.error')) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={2}>
        <Typography variant="h2">{t('transfer.export')}</Typography>
        <ToggleButtonGroup exclusive size="small" value={scope} onChange={(_, v: Scope | null) => v && setScope(v)}
          sx={{ flexWrap: 'wrap' }}>
          {(['team', 'recipes', 'system', 'ingredients'] as const).map((s) => (
            <ToggleButton key={s} value={s}>{t(`transfer.scope.${s}`)}</ToggleButton>
          ))}
        </ToggleButtonGroup>
        <Typography variant="body2" color="text.secondary">
          {t(`transfer.scopeHint.${scope}`, { count: choices.system_ingredients })}
        </Typography>
        {scope === 'team' && (
          <TextField select size="small" label={t('transfer.team')} value={team}
            onChange={(e) => setTeam(Number(e.target.value))} sx={{ maxWidth: 360 }}>
            {choices.teams.map((c) => (
              <MenuItem key={c.id} value={c.id}>
                {t('transfer.teamOption', { name: c.name, recipes: c.recipes, users: c.users })}
              </MenuItem>
            ))}
          </TextField>
        )}
        {scope === 'recipes' && (
          <Autocomplete<RecipeChoice, true>
            multiple
            options={found}
            value={recipes}
            filterOptions={(options) => options}
            getOptionLabel={(r) => (r.team ? `${r.title} · ${r.team}` : r.title)}
            isOptionEqualToValue={(a, b) => a.id === b.id}
            onInputChange={(_, v) => setSearch(v)}
            onChange={(_, v) => setRecipes(v)}
            noOptionsText={t('ingredient.typeToSearch')}
            renderInput={(params) => <TextField {...params} size="small" label={t('transfer.recipes')} />}
          />
        )}
        <Box>
          <Button variant="contained" startIcon={<DownloadIcon />} disabled={!ready || busy}
            onClick={() => void download()}>
            {t('transfer.download')}
          </Button>
        </Box>
        {message && <Alert severity={message.ok ? 'success' : 'error'}>{message.text}</Alert>}
      </Stack>
    </Paper>
  )
}

function ReportView({ report }: { report: ImportReport }) {
  const { t } = useTranslation()
  const kinds = [...new Set([...Object.keys(report.created), ...Object.keys(report.updated), ...Object.keys(report.skipped)])]
  return (
    <Stack spacing={1.5}>
      {report.teams.map((team) => (
        <Typography key={team.file} variant="body2">
          {team.new
            ? t('transfer.teamNew', { name: team.file })
            : t('transfer.teamInto', { name: team.file, into: team.into })}
        </Typography>
      ))}
      {kinds.length === 0 ? (
        <Typography color="text.secondary">{t('transfer.empty')}</Typography>
      ) : (
        <Table size="small" sx={{ maxWidth: 520 }}>
          <TableHead>
            <TableRow>
              <TableCell />
              <TableCell align="right">{t('transfer.created')}</TableCell>
              <TableCell align="right">{t('transfer.updated')}</TableCell>
              <TableCell align="right">{t('transfer.skipped')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {kinds.map((kind) => (
              <TableRow key={kind}>
                <TableCell>{t(`transfer.kind.${kind}`, { defaultValue: kind })}</TableCell>
                <TableCell align="right">{report.created[kind] ?? 0}</TableCell>
                <TableCell align="right">{report.updated[kind] ?? 0}</TableCell>
                <TableCell align="right">{report.skipped[kind] ?? 0}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {report.warnings.length > 0 && (
        <Alert severity="warning">
          <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
            {report.warnings.map((w) => <li key={w}>{w}</li>)}
          </Box>
        </Alert>
      )}
    </Stack>
  )
}

/** Where an import running in the worker is: its phase, and how many items of it are done. */
function JobProgress({ job }: { job: ImportJob }) {
  const { t } = useTranslation()
  const counted = job.total > 1
  return (
    <Stack spacing={0.5}>
      <Typography variant="body2">
        {job.status === 'queued' || !job.phase
          ? t('transfer.queued')
          : t(`transfer.phase.${job.phase}`) + (counted ? ` · ${job.done} / ${job.total}` : '')}
        {job.dry_run && ` (${t('transfer.dryRun')})`}
      </Typography>
      <LinearProgress variant={counted ? 'determinate' : 'indeterminate'}
        value={counted ? (job.done / job.total) * 100 : undefined} />
    </Stack>
  )
}

function ImportPanel({ choices }: { choices: TransferChoices }) {
  const { t, i18n } = useTranslation()
  const [file, setFile] = useState<File | null>(null)
  const [target, setTarget] = useState<number | ''>('')
  const [mode, setMode] = useState<'skip' | 'update'>('skip')
  // The import running in the worker (a preview or the real one), followed live.
  const [job, setJob] = useState<ImportJob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const report = job?.status === 'done' ? job.report : null
  const running = job?.status === 'queued' || job?.status === 'running'

  // Any change of file or options needs a new preview before importing.
  function reset() {
    setJob(null)
    setError(null)
  }

  async function start(request: Promise<ImportJob>) {
    setBusy(true)
    setError(null)
    try {
      setJob(await request)
    } catch (e) {
      setJob(null)
      setError(errorOf(e, t('common.error')))
    } finally {
      setBusy(false)
    }
  }

  function preview() {
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    form.append('mode', mode)
    form.append('target_team', String(target))
    form.append('dry_run', 'true')
    void start(apiUpload<ImportJob>('/transfer/import/', form))
  }

  // The real import reads the file the preview read, with the same options.
  function confirm() {
    if (job) void start(api<ImportJob>(`/transfer/jobs/${job.id}/confirm/`, { method: 'POST' }))
  }

  const reload = useCallback(() => {
    if (job) void api<ImportJob>(`/transfer/jobs/${job.id}/`).then(setJob).catch(() => undefined)
  }, [job])
  useOnConnect(reload)
  useRealtimeEvent<ImportJobEvent>('transfer', (event) => {
    if (!job || event.id !== job.id) return
    if (event.status === 'done' || event.status === 'failed') reload()
    else setJob({ ...job, ...event })
  })

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={2}>
        <Typography variant="h2">{t('transfer.import')}</Typography>
        <Typography variant="body2" color="text.secondary">{t('transfer.importHint')}</Typography>
        <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
          <Button variant="outlined" component="label" startIcon={<UploadIcon />}>
            {t('transfer.chooseFile')}
            <input type="file" accept="application/json,.json" hidden
              onChange={(e) => { setFile(e.target.files?.[0] ?? null); reset() }} />
          </Button>
          {file && <Chip label={file.name} onDelete={() => { setFile(null); reset() }} />}
        </Stack>
        <TextField select size="small" label={t('transfer.target')} value={target} sx={{ maxWidth: 360 }}
          onChange={(e) => { setTarget(e.target.value === '' ? '' : Number(e.target.value)); reset() }}
          helperText={t('transfer.targetHint')}>
          <MenuItem value="">{t('transfer.targetAuto')}</MenuItem>
          {choices.teams.map((c) => <MenuItem key={c.id} value={c.id}>{c.name}</MenuItem>)}
        </TextField>
        <ToggleButtonGroup exclusive size="small" value={mode}
          onChange={(_, v: 'skip' | 'update' | null) => { if (v) { setMode(v); reset() } }}>
          <ToggleButton value="skip">{t('transfer.mode.skip')}</ToggleButton>
          <ToggleButton value="update">{t('transfer.mode.update')}</ToggleButton>
        </ToggleButtonGroup>
        <Typography variant="body2" color="text.secondary">{t(`transfer.modeHint.${mode}`)}</Typography>
        <Stack direction="row" spacing={1}>
          <Button variant="outlined" disabled={!file || busy || running} onClick={preview}>
            {t('transfer.preview')}
          </Button>
          <Button variant="contained" disabled={!report?.dry_run || busy || running} onClick={confirm}>
            {t('transfer.confirm')}
          </Button>
        </Stack>
        {error && <Alert severity="error">{error}</Alert>}
        {job && running && <JobProgress job={job} />}
        {job?.status === 'failed' && <Alert severity="error">{t('transfer.failed', { error: job.error })}</Alert>}
        {report && (
          <>
            <Alert severity={report.dry_run ? 'info' : 'success'}>
              {report.dry_run
                ? t('transfer.previewOf', {
                    scope: t(`transfer.scope.${report.document.scope}`, { defaultValue: report.document.scope }),
                    date: new Date(report.document.exported_at).toLocaleString(i18n.resolvedLanguage),
                  })
                : t('transfer.done')}
            </Alert>
            <ReportView report={report} />
          </>
        )}
      </Stack>
    </Paper>
  )
}

/**
 * Export and import (administrators): a team, recipes or the system data as a JSON file, and
 * back, previewed before anything changes. See apps/transfer in the backend.
 */
export function TransferPage() {
  const { t } = useTranslation()
  const [choices, setChoices] = useState<TransferChoices | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    api<TransferChoices>('/transfer/choices/').then(setChoices).catch(() => setFailed(true))
  }, [])

  if (failed) return <Alert severity="error">{t('common.error')}</Alert>
  if (!choices) return null
  return (
    <Stack spacing={2}>
      <Typography variant="body2" color="text.secondary">{t('transfer.hint')}</Typography>
      <ExportPanel choices={choices} />
      <ImportPanel choices={choices} />
    </Stack>
  )
}
