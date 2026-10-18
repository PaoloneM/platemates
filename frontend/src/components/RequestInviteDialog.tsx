import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError } from '../api'

/** Asking the administrators for an invitation: an address to answer, and a few words. From
 * the sign-in page, and from the page of someone signed in without a team (their address
 * filled in). */
export function RequestInviteDialog({ onClose, initialEmail = '' }: { onClose: () => void; initialEmail?: string }) {
  const { t } = useTranslation()
  const [email, setEmail] = useState(initialEmail)
  const [name, setName] = useState('')
  const [message, setMessage] = useState('')
  // Hidden from people; bots fill it in, and their request is dropped.
  const [website, setWebsite] = useState('')
  const [state, setState] = useState<'idle' | 'busy' | 'sent' | 'invalid' | 'tooMany' | 'error'>('idle')

  async function send() {
    setState('busy')
    try {
      await api('/request-invite/', { method: 'POST', body: JSON.stringify({ email, name, message, website }) })
      setState('sent')
    } catch (e) {
      setState(e instanceof ApiError && e.status === 429 ? 'tooMany' : e instanceof ApiError && e.status === 400 ? 'invalid' : 'error')
    }
  }

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{t('requestInvite.title')}</DialogTitle>
      <DialogContent>
        {state === 'sent' ? (
          <Alert severity="success" sx={{ mt: 1 }}>{t('requestInvite.sent')}</Alert>
        ) : (
          <Stack spacing={2} component="form" sx={{ pt: 1 }} onSubmit={(e) => { e.preventDefault(); void send() }}>
            <Typography variant="body2" color="text.secondary">{t('requestInvite.hint')}</Typography>
            {state === 'invalid' && <Alert severity="error">{t('requestInvite.invalid')}</Alert>}
            {state === 'tooMany' && <Alert severity="warning">{t('requestInvite.tooMany')}</Alert>}
            {state === 'error' && <Alert severity="error">{t('common.error')}</Alert>}
            <TextField label={t('requestInvite.email')} type="email" required autoFocus value={email}
              onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
            <TextField label={t('requestInvite.name')} value={name} onChange={(e) => setName(e.target.value)}
              autoComplete="name" />
            <TextField label={t('requestInvite.message')} value={message} multiline minRows={2}
              onChange={(e) => setMessage(e.target.value)} slotProps={{ htmlInput: { maxLength: 500 } }} />
            <Box aria-hidden sx={{ position: 'absolute', left: -10000, width: 1, height: 1, overflow: 'hidden' }}>
              <input tabIndex={-1} autoComplete="off" name="website" value={website} onChange={(e) => setWebsite(e.target.value)} />
            </Box>
            <button type="submit" hidden />
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{state === 'sent' ? t('common.close') : t('common.cancel')}</Button>
        {state !== 'sent' && (
          <Button variant="contained" disabled={state === 'busy' || !email.trim()} onClick={() => void send()}>
            {t('requestInvite.send')}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  )
}
