import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import ChatIcon from '@mui/icons-material/ChatOutlined'
import TuneIcon from '@mui/icons-material/Tune'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { ActionFab, type FabItem } from './ActionFab'
import { PlanWeekDialog } from './PlanWeekDialog'

/**
 * The menu screen's FAB: generate the shown week with the standing rules, say how to plan it
 * first, or set up the typical week. Generating comes with the menu engine.
 */
export function MenuFab({ weekStart, onSaved }: { weekStart: string; onSaved: () => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [planning, setPlanning] = useState(false)

  const items: FabItem[] = [
    { key: 'generate', icon: <AutoAwesomeIcon />, label: t('menuFab.generateSoon'), primary: true, disabled: true },
    { key: 'plan', icon: <ChatIcon />, label: t('menuFab.plan'), run: () => setPlanning(true) },
    { key: 'week', icon: <TuneIcon />, label: t('menuFab.week'), run: () => navigate('/week') },
  ]

  return (
    <>
      <ActionFab label={t('menuFab.label')} icon={<AutoAwesomeIcon />} items={items} />
      {planning && (
        <PlanWeekDialog weekStart={weekStart} onClose={() => setPlanning(false)}
          onSaved={() => { setPlanning(false); onSaved() }} />
      )}
    </>
  )
}
