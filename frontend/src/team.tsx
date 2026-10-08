import { createContext, useContext, useState, type ReactNode } from 'react'
import { useAuth } from './auth/context'

type Team = { id: number; name: string; role: 'owner' | 'member' }
type TeamState = { team: Team; teams: Team[]; select: (id: number) => void }

const TeamContext = createContext<TeamState | null>(null)
const STORAGE_KEY = 'platemates.team'

function storedTeamId(): number | null {
  try {
    const value = Number(localStorage.getItem(STORAGE_KEY))
    return Number.isFinite(value) && value > 0 ? value : null
  } catch {
    return null
  }
}

/** The team the user is working on. Remembered per browser; the first one by default. */
export function TeamProvider({ children }: { children: ReactNode }) {
  const { me } = useAuth()
  const teams = me?.authenticated ? me.teams : []
  const [selected, setSelected] = useState<number | null>(storedTeamId)
  const team = teams.find((f) => f.id === selected) ?? teams[0]

  function select(id: number) {
    setSelected(id)
    try {
      localStorage.setItem(STORAGE_KEY, String(id))
    } catch {
      // Not remembered: the choice still holds for this page.
    }
  }

  if (!team) return null
  return (
    <TeamContext.Provider value={{ team, teams, select }}>{children}</TeamContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useTeam(): TeamState {
  const state = useContext(TeamContext)
  if (!state) throw new Error('useTeam must be used inside <TeamProvider>')
  return state
}
