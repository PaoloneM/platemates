import CachedIcon from '@mui/icons-material/Cached'
import EggIcon from '@mui/icons-material/EggOutlined'
import RuleIcon from '@mui/icons-material/RuleOutlined'
import TuneIcon from '@mui/icons-material/Tune'
import {
  Box,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Paper,
  Stack,
  Tab,
  Tabs,
  Typography,
  useMediaQuery,
} from '@mui/material'
import { useTheme } from '@mui/material/styles'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, Navigate, useLocation } from 'react-router'
import { useAuth } from '../../auth/context'

/**
 * What the management section covers, and who sees it: shared catalogs and system rules for
 * staff, application settings for administrators (Keycloak's `admin` role). New entities
 * (kitchen tools, ...) go here.
 */
const SECTIONS = [
  { key: 'ingredients', path: '/manage/ingredients', icon: <EggIcon />, who: 'staff' },
  { key: 'rules', path: '/manage/rules', icon: <RuleIcon />, who: 'staff' },
  { key: 'settings', path: '/manage/settings', icon: <TuneIcon />, who: 'admin' },
  { key: 'cache', path: '/manage/cache', icon: <CachedIcon />, who: 'admin' },
] as const

function useSections() {
  const { me } = useAuth()
  if (!me?.authenticated) return []
  return SECTIONS.filter((s) => (s.who === 'admin' ? me.user.is_admin : me.user.is_staff))
}

/** `/manage`: the first section the user may see. */
export function ManageIndex() {
  const sections = useSections()
  return <Navigate to={sections[0]?.path ?? '/'} replace />
}

/** The management section: a menu of sections on the left on desktop, tabs on top on phones. */
export function ManageLayout({ children }: { children: ReactNode }) {
  const { t } = useTranslation()
  const sections = useSections()
  const location = useLocation()
  const wide = useMediaQuery(useTheme().breakpoints.up('md'))
  const current = sections.find((s) => location.pathname.startsWith(s.path))?.key
  if (!current) return <Navigate to="/" replace />
  return (
    <Stack spacing={2}>
      <Typography variant="h1">{t('manage.title')}</Typography>
      <Stack direction={wide ? 'row' : 'column'} spacing={wide ? 3 : 1} sx={{ alignItems: 'flex-start' }}>
        {wide ? (
          <Paper variant="outlined" sx={{ width: 220, flex: 'none', position: 'sticky', top: 88 }}>
            <List disablePadding>
              {sections.map((s) => (
                <ListItemButton key={s.key} component={RouterLink} to={s.path} selected={current === s.key}>
                  <ListItemIcon sx={{ minWidth: 36 }}>{s.icon}</ListItemIcon>
                  <ListItemText primary={t(`manage.section.${s.key}`)} />
                </ListItemButton>
              ))}
            </List>
          </Paper>
        ) : (
          <Tabs value={current} variant="scrollable" sx={{ alignSelf: 'stretch' }}>
            {sections.map((s) => (
              <Tab key={s.key} value={s.key} label={t(`manage.section.${s.key}`)} component={RouterLink}
                to={s.path} icon={s.icon} iconPosition="start" />
            ))}
          </Tabs>
        )}
        <Box sx={{ flex: 1, minWidth: 0, alignSelf: 'stretch' }}>{children}</Box>
      </Stack>
    </Stack>
  )
}
