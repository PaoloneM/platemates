import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/DeleteOutlined'
import EditIcon from '@mui/icons-material/EditOutlined'
import MergeIcon from '@mui/icons-material/MergeType'
import PromoteIcon from '@mui/icons-material/PublicOutlined'
import SearchIcon from '@mui/icons-material/Search'
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  InputAdornment,
  MenuItem,
  Paper,
  Snackbar,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  TableSortLabel,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type Ingredient, type Paginated } from '../../api'
import { IngredientDialog } from '../../components/IngredientDialog'
import { INGREDIENT_CATEGORIES, useDescribeMonths, useLabels } from '../../labels'

const PAGE_SIZE = 50
type Ordering = 'name' | '-usage' | '-shared' | 'category'
// System ingredients, or those teams added for themselves (to promote or merge).
type Owner = 'system' | 'teams'

/** Merge a duplicate into a system ingredient: recipes move over, its name becomes an alias. */
function MergeDialog({ source, onClose, onMerged }: {
  source: Ingredient
  onClose: () => void
  onMerged: (target: Ingredient) => void
}) {
  const { t } = useTranslation()
  const [input, setInput] = useState('')
  const [options, setOptions] = useState<Ingredient[]>([])
  const [target, setTarget] = useState<Ingredient | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!input.trim()) return
    const timer = setTimeout(() => {
      api<Paginated<Ingredient>>(`/ingredients/?owner=system&search=${encodeURIComponent(input.trim())}`)
        .then((page) => setOptions(page.results.filter((i) => i.id !== source.id)))
        .catch(() => undefined)
    }, 200)
    return () => clearTimeout(timer)
  }, [input, source.id])

  async function merge() {
    if (!target) return
    setBusy(true)
    const result = await api<{ ingredient: Ingredient }>(`/ingredients/${source.id}/merge/`, {
      method: 'POST',
      body: JSON.stringify({ into: target.id }),
    })
    onMerged(result.ingredient)
  }

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t('manage.ingredients.mergeTitle', { name: source.name })}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            {t('manage.ingredients.mergeHint', { name: source.name, count: source.usage_count })}
          </Typography>
          <Autocomplete
            options={options}
            value={target}
            getOptionLabel={(o) => o.name}
            isOptionEqualToValue={(a, b) => a.id === b.id}
            onInputChange={(_, v) => setInput(v)}
            onChange={(_, v) => setTarget(v)}
            noOptionsText={t('ingredient.typeToSearch')}
            renderInput={(params) => <TextField {...params} label={t('manage.ingredients.mergeInto')} autoFocus />}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="contained" onClick={() => void merge()} disabled={!target || busy}>
          {t('manage.ingredients.merge')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export function IngredientsPage() {
  const { t } = useTranslation()
  const labels = useLabels()
  const describeMonths = useDescribeMonths()
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [owner, setOwner] = useState<Owner>('system')
  const [ordering, setOrdering] = useState<Ordering>('name')
  const [page, setPage] = useState(0)
  const [data, setData] = useState<Paginated<Ingredient> | null>(null)
  const [editing, setEditing] = useState<Ingredient | 'new' | null>(null)
  const [merging, setMerging] = useState<Ingredient | null>(null)
  const [deleting, setDeleting] = useState<Ingredient | null>(null)
  const [deleteBlocked, setDeleteBlocked] = useState<string[] | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const load = useCallback(() => {
    const params = new URLSearchParams({ owner, ordering, page: String(page + 1) })
    if (search.trim()) params.set('search', search.trim())
    if (category) params.set('category', category)
    return api<Paginated<Ingredient>>(`/ingredients/?${params}`).then(setData)
  }, [search, category, owner, ordering, page])

  useEffect(() => {
    const timer = setTimeout(() => void load().catch(() => setMessage(t('common.error'))), 250)
    return () => clearTimeout(timer)
  }, [load, t])

  async function remove(ingredient: Ingredient) {
    try {
      await api(`/ingredients/${ingredient.id}/`, { method: 'DELETE' })
      setDeleting(null)
      setMessage(t('manage.ingredients.deleted', { name: ingredient.name }))
      void load()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setDeleteBlocked((e.body as { recipes: string[] }).recipes)
      } else setMessage(t('common.error'))
    }
  }

  async function promote(ingredient: Ingredient) {
    try {
      await api(`/ingredients/${ingredient.id}/promote/`, { method: 'POST' })
      setMessage(t('manage.ingredients.promoted', { name: ingredient.name }))
      void load()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // The system catalog has it already: merging is the way.
        setMessage(t('manage.ingredients.promoteClash', { name: ingredient.name }))
        setMerging(ingredient)
      } else setMessage(t('common.error'))
    }
  }

  function showOwner(value: Owner) {
    setOwner(value)
    // Team additions met in shared recipes first: other teams already see them.
    setOrdering(value === 'teams' ? '-shared' : 'name')
    setPage(0)
  }

  const teams = owner === 'teams'
  const sortable = (key: Ordering, label: string) => (
    <TableSortLabel active={ordering === key} direction={key.startsWith('-') ? 'desc' : 'asc'}
      onClick={() => { setOrdering(key); setPage(0) }}>
      {label}
    </TableSortLabel>
  )

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <Typography variant="h2" sx={{ flex: 1 }}>
          {t('manage.section.ingredients')}
          {data && (
            <Typography component="span" color="text.secondary" sx={{ ml: 1, fontSize: '1rem' }}>
              {data.count}
            </Typography>
          )}
        </Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setEditing('new')}>
          {t('manage.ingredients.new')}
        </Button>
      </Stack>
      <ToggleButtonGroup exclusive size="small" value={owner} onChange={(_, v: Owner | null) => v && showOwner(v)}>
        <ToggleButton value="system">{t('manage.ingredients.owner.system')}</ToggleButton>
        <ToggleButton value="teams">{t('manage.ingredients.owner.teams')}</ToggleButton>
      </ToggleButtonGroup>
      {teams && (
        <Typography variant="body2" color="text.secondary">{t('manage.ingredients.teamsHint')}</Typography>
      )}
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
        <TextField size="small" placeholder={t('manage.ingredients.search')} value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(0) }}
          slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment> } }} />
        <TextField size="small" select value={category} label={t('ingredient.category')}
          onChange={(e) => { setCategory(e.target.value); setPage(0) }} sx={{ minWidth: { sm: 240 } }}>
          <MenuItem value="">{t('manage.ingredients.allCategories')}</MenuItem>
          {INGREDIENT_CATEGORIES.map((c) => (
            <MenuItem key={c} value={c}>{labels.category(c)}</MenuItem>
          ))}
        </TextField>
      </Stack>

      <TableContainer component={Paper} variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{sortable('name', t('ingredient.name'))}</TableCell>
              <TableCell sx={{ display: { xs: 'none', sm: 'table-cell' } }}>
                {sortable('category', t('ingredient.category'))}
              </TableCell>
              {teams && <TableCell>{t('manage.ingredients.team')}</TableCell>}
              <TableCell sx={{ display: { xs: 'none', md: 'table-cell' } }}>{t('ingredient.unit')}</TableCell>
              <TableCell sx={{ display: { xs: 'none', md: 'table-cell' } }}>{t('ingredient.season')}</TableCell>
              <TableCell align="right">{sortable('-usage', t('manage.ingredients.recipes'))}</TableCell>
              {teams && (
                <TableCell align="right">{sortable('-shared', t('manage.ingredients.sharedRecipes'))}</TableCell>
              )}
              <TableCell align="right" />
            </TableRow>
          </TableHead>
          <TableBody>
            {data?.results.map((i) => (
              <TableRow key={i.id} hover onClick={() => setEditing(i)} sx={{ cursor: 'pointer' }}>
                <TableCell>
                  <Typography sx={{ fontWeight: 500 }}>{i.name}</Typography>
                  {i.aliases.length > 0 && (
                    <Typography variant="caption" color="text.secondary">{i.aliases.join(', ')}</Typography>
                  )}
                </TableCell>
                <TableCell sx={{ display: { xs: 'none', sm: 'table-cell' } }}>{labels.category(i.category)}</TableCell>
                {teams && <TableCell>{i.team_name}</TableCell>}
                <TableCell sx={{ display: { xs: 'none', md: 'table-cell' } }}>{labels.unit(i.default_unit)}</TableCell>
                <TableCell sx={{ display: { xs: 'none', md: 'table-cell' } }}>{describeMonths(i.season_months.months)}</TableCell>
                <TableCell align="right">{i.usage_count}</TableCell>
                {teams && <TableCell align="right">{i.shared_usage_count}</TableCell>}
                {/* The row opens the editor; these buttons must not also trigger it. */}
                <TableCell align="right" sx={{ whiteSpace: 'nowrap' }} onClick={(e) => e.stopPropagation()}>
                  {i.team != null && (
                    <Tooltip title={t('manage.ingredients.promote')}>
                      <IconButton size="small" onClick={() => void promote(i)}><PromoteIcon fontSize="small" /></IconButton>
                    </Tooltip>
                  )}
                  <Tooltip title={t('common.edit')}>
                    <IconButton size="small" onClick={() => setEditing(i)}><EditIcon fontSize="small" /></IconButton>
                  </Tooltip>
                  <Tooltip title={t('manage.ingredients.merge')}>
                    <IconButton size="small" onClick={() => setMerging(i)}><MergeIcon fontSize="small" /></IconButton>
                  </Tooltip>
                  <Tooltip title={t('common.delete')}>
                    <IconButton size="small" onClick={() => { setDeleting(i); setDeleteBlocked(null) }}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
            {data?.results.length === 0 && (
              <TableRow>
                <TableCell colSpan={teams ? 8 : 6}>
                  <Typography color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
                    {t('manage.ingredients.none')}
                  </Typography>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        <TablePagination component="div" count={data?.count ?? 0} page={page} rowsPerPage={PAGE_SIZE}
          rowsPerPageOptions={[PAGE_SIZE]} onPageChange={(_, p) => setPage(p)}
          labelDisplayedRows={({ from, to, count }) => t('manage.rows', { from, to, count })} />
      </TableContainer>

      {editing && (
        <IngredientDialog
          ingredient={editing === 'new' ? undefined : editing}
          withAliases
          onClose={() => setEditing(null)}
          onCreated={(i) => { setEditing(null); setMessage(t('manage.ingredients.created', { name: i.name })); void load() }}
          onSaved={(i) => { setEditing(null); setMessage(t('manage.ingredients.saved', { name: i.name })); void load() }}
        />
      )}
      {merging && (
        <MergeDialog source={merging} onClose={() => setMerging(null)}
          onMerged={(target) => {
            setMessage(t('manage.ingredients.merged', { name: merging.name, target: target.name }))
            setMerging(null)
            void load()
          }} />
      )}
      {deleting && (
        <Dialog open onClose={() => setDeleting(null)}>
          <DialogTitle>{t('manage.ingredients.deleteTitle', { name: deleting.name })}</DialogTitle>
          <DialogContent>
            {deleteBlocked ? (
              <Alert severity="warning">
                {t('manage.ingredients.inUse')}
                <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
                  {deleteBlocked.map((title) => <li key={title}>{title}</li>)}
                </Box>
              </Alert>
            ) : (
              <Typography>{t('manage.ingredients.deleteHint')}</Typography>
            )}
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setDeleting(null)}>{t('common.cancel')}</Button>
            {deleteBlocked ? (
              <Button variant="contained" onClick={() => { setMerging(deleting); setDeleting(null) }}>
                {t('manage.ingredients.merge')}
              </Button>
            ) : (
              <Button color="error" variant="contained" onClick={() => void remove(deleting)}>
                {t('common.delete')}
              </Button>
            )}
          </DialogActions>
        </Dialog>
      )}
      <Snackbar open={!!message} autoHideDuration={4000} onClose={() => setMessage(null)} message={message} />
    </Stack>
  )
}
