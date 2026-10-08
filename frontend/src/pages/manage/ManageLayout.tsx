import EggIcon from '@mui/icons-material/EggOutlined'
import RuleIcon from '@mui/icons-material/RuleOutlined'
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

/** The entities and settings the management section covers. New ones (kitchen tools, ...) go here. */
const SECTIONS = [
  { key: 'ingredients', path: '/manage/ingredients', icon: <EggIcon /> },
  { key: 'rules', path: '/manage/rules', icon: <RuleIcon /> },
]

/**
 * The management section: shared catalogs, for staff. A menu of entities on the left on
 * desktop, tabs on top on phones.
 */
export function ManageLayout({ children }: { children: ReactNode }) {
  const { t } = useTranslation()
  const { me } = useAuth()
  const location = useLocation()
  const wide = useMediaQuery(useTheme().breakpoints.up('md'))
  if (!me?.authenticated || !me.user.is_staff) return <Navigate to="/" replace />

  const current = SECTIONS.find((s) => location.pathname.startsWith(s.path))?.key ?? false
  return (
    <Stack spacing={2}>
      <Typography variant="h1">{t('manage.title')}</Typography>
      <Stack direction={wide ? 'row' : 'column'} spacing={wide ? 3 : 1} sx={{ alignItems: 'flex-start' }}>
        {wide ? (
          <Paper variant="outlined" sx={{ width: 220, flex: 'none', position: 'sticky', top: 88 }}>
            <List disablePadding>
              {SECTIONS.map((s) => (
                <ListItemButton key={s.key} component={RouterLink} to={s.path} selected={current === s.key}>
                  <ListItemIcon sx={{ minWidth: 36 }}>{s.icon}</ListItemIcon>
                  <ListItemText primary={t(`manage.section.${s.key}`)} />
                </ListItemButton>
              ))}
            </List>
          </Paper>
        ) : (
          <Tabs value={current} variant="scrollable" sx={{ alignSelf: 'stretch' }}>
            {SECTIONS.map((s) => (
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
