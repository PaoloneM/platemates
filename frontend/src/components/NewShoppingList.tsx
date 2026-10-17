import { Button, Snackbar } from '@mui/material'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { api, ApiError, type ShoppingListSummary } from '../api'
import type { ShoppingFor } from '../shopping'
import { useTeam } from '../team'

/**
 * Makes a shopping list for a day, a meal or a recipe, and says so where the user is, with a
 * way to open it: they usually stay on the menu or the recipe.
 */
export function useNewShoppingList() {
  const { t } = useTranslation()
  const { team } = useTeam()
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<{ message: string; list?: number } | null>(null)

  async function create(what: ShoppingFor) {
    setBusy(true)
    try {
      const created = await api<ShoppingListSummary>('/shopping-lists/generate/', {
        method: 'POST',
        body: JSON.stringify({ team: team.id, ...what }),
      })
      setNotice({ message: t('shopping.created', { title: created.title }), list: created.id })
    } catch (e) {
      const code = e instanceof ApiError ? (e.body as { code?: string } | null)?.code : undefined
      setNotice({ message: code === 'nothing_to_buy' ? t('shopping.nothingToBuy') : t('common.error') })
    } finally {
      setBusy(false)
    }
  }

  const snackbar = (
    <Snackbar open={!!notice} autoHideDuration={6000} onClose={() => setNotice(null)} message={notice?.message}
      action={notice?.list !== undefined && (
        <Button color="inherit" size="small" onClick={() => navigate(`/shopping/${notice.list}`)}>
          {t('shopping.open')}
        </Button>
      )} />
  )
  return { create, busy, snackbar }
}
