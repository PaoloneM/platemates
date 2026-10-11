import { useState } from 'react'
import { api, type MenuLayout } from './api'
import { useAuth } from './auth/context'
import { useTeam } from './team'

/**
 * How the menu screen lays out the days: the user's choice, else the team's, else the
 * application's (`ui.menu_layout`, administrators). `choose` saves the user's choice; null
 * gives it back to the team.
 */
export function useMenuLayout(): {
  layout: MenuLayout
  own: MenuLayout | null
  choose: (layout: MenuLayout | null) => Promise<void>
} {
  const { me, refresh } = useAuth()
  const { team } = useTeam()
  const saved = me?.authenticated ? me.user.menu_layout : null
  // Shown at once, before the save comes back.
  const [pending, setPending] = useState<{ value: MenuLayout | null } | null>(null)
  const own = pending ? pending.value : saved
  const system = (me?.authenticated && me.settings['ui.menu_layout']) || 'vertical'
  async function choose(value: MenuLayout | null) {
    setPending({ value })
    try {
      await api('/me/', { method: 'PATCH', body: JSON.stringify({ menu_layout: value ?? '' }) })
      await refresh()
    } finally {
      setPending(null)
    }
  }
  return { layout: own ?? team.menu_layout ?? system, own, choose }
}
