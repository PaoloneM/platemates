import { useTranslation } from 'react-i18next'
import { useAuth } from '../auth/context'
import { LogoutButton } from '../components/LogoutButton'
import { LanguageSwitcher } from '../components/LanguageSwitcher'
import { Logo } from '../components/Logo'

/** Signed in, but not a member of any family yet: access is invitation-only. */
export function NoFamilyPage() {
  const { t } = useTranslation()
  const { me } = useAuth()
  const email = me?.authenticated ? me.user.email : ''
  return (
    <div className="auth-screen">
      <div className="auth-topbar">
        <LanguageSwitcher />
      </div>
      <main className="auth-card">
        <Logo />
        <h1>{t('noFamily.title')}</h1>
        <p>{t('noFamily.body', { email })}</p>
        <p className="muted">{t('noFamily.hint')}</p>
        <div className="auth-actions">
          <LogoutButton />
        </div>
      </main>
    </div>
  )
}
