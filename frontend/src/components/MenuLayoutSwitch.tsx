import TeamIcon from '@mui/icons-material/GroupsOutlined'
import HorizontalIcon from '@mui/icons-material/ViewWeekOutlined'
import VerticalIcon from '@mui/icons-material/ViewAgendaOutlined'
import LayoutIcon from '@mui/icons-material/DashboardOutlined'
import { ListItemIcon, Stack, ToggleButton, ToggleButtonGroup, Tooltip } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { MenuLayout } from '../api'
import { useMenuLayout } from '../menuLayout'

/** The menu layout switch of the user menu: the team's, or the user's own choice. */
export function MenuLayoutSwitch() {
  const { t } = useTranslation()
  const { own, choose } = useMenuLayout()
  const options: { value: MenuLayout | 'team'; label: string; icon: React.JSX.Element }[] = [
    { value: 'team', label: t('calendar.layout.team'), icon: <TeamIcon fontSize="small" /> },
    { value: 'vertical', label: t('calendar.layout.vertical'), icon: <VerticalIcon fontSize="small" /> },
    { value: 'horizontal', label: t('calendar.layout.horizontal'), icon: <HorizontalIcon fontSize="small" /> },
  ]
  return (
    // Laid out as a menu item, like the theme switch above it.
    <Stack direction="row" sx={{ px: 2, py: 0.75, alignItems: 'center' }}>
      <ListItemIcon>
        <Tooltip title={t('calendar.layout.label')}>
          <LayoutIcon fontSize="small" />
        </Tooltip>
      </ListItemIcon>
      <ToggleButtonGroup size="small" exclusive value={own ?? 'team'} aria-label={t('calendar.layout.label')}
        onChange={(_, value: MenuLayout | 'team' | null) => value && void choose(value === 'team' ? null : value)}>
        {options.map((o) => (
          <Tooltip key={o.value} title={o.label}>
            <ToggleButton value={o.value} aria-label={o.label}>{o.icon}</ToggleButton>
          </Tooltip>
        ))}
      </ToggleButtonGroup>
    </Stack>
  )
}
