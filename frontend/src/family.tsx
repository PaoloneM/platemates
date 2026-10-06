import { createContext, useContext, useState, type ReactNode } from 'react'
import { useAuth } from './auth/context'

type Family = { id: number; name: string; role: 'owner' | 'member' }
type FamilyState = { family: Family; families: Family[]; select: (id: number) => void }

const FamilyContext = createContext<FamilyState | null>(null)
const STORAGE_KEY = 'mymenu.family'

function storedFamilyId(): number | null {
  try {
    const value = Number(localStorage.getItem(STORAGE_KEY))
    return Number.isFinite(value) && value > 0 ? value : null
  } catch {
    return null
  }
}

/** The family the user is working on. Remembered per browser; the first one by default. */
export function FamilyProvider({ children }: { children: ReactNode }) {
  const { me } = useAuth()
  const families = me?.authenticated ? me.families : []
  const [selected, setSelected] = useState<number | null>(storedFamilyId)
  const family = families.find((f) => f.id === selected) ?? families[0]

  function select(id: number) {
    setSelected(id)
    try {
      localStorage.setItem(STORAGE_KEY, String(id))
    } catch {
      // Not remembered: the choice still holds for this page.
    }
  }

  if (!family) return null
  return (
    <FamilyContext.Provider value={{ family, families, select }}>{children}</FamilyContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useFamily(): FamilyState {
  const state = useContext(FamilyContext)
  if (!state) throw new Error('useFamily must be used inside <FamilyProvider>')
  return state
}
