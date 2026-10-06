import AddIcon from '@mui/icons-material/Add'
import ChatIcon from '@mui/icons-material/ChatOutlined'
import CloseIcon from '@mui/icons-material/Close'
import EditIcon from '@mui/icons-material/EditOutlined'
import LinkIcon from '@mui/icons-material/Link'
import PhotoIcon from '@mui/icons-material/PhotoCameraOutlined'
import SearchIcon from '@mui/icons-material/Search'
import { Backdrop, SpeedDial, SpeedDialAction, SpeedDialIcon } from '@mui/material'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { api, type AssistantMode, type AssistantSession } from '../api'
import { useFamily } from '../family'

type Item = { key: string; icon: ReactNode; label: string; primary?: boolean; disabled?: boolean; run?: () => void }

/**
 * The "+" button of the recipe book. Tap or click always opens the menu (hover never does), and
 * labels are always visible, so it behaves the same with a mouse and on a phone. "Tell me the
 * recipe" is the first, highlighted entry; modes whose backend is not built yet are shown
 * disabled with "coming soon".
 */
export function AddRecipeFab() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { family } = useFamily()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  async function startAssistant(mode: AssistantMode) {
    setBusy(true)
    try {
      const session = await api<AssistantSession>('/assistant/sessions/', {
        method: 'POST',
        body: JSON.stringify({ family: family.id, mode }),
      })
      navigate(`/assistant/${session.id}`)
    } finally {
      setBusy(false)
    }
  }

  const soon = (label: string) => `${label} · ${t('assistant.soon')}`
  // Listed top-down from the button: the first item sits closest to it.
  const items: Item[] = [
    { key: 'tell', icon: <ChatIcon />, label: t('assistant.mode.tell'), primary: true,
      run: () => void startAssistant('tell') },
    { key: 'search', icon: <SearchIcon />, label: soon(t('assistant.mode.search')), disabled: true },
    { key: 'link', icon: <LinkIcon />, label: t('assistant.mode.link'),
      run: () => void startAssistant('link') },
    { key: 'photo', icon: <PhotoIcon />, label: t('assistant.mode.photo'),
      run: () => void startAssistant('photo') },
    { key: 'manual', icon: <EditIcon />, label: t('assistant.mode.manual'),
      run: () => navigate('/recipes/new') },
  ]

  return (
    <>
      <Backdrop open={open} onClick={() => setOpen(false)} sx={{ zIndex: (theme) => theme.zIndex.speedDial - 1 }} />
      <SpeedDial
        ariaLabel={t('book.add')}
        icon={<SpeedDialIcon icon={<AddIcon />} openIcon={<CloseIcon />} />}
        open={open}
        // Only explicit clicks or taps toggle the menu, never hovering or focus.
        onOpen={(_, reason) => reason === 'toggle' && setOpen(true)}
        onClose={(_, reason) => (reason === 'toggle' || reason === 'escapeKeyDown') && setOpen(false)}
        FabProps={{ disabled: busy }}
        sx={{ position: 'fixed', right: { xs: 16, sm: 32 }, bottom: { xs: 16, sm: 32 } }}
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
                      bgcolor: 'primary.main',
                      color: 'primary.contrastText',
                      '&:hover': { bgcolor: 'primary.dark' },
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
