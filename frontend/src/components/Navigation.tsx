import MenuIcon from '@mui/icons-material/RestaurantMenuOutlined'
import MenuActiveIcon from '@mui/icons-material/RestaurantMenu'
import BookIcon from '@mui/icons-material/MenuBookOutlined'
import BookActiveIcon from '@mui/icons-material/MenuBook'
import { BottomNavigation, BottomNavigationAction, Box, ButtonBase, Paper, Typography } from '@mui/material'
import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, useLocation } from 'react-router'

// Material 3 adaptive navigation: a rail on tablets and desktops, a bottom bar on phones.
export const RAIL_WIDTH = 88
export const BOTTOM_BAR_HEIGHT = 64

type Destination = {
  to: string
  label: string
  icon: ReactElement
  activeIcon: ReactElement
  // Paths that belong to this destination besides `to` itself.
  owns: (path: string) => boolean
}

function useDestinations(): Destination[] {
  const { t } = useTranslation()
  return [
    {
      to: '/',
      label: t('nav.calendar'),
      icon: <MenuIcon />,
      activeIcon: <MenuActiveIcon />,
      owns: (path) => path === '/' || path.startsWith('/calendar'),
    },
    {
      to: '/recipes',
      label: t('nav.recipes'),
      icon: <BookIcon />,
      activeIcon: <BookActiveIcon />,
      owns: (path) => path.startsWith('/recipes') || path.startsWith('/assistant'),
    },
  ]
}

function useCurrent(destinations: Destination[]): number {
  const { pathname } = useLocation()
  return destinations.findIndex((d) => d.owns(pathname))
}

export function NavigationRail() {
  const destinations = useDestinations()
  const current = useCurrent(destinations)
  return (
    <Box component="nav" sx={{
      display: { xs: 'none', sm: 'flex' }, flexDirection: 'column', alignItems: 'center', gap: 1.5,
      width: RAIL_WIDTH, flexShrink: 0, pt: 2, position: 'sticky', top: 64, alignSelf: 'flex-start',
    }}>
      {destinations.map((d, index) => {
        const active = index === current
        return (
          <ButtonBase key={d.to} component={RouterLink} to={d.to} aria-current={active ? 'page' : undefined}
            sx={{ flexDirection: 'column', gap: 0.5, width: '100%', py: 0.5, borderRadius: 2 }}>
            <Box sx={{
              display: 'flex', justifyContent: 'center', width: 56, py: 0.5, borderRadius: 4,
              bgcolor: (theme) =>
                active ? theme.alpha((theme.vars ?? theme).palette.primary.main, 0.16) : 'transparent',
              color: active ? 'primary.main' : 'text.secondary',
              transition: 'background-color 150ms',
            }}>
              {active ? d.activeIcon : d.icon}
            </Box>
            <Typography variant="caption" sx={{ fontWeight: active ? 700 : 500, color: active ? 'text.primary' : 'text.secondary' }}>
              {d.label}
            </Typography>
          </ButtonBase>
        )
      })}
    </Box>
  )
}

export function BottomBar() {
  const destinations = useDestinations()
  const current = useCurrent(destinations)
  return (
    <Paper component="nav" elevation={3} sx={{
      display: { xs: 'block', sm: 'none' }, position: 'fixed', left: 0, right: 0, bottom: 0,
      zIndex: 'appBar', pb: 'env(safe-area-inset-bottom)',
    }}>
      <BottomNavigation showLabels value={current} sx={{ height: BOTTOM_BAR_HEIGHT }}>
        {destinations.map((d, index) => (
          <BottomNavigationAction key={d.to} component={RouterLink} to={d.to} label={d.label}
            icon={index === current ? d.activeIcon : d.icon} />
        ))}
      </BottomNavigation>
    </Paper>
  )
}
