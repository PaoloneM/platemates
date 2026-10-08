import AddIcon from '@mui/icons-material/Add'
import ChatIcon from '@mui/icons-material/ChatOutlined'
import EditIcon from '@mui/icons-material/EditOutlined'
import LinkIcon from '@mui/icons-material/Link'
import PhotoIcon from '@mui/icons-material/PhotoCameraOutlined'
import SearchIcon from '@mui/icons-material/Search'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { api, type AssistantMode, type AssistantSession } from '../api'
import { useTeam } from '../team'
import { ActionFab, type FabItem } from './ActionFab'

/** The "+" button of the recipe book. "Tell me the recipe" is the first, highlighted entry. */
export function AddRecipeFab() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { team } = useTeam()
  const [busy, setBusy] = useState(false)

  async function startAssistant(mode: AssistantMode) {
    setBusy(true)
    try {
      const session = await api<AssistantSession>('/assistant/sessions/', {
        method: 'POST',
        body: JSON.stringify({ team: team.id, mode }),
      })
      navigate(`/assistant/${session.id}`)
    } finally {
      setBusy(false)
    }
  }

  const items: FabItem[] = [
    { key: 'tell', icon: <ChatIcon />, label: t('assistant.mode.tell'), primary: true,
      run: () => void startAssistant('tell') },
    { key: 'search', icon: <SearchIcon />, label: t('assistant.mode.search'),
      run: () => void startAssistant('search') },
    { key: 'link', icon: <LinkIcon />, label: t('assistant.mode.link'),
      run: () => void startAssistant('link') },
    { key: 'photo', icon: <PhotoIcon />, label: t('assistant.mode.photo'),
      run: () => void startAssistant('photo') },
    { key: 'manual', icon: <EditIcon />, label: t('assistant.mode.manual'),
      run: () => navigate('/recipes/new') },
  ]

  return <ActionFab label={t('book.add')} icon={<AddIcon />} items={items} busy={busy} />
}
