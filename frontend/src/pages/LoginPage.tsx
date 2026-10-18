import BookIcon from '@mui/icons-material/MenuBookOutlined'
import MenuIcon from '@mui/icons-material/RestaurantMenuOutlined'
import CartIcon from '@mui/icons-material/ShoppingCartOutlined'
import MailIcon from '@mui/icons-material/MailOutlined'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Grid,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router'
import { api, ApiError, type IdentityProvider, type InvitationPreview, type LoginOptions, loginUrl } from '../api'
import { LanguageSwitcher } from '../components/LanguageSwitcher'
import { Logo } from '../components/Logo'
import { ProviderIcon } from '../components/ProviderIcon'

const PROVIDER_NAMES: Record<IdentityProvider, string> = {
  google: 'Google',
  microsoft: 'Microsoft',
  apple: 'Apple',
}

/**
 * The landing and sign-in screen: what the app does, the ways to sign in (every button a
 * full-page redirect through Django to Keycloak), and a way to ask for an invitation. Opened
 * from an invitation link (`invitation`: its token), it says who invited the user and to which
 * team instead.
 */
export function LoginPage({ next = '/', invitation }: { next?: string; invitation?: string }) {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const [providers, setProviders] = useState<IdentityProvider[]>([])
  const [invite, setInvite] = useState<InvitationPreview | null>(null)
  const [asking, setAsking] = useState(false)

  useEffect(() => {
    api<LoginOptions>('/login-options/')
      .then((options) => setProviders(options.identity_providers))
      .catch(() => setProviders([]))
  }, [])
  useEffect(() => {
    if (!invitation) return
    api<InvitationPreview>(`/invitations/by-token/${encodeURIComponent(invitation)}/`)
      .then(setInvite)
      .catch(() => setInvite(null))
  }, [invitation])

  return (
    <Stack sx={{ alignItems: 'center', minHeight: '100vh', p: 2 }}>
      <Box sx={{ alignSelf: 'stretch', display: 'flex', justifyContent: 'flex-end' }}>
        <LanguageSwitcher />
      </Box>
      <Stack spacing={4} sx={{ width: '100%', maxWidth: 960, my: 'auto', alignItems: 'center', py: 2 }}>
        <Stack spacing={1.5} sx={{ alignItems: 'center', textAlign: 'center' }}>
          <Logo size={64} />
          <Typography variant="h1" sx={{ color: 'primary.main' }}>{t('app.title')}</Typography>
          <Typography color="text.secondary" sx={{ maxWidth: 560 }}>{t('auth.tagline')}</Typography>
        </Stack>

        {invitation ? <InvitationNotice invite={invite} /> : <Features />}

        <Card sx={{ width: '100%', maxWidth: 420, borderRadius: 4 }}>
          <CardContent sx={{ p: { xs: 3, sm: 4 } }}>
            <Stack spacing={1.25}>
              {params.get('login') === 'failed' && <Alert severity="error">{t('auth.failed')}</Alert>}
              {providers.map((idp) => (
                <Button
                  key={idp}
                  variant="outlined"
                  color="inherit"
                  size="large"
                  href={loginUrl({ next, idp })}
                  startIcon={<ProviderIcon provider={idp} />}
                  sx={{ borderColor: 'divider', '& svg': { width: 20, height: 20 } }}
                >
                  {t('auth.continueWith', { provider: PROVIDER_NAMES[idp] })}
                </Button>
              ))}
              {providers.length > 0 && (
                <Divider sx={{ color: 'text.secondary', fontSize: 14 }}>{t('auth.or')}</Divider>
              )}
              <Button variant="contained" size="large" href={loginUrl({ next })}>
                {t('auth.signInWithEmail')}
              </Button>
              <Button href={loginUrl({ next, signup: true })}>{t('auth.createAccount')}</Button>
            </Stack>
          </CardContent>
        </Card>

        {!invitation && (
          <Stack spacing={1} sx={{ alignItems: 'center', textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 420 }}>
              {t('auth.invitationOnly')}
            </Typography>
            <Button variant="outlined" startIcon={<MailIcon />} onClick={() => setAsking(true)}>
              {t('requestInvite.action')}
            </Button>
          </Stack>
        )}
      </Stack>
      {asking && <RequestInviteDialog onClose={() => setAsking(false)} />}
    </Stack>
  )
}

/** The three things the app does, each with its own icon, as in the navigation. */
function Features() {
  const { t } = useTranslation()
  const features: { key: string; icon: ReactNode }[] = [
    { key: 'recipes', icon: <BookIcon fontSize="large" /> },
    { key: 'menu', icon: <MenuIcon fontSize="large" /> },
    { key: 'shopping', icon: <CartIcon fontSize="large" /> },
  ]
  return (
    <Grid container spacing={2} sx={{ width: '100%' }}>
      {features.map((f) => (
        <Grid key={f.key} size={{ xs: 12, sm: 4 }}>
          <Stack spacing={1.25} sx={{ alignItems: 'center', textAlign: 'center', px: 2 }}>
            <Box sx={(theme) => ({
              width: 72, height: 72, borderRadius: '50%', display: 'grid', placeItems: 'center',
              color: 'primary.main',
              bgcolor: theme.alpha((theme.vars ?? theme).palette.primary.main, 0.1),
            })}>
              {f.icon}
            </Box>
            <Typography variant="h3">{t(`landing.${f.key}.claim`)}</Typography>
            <Typography variant="body2" color="text.secondary">{t(`landing.${f.key}.text`)}</Typography>
          </Stack>
        </Grid>
      ))}
    </Grid>
  )
}

/** Who invited the user, to which team; or why the link no longer works. */
function InvitationNotice({ invite }: { invite: InvitationPreview | null }) {
  const { t } = useTranslation()
  if (!invite) return <Alert severity="info" sx={{ maxWidth: 420, width: '100%' }}>{t('auth.invitedSignIn')}</Alert>
  if (invite.state !== 'pending') {
    return <Alert severity="warning" sx={{ maxWidth: 420, width: '100%' }}>{t(`invite.state.${invite.state}`)}</Alert>
  }
  return (
    <Card variant="outlined" sx={{ maxWidth: 420, width: '100%', borderRadius: 4, borderColor: 'primary.main' }}>
      <CardContent sx={{ textAlign: 'center' }}>
        <Typography variant="h3" sx={{ mb: 1 }}>
          {invite.invited_by_name
            ? t('auth.invitedBy', { name: invite.invited_by_name, team: invite.team_name })
            : t('auth.invitedTo', { team: invite.team_name })}
        </Typography>
        <Typography variant="body2" color="text.secondary">{t('auth.invitedHint')}</Typography>
      </CardContent>
    </Card>
  )
}

/** Asking the administrators for an invitation: an address to answer, and a few words. */
function RequestInviteDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const [email, setEmail] = useState('')
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
