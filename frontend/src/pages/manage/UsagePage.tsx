import EditIcon from '@mui/icons-material/EditOutlined'
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type ModelPrice, type UsageCounts, type UsageReport } from '../../api'

const PRICE_FIELDS = [
  'input_per_mtok',
  'output_per_mtok',
  'cache_read_per_mtok',
  'cache_write_per_mtok',
  'per_thousand_searches',
] as const

function useFormat() {
  const { i18n } = useTranslation()
  const locale = i18n.resolvedLanguage
  return {
    number: (n: number) => n.toLocaleString(locale),
    cost: (n: number) => n.toLocaleString(locale, { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 4 }),
  }
}

/** A cost, with a mark when some of the calls had no price (local models). */
function Cost({ row }: { row: UsageCounts }) {
  const { t } = useTranslation()
  const format = useFormat()
  return (
    <>
      {format.cost(Number(row.cost))}
      {row.unpriced_calls > 0 && (
        <Tooltip title={t('usage.unpriced', { count: row.unpriced_calls })}>
          <Typography component="span" color="text.secondary"> *</Typography>
        </Tooltip>
      )}
    </>
  )
}

function CountsCells({ row }: { row: UsageCounts }) {
  const format = useFormat()
  return (
    <>
      <TableCell align="right">{format.number(row.calls)}</TableCell>
      <TableCell align="right" sx={{ display: { xs: 'none', sm: 'table-cell' } }}>{format.number(row.input_tokens)}</TableCell>
      <TableCell align="right" sx={{ display: { xs: 'none', sm: 'table-cell' } }}>{format.number(row.output_tokens)}</TableCell>
      <TableCell align="right" sx={{ display: { xs: 'none', md: 'table-cell' } }}>{format.number(row.web_searches)}</TableCell>
      <TableCell align="right" sx={{ fontWeight: 600 }}><Cost row={row} /></TableCell>
    </>
  )
}

function CountsHead({ first }: { first: string }) {
  const { t } = useTranslation()
  return (
    <TableHead>
      <TableRow>
        <TableCell>{first}</TableCell>
        <TableCell align="right">{t('usage.calls')}</TableCell>
        <TableCell align="right" sx={{ display: { xs: 'none', sm: 'table-cell' } }}>{t('usage.input')}</TableCell>
        <TableCell align="right" sx={{ display: { xs: 'none', sm: 'table-cell' } }}>{t('usage.output')}</TableCell>
        <TableCell align="right" sx={{ display: { xs: 'none', md: 'table-cell' } }}>{t('usage.searches')}</TableCell>
        <TableCell align="right">{t('usage.cost')}</TableCell>
      </TableRow>
    </TableHead>
  )
}

function PriceDialog({ price, onClose, onSaved }: {
  price: ModelPrice
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useTranslation()
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(PRICE_FIELDS.map((f) => [f, price[f]])),
  )
  const [error, setError] = useState(false)
  async function save() {
    try {
      await api(`/usage/prices/${price.id}/`, { method: 'PATCH', body: JSON.stringify(values) })
      onSaved()
    } catch {
      setError(true)
    }
  }
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{price.model}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {PRICE_FIELDS.map((field) => (
            <TextField key={field} size="small" type="number" label={t(`usage.price.${field}`)} value={values[field]}
              onChange={(e) => setValues({ ...values, [field]: e.target.value })}
              slotProps={{ htmlInput: { min: 0, step: '0.01' } }} />
          ))}
          {error && <Alert severity="error">{t('common.error')}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="contained" onClick={() => void save()}>{t('common.save')}</Button>
      </DialogActions>
    </Dialog>
  )
}

/**
 * What the AI providers consumed, by team, feature and model, with costs estimated from the
 * price list below (administrators). Costs are estimates: the providers' invoices are what
 * counts.
 */
export function UsagePage() {
  const { t } = useTranslation()
  const format = useFormat()
  const [month, setMonth] = useState('')
  const [report, setReport] = useState<UsageReport | null>(null)
  const [prices, setPrices] = useState<ModelPrice[]>([])
  const [editing, setEditing] = useState<ModelPrice | null>(null)
  const [failed, setFailed] = useState(false)

  const load = useCallback(() => {
    const query = month ? `?month=${month}` : ''
    Promise.all([api<UsageReport>(`/usage/${query}`), api<ModelPrice[]>('/usage/prices/')])
      .then(([r, p]) => { setReport(r); setPrices(p) })
      .catch(() => setFailed(true))
  }, [month])

  useEffect(() => { load() }, [load])

  if (failed) return <Alert severity="error">{t('common.error')}</Alert>
  if (!report) return null
  const months = report.months.includes(report.month) ? report.months : [report.month, ...report.months]

  return (
    <Stack spacing={2.5}>
      <Typography variant="body2" color="text.secondary">{t('usage.hint')}</Typography>
      <Stack direction="row" spacing={2} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
        <TextField select size="small" label={t('usage.month')} value={report.month}
          onChange={(e) => setMonth(e.target.value)} sx={{ minWidth: 160 }}>
          {months.map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}
        </TextField>
        {report.totals && (
          <Typography variant="h2" component="p">
            {t('usage.total')}: <Cost row={report.totals} />
            <Typography component="span" color="text.secondary" sx={{ ml: 1.5, fontSize: '1rem' }}>
              {t('usage.callsCount', { count: report.totals.calls, formatted: format.number(report.totals.calls) })}
            </Typography>
          </Typography>
        )}
      </Stack>

      {!report.totals ? (
        <Typography color="text.secondary">{t('usage.none')}</Typography>
      ) : (
        <>
          <Typography variant="h3">{t('usage.byTeam')}</Typography>
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <CountsHead first={t('usage.team')} />
              <TableBody>
                {report.teams.map((row) => (
                  <TableRow key={row.team_id ?? 'none'}>
                    <TableCell>
                      <Typography sx={{ fontWeight: 500 }}>{row.team ?? t('usage.noTeam')}</Typography>
                      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
                        {Object.entries(row.features).map(([feature, cost]) => (
                          <Chip key={feature} size="small" variant="outlined"
                            label={`${t(`usage.feature.${feature}`)} ${format.cost(Number(cost))}`} />
                        ))}
                      </Box>
                    </TableCell>
                    <CountsCells row={row} />
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>

          <Stack spacing={2.5}>
            <Box sx={{ flex: 1 }}>
              <Typography variant="h3" sx={{ mb: 1 }}>{t('usage.byFeature')}</Typography>
              <TableContainer component={Paper} variant="outlined">
                <Table size="small">
                  <CountsHead first={t('usage.featureLabel')} />
                  <TableBody>
                    {report.features.map((row) => (
                      <TableRow key={row.feature}>
                        <TableCell>{t(`usage.feature.${row.feature}`)}</TableCell>
                        <CountsCells row={row} />
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Box>
            <Box sx={{ flex: 1 }}>
              <Typography variant="h3" sx={{ mb: 1 }}>{t('usage.byModel')}</Typography>
              <TableContainer component={Paper} variant="outlined">
                <Table size="small">
                  <CountsHead first={t('usage.model')} />
                  <TableBody>
                    {report.models.map((row) => (
                      <TableRow key={`${row.provider}/${row.model}`}>
                        <TableCell>
                          {row.model}
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                            {row.provider}{!row.priced && ` · ${t('usage.noPrice')}`}
                          </Typography>
                        </TableCell>
                        <CountsCells row={row} />
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Box>
          </Stack>
        </>
      )}

      <Typography variant="h3">{t('usage.prices')}</Typography>
      <Typography variant="body2" color="text.secondary">{t('usage.pricesHint')}</Typography>
      <TableContainer component={Paper} variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t('usage.model')}</TableCell>
              {PRICE_FIELDS.map((f) => (
                <TableCell key={f} align="right" sx={{ display: { xs: 'none', sm: 'table-cell' } }}>
                  {t(`usage.price.${f}`)}
                </TableCell>
              ))}
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {prices.map((p) => (
              <TableRow key={p.id}>
                <TableCell>{p.model}</TableCell>
                {PRICE_FIELDS.map((f) => (
                  <TableCell key={f} align="right" sx={{ display: { xs: 'none', sm: 'table-cell' } }}>
                    {format.cost(Number(p[f]))}
                  </TableCell>
                ))}
                <TableCell align="right">
                  <Tooltip title={t('common.edit')}>
                    <IconButton size="small" onClick={() => setEditing(p)}><EditIcon fontSize="small" /></IconButton>
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      {editing && (
        <PriceDialog price={editing} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load() }} />
      )}
    </Stack>
  )
}
