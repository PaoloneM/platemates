import CloseIcon from '@mui/icons-material/Close'
import { Backdrop, SpeedDial, SpeedDialAction, SpeedDialIcon } from '@mui/material'
import { useState, type ReactNode } from 'react'
import { BOTTOM_BAR_HEIGHT } from './Navigation'

export type FabItem = {
  key: string
  icon: ReactNode
  label: string
  // The main entry: larger and in the primary colour, first next to the button.
  primary?: boolean
  // Shown but not usable yet; `label` should say why ("coming soon").
  disabled?: boolean
  run?: () => void
}

/**
 * A screen's FAB with a menu of actions. Tap or click always opens the menu (hover never does),
 * and labels are always visible, so it behaves the same with a mouse and on a phone. Items are
 * listed top-down from the button: the first sits closest to it.
 */
export function ActionFab({ label, icon, items, busy = false }: {
  label: string
  icon: ReactNode
  items: FabItem[]
  busy?: boolean
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Backdrop open={open} onClick={() => setOpen(false)} sx={{ zIndex: (theme) => theme.zIndex.speedDial - 1 }} />
      <SpeedDial
        ariaLabel={label}
        icon={<SpeedDialIcon icon={icon} openIcon={<CloseIcon />} />}
        open={open}
        // Only explicit clicks or taps toggle the menu, never hovering or focus.
        onOpen={(_, reason) => reason === 'toggle' && setOpen(true)}
        onClose={(_, reason) => (reason === 'toggle' || reason === 'escapeKeyDown') && setOpen(false)}
        FabProps={{ disabled: busy }}
        sx={{ position: 'fixed', right: { xs: 16, sm: 32 }, bottom: { xs: `calc(${BOTTOM_BAR_HEIGHT + 16}px + env(safe-area-inset-bottom))`, sm: 32 } }}
      >
        {items.map((item) => (
          <SpeedDialAction
            key={item.key}
            icon={item.icon}
            slotProps={{
              tooltip: { open: true, title: item.label },
              fab: {
                disabled: item.disabled,
                // The action Fab ignores `color`: highlight the main entry through sx.
                sx: item.primary
                  ? {
                      width: 48,
                      height: 48,
                      ...(!item.disabled && {
                        bgcolor: 'primary.main',
                        color: 'primary.contrastText',
                        '&:hover': { bgcolor: 'primary.dark' },
                      }),
                    }
                  : undefined,
              },
              staticTooltipLabel: {
                sx: {
                  whiteSpace: 'nowrap',
                  fontWeight: item.primary ? 600 : 400,
                  color: item.disabled ? 'text.disabled' : 'text.primary',
                },
              },
            }}
            onClick={() => {
              if (item.disabled || !item.run) return
              setOpen(false)
              item.run()
            }}
          />
        ))}
      </SpeedDial>
    </>
  )
}
