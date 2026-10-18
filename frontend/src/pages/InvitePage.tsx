import { Alert, Button, CircularProgress, Typography } from '@mui/material'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router'
import { api, ApiError, csrfToken, type InvitationPreview } from '../api'
import { useAuth } from '../auth/context'
import { AuthLayout } from '../components/AuthLayout'
import { LoginPage } from './LoginPage'

/** `/invite/:token`: sign in first if needed, then show the team and accept. */
export function InvitePage() {
  const { token = '' } = useParams()
  const { me } = useAuth()
  if (!me) return <CircularProgress sx={{ display: 'block', mx: 'auto', mt: 8 }} />
  if (!me.authenticated) return <LoginPage next={`/invite/${token}`} invitation={token} />
  return <AcceptInvitation token={token} />
}

function AcceptInvitation({ token }: { token: string }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { me, refresh } = useAuth()
  const [invitation, setInvitation] = useState<InvitationPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api<InvitationPreview>(`/invitations/by-token/${encodeURIComponent(token)}/`)
      .then(setInvitation)
      .catch((e) => setError(e instanceof ApiError && e.status === 404 ? 'notFound' : 'generic'))
  }, [token])

  async function accept() {
    setBusy(true)
    try {
      await api(`/invitations/by-token/${encodeURIComponent(token)}/`, { method: 'POST' })
      await refresh()
      navigate('/', { replace: true })
    } catch (e) {
      const body = e instanceof ApiError ? (e.body as { code?: string } | null) : null
      setError(body?.code === 'wrong_account' ? 'wrongAccount' : 'generic')
      setBusy(false)
    }
  }

  // Sent by email to another address: this account cannot take it; signing out lets the
  // user come back with the right one.
  const email = me?.authenticated ? me.user.email : ''
  if (error === 'wrongAccount')
    return (
      <AuthLayout>
        <Typography variant="h1">{t('invite.title')}</Typography>
        <Alert severity="warning" sx={{ textAlign: 'left' }}>
          {t('invite.error.wrongAccount', { hint: invitation?.email_hint ?? '', email })}
        </Alert>
        <form method="post" action={`/oidc/logout/`}>
          <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken()} />
          <Button variant="contained" type="submit">{t('invite.switchAccount')}</Button>
        </form>
      </AuthLayout>
    )

  let body
  if (error) body = <Alert severity="error">{t(`invite.error.${error}`)}</Alert>
  else if (!invitation) body = <CircularProgress />
  else if (invitation.state !== 'pending')
    body = <Alert severity="warning">{t(`invite.state.${invitation.state}`)}</Alert>
  else
    body = (
      <>
        <Typography>
          {invitation.invited_by_name
            ? t('auth.invitedBy', { name: invitation.invited_by_name, team: invitation.team_name })
            : t('invite.body', { team: invitation.team_name })}
        </Typography>
        {invitation.email_hint && (
          <Typography variant="body2" color="text.secondary">{t('invite.forAddress', { hint: invitation.email_hint })}</Typography>
        )}
        <Button variant="contained" size="large" fullWidth onClick={accept} disabled={busy}>
          {t('invite.accept')}
        </Button>
      </>
    )

  return (
    <AuthLayout>
      <Typography variant="h1">{t('invite.title')}</Typography>
      {body}
    </AuthLayout>
  )
}
