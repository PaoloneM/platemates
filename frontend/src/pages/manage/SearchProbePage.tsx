import SearchIcon from '@mui/icons-material/Search'
import {
  Alert,
  Box,
  Button,
  Chip,
  FormControlLabel,
  LinearProgress,
  Link,
  Paper,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink } from 'react-router'
import { api, type ConfigSetting, type SearchProbe, type SearchTuning } from '../../api'
import { useLabels } from '../../labels'

const TUNING: (keyof SearchTuning)[] = ['min_similarity', 'margin', 'keyword_bonus']

function Facts({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={{ xs: 0.5, sm: 2 }} sx={{ alignItems: { sm: 'baseline' } }}>
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>{label}</Typography>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>{children}</Box>
    </Stack>
  )
}

/**
 * For administrators tuning recipe search: how a request is read and how every recipe ranks,
 * with the `search.*` settings or other values tried here only (saved in Settings).
 */
export function SearchProbePage() {
  const { t, i18n } = useTranslation()
  const labels = useLabels()
  const [text, setText] = useState('')
  const [plain, setPlain] = useState(false)
  const [tuning, setTuning] = useState<Record<keyof SearchTuning, string>>({ min_similarity: '', margin: '', keyword_bonus: '' })
  const [probe, setProbe] = useState<SearchProbe | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)

  // Start from the current settings.
  useEffect(() => {
    api<ConfigSetting[]>('/config/')
      .then((all) => {
        const value = (name: string) => String(all.find((s) => s.key === `search.${name}`)?.value ?? '')
        setTuning({ min_similarity: value('min_similarity'), margin: value('margin'), keyword_bonus: value('keyword_bonus') })
      })
      .catch(() => undefined)
  }, [])

  async function run() {
    if (!text.trim()) return
    setBusy(true)
    setError(false)
    try {
      const body: Record<string, unknown> = { text: text.trim(), plain, language: i18n.resolvedLanguage === 'en' ? 'en' : 'it' }
      for (const name of TUNING) if (tuning[name] !== '') body[name] = Number(tuning[name])
      setProbe(await api<SearchProbe>('/search-probe/', { method: 'POST', body: JSON.stringify(body) }))
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }

  const fraction = (n: number) => n.toLocaleString(i18n.resolvedLanguage, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const best = probe ? Math.max(0, ...probe.results.map((r) => r.similarity)) : 0

  return (
    <Stack spacing={2}>
      <Typography color="text.secondary">
        {t('probe.hint')}{' '}
        <Link component={RouterLink} to="/manage/settings">{t('probe.settingsLink')}</Link>
      </Typography>

      <Paper variant="outlined" sx={{ p: 2 }}>
        <Stack spacing={2} component="form" onSubmit={(e) => { e.preventDefault(); void run() }}>
          <TextField label={t('probe.request')} value={text} onChange={(e) => setText(e.target.value)}
            placeholder={t('probe.placeholder')} fullWidth autoFocus />
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ alignItems: { md: 'center' } }}>
            {TUNING.map((name) => (
              <TextField key={name} size="small" type="number" label={t(`probe.tuning.${name}`)}
                value={tuning[name]} onChange={(e) => setTuning((v) => ({ ...v, [name]: e.target.value }))}
                slotProps={{ htmlInput: { min: 0, max: 100 } }} sx={{ width: { md: 190 } }} />
            ))}
            <FormControlLabel control={<Switch checked={plain} onChange={(e) => setPlain(e.target.checked)} />}
              label={t('probe.plain')} />
            <Box sx={{ flex: 1 }} />
            <Button type="submit" variant="contained" startIcon={<SearchIcon />} disabled={busy || !text.trim()}>
              {t('probe.run')}
            </Button>
          </Stack>
          <Typography variant="caption" color="text.secondary">{t('probe.tuningHint')}</Typography>
        </Stack>
      </Paper>

      {busy && <LinearProgress />}
      {error && <Alert severity="error">{t('common.error')}</Alert>}

      {probe && (
        <>
          <Paper variant="outlined" sx={{ p: 2 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>{t('probe.readAs')}</Typography>
            <Stack spacing={1}>
              <Facts label={t('probe.query')}><Typography>{probe.request.query}</Typography></Facts>
              <Facts label={t('probe.keywords')}>
                {probe.request.keywords.length ? probe.request.keywords.map((k) => <Chip key={k} size="small" label={k} />)
                  : <Typography color="text.secondary">—</Typography>}
              </Facts>
              <Facts label={t('probe.dishes')}>
                {probe.request.dishes.map((d) => <Chip key={d} size="small" variant="outlined" label={d} />)}
              </Facts>
              <Facts label={t('probe.excluded')}>
                {probe.request.exclude_categories.length + probe.request.exclude_ingredients.length ? (
                  <>
                    {probe.request.exclude_categories.map((c) => <Chip key={c} size="small" color="error" variant="outlined" label={labels.category(c)} />)}
                    {probe.request.exclude_ingredients.map((i) => <Chip key={i} size="small" color="error" variant="outlined" label={i} />)}
                  </>
                ) : <Typography color="text.secondary">—</Typography>}
              </Facts>
              <Facts label={t('probe.threshold')}>
                <Typography>
                  {t('probe.thresholdValue', {
                    floor: fraction(probe.tuning.min_similarity / 100),
                    bar: fraction(Math.max(probe.tuning.min_similarity / 100, best - probe.tuning.margin / 100)),
                  })}
                </Typography>
              </Facts>
            </Stack>
          </Paper>

          <Paper variant="outlined" sx={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t('probe.recipe')}</TableCell>
                  <TableCell align="right">{t('probe.similarity')}</TableCell>
                  <TableCell align="center">{t('probe.keyword')}</TableCell>
                  <TableCell align="right">{t('probe.score')}</TableCell>
                  <TableCell>{t('probe.outcome')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {probe.results.length === 0 && (
                  <TableRow><TableCell colSpan={5}><Typography color="text.secondary">{t('probe.none')}</Typography></TableCell></TableRow>
                )}
                {probe.results.map((r) => (
                  <TableRow key={r.recipe} sx={{ opacity: r.kept ? 1 : 0.6 }}>
                    <TableCell>
                      <Link component={RouterLink} to={`/recipes/${r.recipe}`}>{r.title}</Link>
                    </TableCell>
                    <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>{fraction(r.similarity)}</TableCell>
                    <TableCell align="center">{r.keyword ? '✓' : ''}</TableCell>
                    <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>{fraction(r.score)}</TableCell>
                    <TableCell>
                      {r.kept
                        ? <Chip size="small" color="success" label={r.keyword ? t('probe.keptKeyword') : t('probe.kept')} />
                        : <Typography variant="body2" color="text.secondary">{t('probe.dropped')}</Typography>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Paper>
          <Typography variant="caption" color="text.secondary">{t('probe.legend')}</Typography>
        </>
      )}
    </Stack>
  )
}
