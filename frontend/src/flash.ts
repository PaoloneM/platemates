import { keyframes, type SxProps, type Theme } from '@mui/material/styles'
import { useCallback, useEffect, useRef, useState } from 'react'

// Three pulses of the accent colour around an element someone else just changed. Two identical
// animations, used in turn, so a second change restarts the pulses on an element still pulsing.
const pulse = `
  0%, 100% { box-shadow: 0 0 0 0 transparent; }
  50% { box-shadow: 0 0 0 3px var(--flash-colour); background-color: var(--flash-background); }
`
const pulseA = keyframes(pulse)
const pulseB = keyframes(pulse)
const PULSES = 3
const PULSE_MS = 700

/**
 * Highlights elements by key: `flash(keys)` makes every element whose `flashSx(key)` is applied
 * pulse three times. Keys are the page's own ("2026-10-12:dinner", "ingredients").
 */
export function useFlash() {
  const [state, setState] = useState<{ keys: Set<string>; round: number }>({ keys: new Set(), round: 0 })
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const flash = useCallback((keys: string[]) => {
    if (keys.length === 0) return
    setState((s) => ({ keys: new Set(keys), round: s.round + 1 }))
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setState((s) => ({ ...s, keys: new Set() })), PULSES * PULSE_MS + 100)
  }, [])
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])

  const flashSx = useCallback(
    (key: string): SxProps<Theme> =>
      state.keys.has(key)
        ? (theme) => ({
            '--flash-colour': (theme.vars ?? theme).palette.primary.main,
            '--flash-background': theme.alpha((theme.vars ?? theme).palette.primary.main, 0.08),
            animation: `${state.round % 2 ? pulseA : pulseB} ${PULSE_MS}ms ease-in-out ${PULSES}`,
          })
        : {},
    [state],
  )
  return { flash, flashSx }
}

/** An element's own style with a flash on top (MUI accepts a list of styles). */
export function withFlash(base: SxProps<Theme>, flash: SxProps<Theme>): SxProps<Theme> {
  const list = (sx: SxProps<Theme>) => (Array.isArray(sx) ? sx : [sx])
  return [...list(base), ...list(flash)] as SxProps<Theme>
}
