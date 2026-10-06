import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router'
import { api, ApiError, type InvitationPreview } from '../api'
import { useAuth } from '../auth/context'
import { LanguageSwitcher } from '../components/LanguageSwitcher'
import { Logo } from '../components/Logo'
import { LoginPage } from './LoginPage'

/** `/invite/:token`: sign in first if needed, then show the family and accept. */
export function InvitePage() {
  const { token = '' } = useParams()
  const { t } = useTranslation()
  const { me } = useAuth()
  if (!me) return <p className="muted page">{t('common.loading')}</p>
  if (!me.authenticated) return <LoginPage next={`/invite/${token}`} invited />
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
  if (error) body = <p className="notice bad">{t(`invite.error.${error}`)}</p>
  else if (!invitation) body = <p className="muted">{t('common.loading')}</p>
  else if (invitation.state !== 'pending')
    body = <p className="notice bad">{t(`invite.state.${invitation.state}`)}</p>
  else
    body = (
      <>
        <p>{t('invite.body', { family: invitation.family_name })}</p>
        <div className="auth-actions">
          <button className="button primary" onClick={accept} disabled={busy}>
            {t('invite.accept')}
          </button>
        </div>
      </>
    )

  return (
    <div className="auth-screen">
      <div className="auth-topbar">
        <LanguageSwitcher />
      </div>
      <main className="auth-card">
        <Logo />
        <h1>{t('invite.title')}</h1>
        {body}
      </main>
    </div>
  )
}
