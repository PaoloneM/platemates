import MergeIcon from '@mui/icons-material/CallMergeOutlined'
import {
  Alert,
  Box,
  Button,
  Card,
  CardActionArea,
  CardContent,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  Stack,
  Typography,
} from '@mui/material'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, useNavigate } from 'react-router'
import { api, type ShoppingEvent, type ShoppingListSummary, type ShoppingWeek } from '../api'
import { useOnConnect, useRealtimeEvent } from '../realtime'
import { weekRange } from '../shopping'
import { useTeam } from '../team'

/**
 * The shopping section: the weeks (from the current one on) with a menu to shop for and no
 * list yet, each generating a new list; and the team's lists, which can be merged into one.
 */
export function ShoppingPage() {
  const { t, i18n } = useTranslation()
  const { team } = useTeam()
  const navigate = useNavigate()
  const [weeks, setWeeks] = useState<ShoppingWeek[] | null>(null)
  const [lists, setLists] = useState<ShoppingListSummary[] | null>(null)
  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState<number[]>([])
  const [confirmMerge, setConfirmMerge] = useState(false)
  const [busy, setBusy] = useState<number | 'merge' | null>(null)
  const [error, setError] = useState(false)

  const load = useCallback(() => {
    Promise.all([
      api<ShoppingWeek[]>(`/shopping-lists/weeks/?team=${team.id}`),
      api<ShoppingListSummary[]>(`/shopping-lists/?team=${team.id}`),
    ])
      .then(([w, l]) => {
        setWeeks(w)
        setLists(l)
      })
      .catch(() => setError(true))
  }, [team.id])

  useEffect(load, [load])
  useRealtimeEvent<ShoppingEvent>('shopping', (event) => {
    if (event.team === team.id) load()
  })
  useOnConnect(load)

  async function generate(week: ShoppingWeek) {
    setBusy(week.menu)
    try {
      const created = await api<ShoppingListSummary>('/shopping-lists/generate/', {
        method: 'POST',
        body: JSON.stringify({ menu: week.menu }),
      })
      navigate(`/shopping/${created.id}`)
    } catch {
      setError(true)
      setBusy(null)
    }
  }

  async function merge() {
    setBusy('merge')
    try {
      const merged = await api<ShoppingListSummary>('/shopping-lists/merge/', {
        method: 'POST',
        body: JSON.stringify({ lists: selected }),
      })
      navigate(`/shopping/${merged.id}`)
    } catch {
      setError(true)
      setBusy(null)
    }
  }

  const toggle = (id: number) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))

  if (error) return <Alert severity="error">{t('common.error')}</Alert>
  if (!weeks || !lists) return <LinearProgress />

  return (
    <Stack spacing={3}>
      <Typography variant="h1">{t('shopping.title')}</Typography>

      <Stack spacing={1.5}>
        <Typography variant="h2">{t('shopping.weeks')}</Typography>
        {weeks.length === 0 ? (
          <Typography color="text.secondary">{t('shopping.noWeeks')}</Typography>
        ) : (
          weeks.map((week) => (
            <Card key={week.menu} variant="outlined">
              <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 2, '&:last-child': { pb: 2 } }}>
                <Typography sx={{ flex: 1 }}>{weekRange([week.week_start], i18n.resolvedLanguage)}</Typography>
                <Button variant="contained" disabled={busy !== null} onClick={() => void generate(week)}>
                  {t('shopping.generate')}
                </Button>
              </CardContent>
            </Card>
          ))
        )}
      </Stack>

      <Stack spacing={1.5}>
        <Stack direction="row" sx={{ alignItems: 'center' }}>
          <Typography variant="h2" sx={{ flex: 1 }}>{t('shopping.lists')}</Typography>
          {lists.length > 1 && (
            selecting ? (
              <Stack direction="row" spacing={1}>
                <Button onClick={() => { setSelecting(false); setSelected([]) }}>{t('common.cancel')}</Button>
                <Button variant="contained" startIcon={<MergeIcon />} disabled={selected.length < 2}
                  onClick={() => setConfirmMerge(true)}>
                  {t('shopping.merge', { count: selected.length })}
                </Button>
              </Stack>
            ) : (
              <Button startIcon={<MergeIcon />} onClick={() => setSelecting(true)}>{t('shopping.mergeStart')}</Button>
            )
          )}
        </Stack>
        {selecting && <Typography variant="body2" color="text.secondary">{t('shopping.mergeHint')}</Typography>}
        {lists.length === 0 && <Typography color="text.secondary">{t('shopping.noLists')}</Typography>}
        {lists.map((list) => {
          const done = list.total > 0 && list.bought === list.total
          const content = (
            <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 1.5, '&:last-child': { pb: 2 } }}>
              {selecting && <Checkbox checked={selected.includes(list.id)} sx={{ p: 0 }} />}
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography sx={{ fontWeight: 500 }} noWrap>{list.title}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {done ? t('shopping.allBought') : t('shopping.progress', { bought: list.bought, total: list.total })}
                </Typography>
                <LinearProgress variant="determinate" value={list.total ? (100 * list.bought) / list.total : 0}
                  sx={{ mt: 1, borderRadius: 1 }} />
              </Box>
            </CardContent>
          )
          return (
            <Card key={list.id} variant="outlined">
              {selecting ? (
                <CardActionArea onClick={() => toggle(list.id)}>{content}</CardActionArea>
              ) : (
                <CardActionArea component={RouterLink} to={`/shopping/${list.id}`}>{content}</CardActionArea>
              )}
            </Card>
          )
        })}
      </Stack>

      <Dialog open={confirmMerge} onClose={() => setConfirmMerge(false)}>
        <DialogTitle>{t('shopping.mergeTitle', { count: selected.length })}</DialogTitle>
        <DialogContent>
          <Typography>{t('shopping.mergeConfirm')}</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmMerge(false)}>{t('common.cancel')}</Button>
          <Button variant="contained" disabled={busy === 'merge'} onClick={() => void merge()}>
            {t('shopping.merge', { count: selected.length })}
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  )
}
