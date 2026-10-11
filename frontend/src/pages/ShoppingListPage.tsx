import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import DeleteIcon from '@mui/icons-material/DeleteOutlined'
import EditIcon from '@mui/icons-material/EditOutlined'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Checkbox,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  LinearProgress,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  ListSubheader,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, useNavigate, useParams } from 'react-router'
import {
  api,
  ApiError,
  type Ingredient,
  type Paginated,
  type ShoppingEvent,
  type ShoppingItem,
  type ShoppingList,
  type Unit,
} from '../api'
import { INGREDIENT_CATEGORIES, UNITS, useLabels } from '../labels'
import { useOnConnect, useRealtimeEvent } from '../realtime'
import { formatAmount } from '../shopping'

type Suggestion = Pick<Ingredient, 'id' | 'name'>

/**
 * One shopping list, made to be used in the shop: what is still to buy on top, by aisle; what
 * is in the cart below. Ticks show up live on the phones of everyone in the team.
 */
export function ShoppingListPage() {
  const { t } = useTranslation()
  const { id } = useParams()
  const navigate = useNavigate()
  const [list, setList] = useState<ShoppingList | null>(null)
  const [error, setError] = useState(false)
  const [cartOpen, setCartOpen] = useState(true)
  const [editing, setEditing] = useState<ShoppingItem | null>(null)
  const [renaming, setRenaming] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const load = useCallback(() => {
    api<ShoppingList>(`/shopping-lists/${id}/`)
      .then(setList)
      .catch((e: unknown) => {
        // Deleted, or merged into another list, by someone else.
        if (e instanceof ApiError && e.status === 404) navigate('/shopping', { replace: true })
        else setError(true)
      })
  }, [id, navigate])

  useEffect(load, [load])
  // Any change to the team's lists: a merge announces the new list, not the ones it replaced.
  useRealtimeEvent<ShoppingEvent>('shopping', (event) => {
    if (list && event.team === list.team) load()
  })
  useOnConnect(load)

  async function tick(item: ShoppingItem, bought: boolean) {
    setList((l) => l && { ...l, items: l.items.map((i) => (i.id === item.id ? { ...i, bought } : i)) })
    try {
      await api(`/shopping-items/${item.id}/`, { method: 'PATCH', body: JSON.stringify({ bought }) })
    } catch {
      load()
    }
  }

  async function deleteList() {
    await api(`/shopping-lists/${id}/`, { method: 'DELETE' })
    navigate('/shopping', { replace: true })
  }

  if (error) return <Alert severity="error">{t('common.error')}</Alert>
  if (!list) return <LinearProgress />

  const toBuy = list.items.filter((i) => !i.bought)
  const inCart = list.items.filter((i) => i.bought)

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <IconButton component={RouterLink} to="/shopping" aria-label={t('shopping.back')} edge="start">
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h1" sx={{ flex: 1, minWidth: 0 }} noWrap>{list.title}</Typography>
        <IconButton aria-label={t('shopping.rename')} onClick={() => setRenaming(true)}><EditIcon /></IconButton>
        <IconButton aria-label={t('shopping.delete')} onClick={() => setDeleting(true)}><DeleteIcon /></IconButton>
      </Stack>

      <AddItem list={list} onAdded={load} />

      {toBuy.length === 0 ? (
        <Typography color="text.secondary">
          {list.items.length ? t('shopping.allBought') : t('shopping.empty')}
        </Typography>
      ) : (
        <Paper variant="outlined">
          <ItemsByAisle items={toBuy} onTick={tick} onEdit={setEditing} />
        </Paper>
      )}

      {inCart.length > 0 && (
        <Paper variant="outlined">
          <ListItemButton onClick={() => setCartOpen((o) => !o)}>
            <ListItemText primary={t('shopping.inCart', { count: inCart.length })}
              slotProps={{ primary: { sx: { fontWeight: 500 } } }} />
            {cartOpen ? <ExpandLessIcon /> : <ExpandMoreIcon />}
          </ListItemButton>
          <Collapse in={cartOpen}>
            <List dense disablePadding>
              {inCart.map((item) => (
                <ItemRow key={item.id} item={item} onTick={tick} onEdit={setEditing} />
              ))}
            </List>
          </Collapse>
        </Paper>
      )}

      {editing && (
        <EditItemDialog item={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load() }} />
      )}
      {renaming && (
        <RenameDialog list={list} onClose={() => setRenaming(false)} onSaved={() => { setRenaming(false); load() }} />
      )}
      <Dialog open={deleting} onClose={() => setDeleting(false)}>
        <DialogTitle>{t('shopping.deleteTitle')}</DialogTitle>
        <DialogContent><Typography>{t('shopping.deleteConfirm')}</Typography></DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleting(false)}>{t('common.cancel')}</Button>
          <Button color="error" variant="contained" onClick={() => void deleteList()}>{t('common.delete')}</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  )
}

function ItemsByAisle({ items, onTick, onEdit }: {
  items: ShoppingItem[]
  onTick: (item: ShoppingItem, bought: boolean) => void
  onEdit: (item: ShoppingItem) => void
}) {
  const labels = useLabels()
  const groups = useMemo(() => {
    const order = (c: string) => {
      const index = INGREDIENT_CATEGORIES.indexOf(c)
      return index < 0 ? INGREDIENT_CATEGORIES.length : index
    }
    const byCategory = new Map<string, ShoppingItem[]>()
    for (const item of items) byCategory.set(item.category, [...(byCategory.get(item.category) ?? []), item])
    return [...byCategory.entries()].sort(([a], [b]) => order(a) - order(b))
  }, [items])

  return (
    <List dense disablePadding>
      {groups.map(([category, group]) => (
        <li key={category}>
          <ul style={{ padding: 0 }}>
            <ListSubheader sx={{ lineHeight: 2.5, bgcolor: 'background.paper' }}>{labels.category(category)}</ListSubheader>
            {group.map((item) => <ItemRow key={item.id} item={item} onTick={onTick} onEdit={onEdit} />)}
          </ul>
        </li>
      ))}
    </List>
  )
}

function ItemRow({ item, onTick, onEdit }: {
  item: ShoppingItem
  onTick: (item: ShoppingItem, bought: boolean) => void
  onEdit: (item: ShoppingItem) => void
}) {
  const { t, i18n } = useTranslation()
  const labels = useLabels()
  const amount = formatAmount(item, labels.unit, i18n.resolvedLanguage)
  const secondary = [item.optional ? t('shopping.optional') : '', item.note].filter(Boolean).join(' · ')
  return (
    <ListItem disablePadding secondaryAction={
      amount && <Typography variant="body2" color="text.secondary" sx={{ textDecoration: item.bought ? 'line-through' : undefined }}>{amount}</Typography>
    }>
      <ListItemIcon sx={{ minWidth: 0, pl: 1 }}>
        <Checkbox checked={item.bought} onChange={(e) => onTick(item, e.target.checked)}
          slotProps={{ input: { 'aria-label': item.name } }} />
      </ListItemIcon>
      <ListItemButton onClick={() => onEdit(item)} sx={{ pl: 0.5, pr: amount ? 12 : 2 }}>
        <ListItemText
          primary={item.name}
          secondary={secondary || undefined}
          slotProps={{ primary: { sx: item.bought ? { textDecoration: 'line-through', color: 'text.secondary' } : undefined } }}
        />
      </ListItemButton>
    </ListItem>
  )
}

/** Something to buy: an ingredient from the team's catalog, or anything typed (soap, foil). */
function AddItem({ list, onAdded }: { list: ShoppingList; onAdded: () => void }) {
  const { t } = useTranslation()
  const [input, setInput] = useState('')
  const [options, setOptions] = useState<Suggestion[]>([])
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const term = input.trim()
    if (!term) return
    let cancelled = false
    const timer = setTimeout(() => {
      api<Paginated<Ingredient>>(`/ingredients/?team=${list.team}&search=${encodeURIComponent(term)}`)
        .then((page) => { if (!cancelled) setOptions(page.results) })
        .catch(() => undefined)
    }, 200)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [input, list.team])

  async function add(value: Suggestion | string | null) {
    const name = typeof value === 'string' ? value.trim() : ''
    if (!value || (typeof value === 'string' && !name)) return
    setBusy(true)
    try {
      await api('/shopping-items/', {
        method: 'POST',
        body: JSON.stringify(typeof value === 'string'
          ? { shopping_list: list.id, name }
          : { shopping_list: list.id, ingredient: value.id }),
      })
      setInput('')
      setOptions([])
      onAdded()
    } finally {
      setBusy(false)
    }
  }

  return (
    <Autocomplete<Suggestion, false, false, true>
      freeSolo
      value={null}
      inputValue={input}
      onInputChange={(_, value, reason) => { if (reason !== 'reset') setInput(value) }}
      onChange={(_, value) => void add(value)}
      options={input.trim() ? options : []}
      filterOptions={(o) => o}
      getOptionLabel={(o) => (typeof o === 'string' ? o : o.name)}
      disabled={busy}
      renderInput={(params) => (
        <TextField {...params} size="small" placeholder={t('shopping.addPlaceholder')} />
      )}
    />
  )
}

function EditItemDialog({ item, onClose, onSaved }: {
  item: ShoppingItem
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useTranslation()
  const labels = useLabels()
  const [name, setName] = useState(item.name)
  const [quantity, setQuantity] = useState(item.quantity === null ? '' : String(Number(item.quantity)))
  const [unit, setUnit] = useState<Unit>(item.unit)
  const [category, setCategory] = useState(item.category)
  const [note, setNote] = useState(item.note)
  const [error, setError] = useState(false)

  async function save() {
    try {
      await api(`/shopping-items/${item.id}/`, {
        method: 'PATCH',
        body: JSON.stringify({
          name, unit, category, note,
          quantity: unit === 'tt' || quantity.trim() === '' ? null : quantity.replace(',', '.'),
        }),
      })
      onSaved()
    } catch {
      setError(true)
    }
  }

  async function remove() {
    await api(`/shopping-items/${item.id}/`, { method: 'DELETE' })
    onSaved()
  }

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{t('shopping.editItem')}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {error && <Alert severity="error">{t('common.error')}</Alert>}
          <TextField label={t('shopping.name')} value={name} onChange={(e) => setName(e.target.value)} />
          <Stack direction="row" spacing={1}>
            <TextField label={t('shopping.quantity')} value={unit === 'tt' ? '' : quantity} disabled={unit === 'tt'}
              onChange={(e) => setQuantity(e.target.value)} sx={{ flex: 1 }}
              slotProps={{ htmlInput: { inputMode: 'decimal' } }} />
            <TextField select label={t('shopping.unit')} value={unit} onChange={(e) => setUnit(e.target.value as Unit)}
              sx={{ width: 120 }}>
              {UNITS.map((u) => <MenuItem key={u} value={u}>{labels.unit(u)}</MenuItem>)}
            </TextField>
          </Stack>
          <TextField select label={t('shopping.aisle')} value={category} onChange={(e) => setCategory(e.target.value)}>
            {INGREDIENT_CATEGORIES.map((c) => <MenuItem key={c} value={c}>{labels.category(c)}</MenuItem>)}
          </TextField>
          <TextField label={t('shopping.note')} value={note} onChange={(e) => setNote(e.target.value)} />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Box sx={{ flex: 1 }}>
          <Button color="error" startIcon={<DeleteIcon />} onClick={() => void remove()}>{t('common.delete')}</Button>
        </Box>
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="contained" disabled={!name.trim()} onClick={() => void save()}>{t('common.save')}</Button>
      </DialogActions>
    </Dialog>
  )
}

function RenameDialog({ list, onClose, onSaved }: { list: ShoppingList; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation()
  const [title, setTitle] = useState(list.title)
  async function save() {
    await api(`/shopping-lists/${list.id}/`, { method: 'PATCH', body: JSON.stringify({ title }) })
    onSaved()
  }
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{t('shopping.rename')}</DialogTitle>
      <DialogContent>
        <TextField autoFocus fullWidth label={t('shopping.listTitle')} value={title}
          onChange={(e) => setTitle(e.target.value)} sx={{ mt: 1 }} />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="contained" disabled={!title.trim()} onClick={() => void save()}>{t('common.save')}</Button>
      </DialogActions>
    </Dialog>
  )
}
