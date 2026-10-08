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
 * first (and generate from there), or set up the typical week.
 */
export function MenuFab({ weekStart, generating, onGenerate, onSaved }: {
  weekStart: string
  // A generation of this week is running: another one has to wait.
  generating: boolean
  onGenerate: (useWeekSettings: boolean) => void
  onSaved: () => void
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [planning, setPlanning] = useState(false)

  const items: FabItem[] = [
    { key: 'generate', icon: <AutoAwesomeIcon />, primary: true, disabled: generating,
      label: generating ? t('menuFab.generating') : t('menuFab.generate'), run: () => onGenerate(false) },
    { key: 'plan', icon: <ChatIcon />, label: t('menuFab.plan'), run: () => setPlanning(true) },
    { key: 'week', icon: <TuneIcon />, label: t('menuFab.week'), run: () => navigate('/week') },
  ]

  return (
    <>
      <ActionFab label={t('menuFab.label')} icon={<AutoAwesomeIcon />} items={items} />
      {planning && (
        <PlanWeekDialog weekStart={weekStart} generating={generating} onClose={() => setPlanning(false)}
          onSaved={(generate) => {
            setPlanning(false)
            if (generate) onGenerate(true)
            else onSaved()
          }} />
      )}
    </>
  )
}
