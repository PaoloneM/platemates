import { Alert, Button, CircularProgress, Typography } from '@mui/material'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router'
import { api, ApiError, type InvitationPreview } from '../api'
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
  const { refresh } = useAuth()
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
    } catch {
      setError('generic')
      setBusy(false)
    }
  }

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
