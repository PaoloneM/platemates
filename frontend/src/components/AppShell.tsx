import GroupsIcon from '@mui/icons-material/GroupsOutlined'
import LogoutIcon from '@mui/icons-material/Logout'
import SettingsIcon from '@mui/icons-material/SettingsOutlined'
import {
  AppBar,
  Avatar,
  Badge,
  Box,
  Container,
  Divider,
  IconButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Select,
  Toolbar,
  Typography,
} from '@mui/material'
import { useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink } from 'react-router'
import { csrfToken } from '../api'
import { useAuth } from '../auth/context'
import { saveLanguage } from '../auth/language'
import { useTeam } from '../team'
import { supportedLanguages } from '../i18n'
import { Flag } from './Flag'
import { ThemeModeSwitch } from './ThemeMode'
import { Logo } from './Logo'
import { BOTTOM_BAR_HEIGHT, BottomBar, NavigationRail } from './Navigation'
import yoda from '../assets/yoda.png'

function UserMenu() {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const logoutForm = useRef<HTMLFormElement>(null)
  if (!me?.authenticated) return null
  const { first_name, last_name, email } = me.user
  const name = [first_name, last_name].filter(Boolean).join(' ') || email

  return (
    <>
      <IconButton onClick={(e) => setAnchor(e.currentTarget)}
        aria-label={me.user.is_admin ? `${t('shell.account')} (${t('shell.admin')})` : t('shell.account')}>
        {/* Administrators (Keycloak's admin role) carry a badge, so it is clear whose powers are on. */}
        <Badge invisible={!me.user.is_admin} overlap="circular" anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
          badgeContent={<Box component="img" src={yoda} alt="" sx={{ width: 28, height: 'auto', display: 'block' }} />}
          sx={{ '& .MuiBadge-badge': { p: 0, minWidth: 0, height: 'auto', bgcolor: 'transparent', transform: 'translate(45%, 35%)' } }}>
          <Avatar sx={{ width: 34, height: 34, bgcolor: 'primary.main', fontSize: 16 }}>
            {name[0]?.toUpperCase()}
          </Avatar>
        </Badge>
      </IconButton>
      <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
        <Box sx={{ px: 2, py: 1 }}>
          <Typography sx={{ fontWeight: 600 }}>{name}</Typography>
          <Typography variant="body2" color="text.secondary">
            {email}
          </Typography>
        </Box>
        <Divider />
        {Object.entries(supportedLanguages).map(([code, label]) => (
          <MenuItem
            key={code}
            selected={i18n.resolvedLanguage === code}
            onClick={() => {
              void i18n.changeLanguage(code)
              void saveLanguage(code)
              setAnchor(null)
            }}
          >
            <ListItemIcon>
              <Flag language={code} />
            </ListItemIcon>
            <ListItemText>{label}</ListItemText>
          </MenuItem>
        ))}
        <ThemeModeSwitch />
        <Divider />
        <MenuItem component={RouterLink} to="/team" onClick={() => setAnchor(null)}>
          <ListItemIcon>
            <GroupsIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{t('team.menu')}</ListItemText>
        </MenuItem>
        {(me.user.is_staff || me.user.is_admin) && (
          <MenuItem component={RouterLink} to="/manage" onClick={() => setAnchor(null)}>
            <ListItemIcon>
              <SettingsIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>{t('manage.title')}</ListItemText>
          </MenuItem>
        )}
        {(me.user.is_staff || me.user.is_admin) && <Divider />}
        <MenuItem onClick={() => logoutForm.current?.submit()}>
          <ListItemIcon>
            <LogoutIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{t('auth.logout')}</ListItemText>
        </MenuItem>
      </Menu>
      {/* Logout must be a CSRF-protected POST; Django then ends the Keycloak session too. */}
      <form ref={logoutForm} method="post" action="/oidc/logout/" hidden>
        <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken()} />
      </form>
    </>
  )
}

function TeamSwitcher() {
  const { team, teams, select } = useTeam()
  if (teams.length < 2) {
    return (
      <Typography variant="h3" component={RouterLink} to="/team" noWrap
        sx={{ color: 'inherit', textDecoration: 'none', '&:hover': { textDecoration: 'underline' } }}>
        {team.name}
      </Typography>
    )
  }
  return (
    <Select
      size="small"
      variant="standard"
      disableUnderline
      value={team.id}
      onChange={(e) => select(Number(e.target.value))}
      sx={{ fontWeight: 600, fontSize: '1.1rem' }}
    >
      {teams.map((f) => (
        <MenuItem key={f.id} value={f.id}>
          {f.name}
        </MenuItem>
      ))}
    </Select>
  )
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <>
      <AppBar position="sticky" color="inherit" elevation={0} sx={{ borderBottom: 1, borderColor: 'divider' }}>
        <Toolbar sx={{ gap: 1.5 }}>
          <Box component={RouterLink} to="/" sx={{ display: 'flex' }} aria-label="home">
            <Logo size={32} />
          </Box>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <TeamSwitcher />
          </Box>
          <UserMenu />
        </Toolbar>
      </AppBar>
      <Box sx={{ display: 'flex' }}>
        <NavigationRail />
        <Container maxWidth="lg" sx={{
          py: { xs: 2, sm: 3 }, minWidth: 0,
          pb: { xs: `calc(${BOTTOM_BAR_HEIGHT}px + 96px + env(safe-area-inset-bottom))`, sm: 12 },
        }}>
          {children}
        </Container>
      </Box>
      <BottomBar />
    </>
  )
}
