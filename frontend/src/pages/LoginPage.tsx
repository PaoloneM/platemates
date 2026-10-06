import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router'
import { api, type IdentityProvider, type LoginOptions, loginUrl } from '../api'
import { LanguageSwitcher } from '../components/LanguageSwitcher'
import { Logo } from '../components/Logo'
import { ProviderIcon } from '../components/ProviderIcon'

const PROVIDER_NAMES: Record<IdentityProvider, string> = {
  google: 'Google',
  microsoft: 'Microsoft',
  apple: 'Apple',
}

/**
 * The app's own sign-in screen. Every button is a full-page redirect through Django to Keycloak:
 * social buttons jump straight to the provider (`idp`), the email button opens Keycloak's
 * themed login form, and "create account" opens its registration form.
 */
export function LoginPage({ next = '/', invited = false }: { next?: string; invited?: boolean }) {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const [providers, setProviders] = useState<IdentityProvider[]>([])

  useEffect(() => {
    api<LoginOptions>('/login-options/')
      .then((options) => setProviders(options.identity_providers))
      .catch(() => setProviders([]))
  }, [])

  return (
    <div className="auth-screen">
      <div className="auth-topbar">
        <LanguageSwitcher />
      </div>
      <main className="auth-card">
        <Logo />
        <h1>{t('app.title')}</h1>
        <p className="muted">{t('auth.tagline')}</p>

        {invited && <p className="notice">{t('auth.invitedSignIn')}</p>}
        {params.get('login') === 'failed' && <p className="notice bad">{t('auth.failed')}</p>}

        <div className="auth-actions">
          {providers.map((idp) => (
            <a key={idp} className="button provider" href={loginUrl({ next, idp })}>
              <ProviderIcon provider={idp} />
              {t('auth.continueWith', { provider: PROVIDER_NAMES[idp] })}
            </a>
          ))}
          {providers.length > 0 && <div className="divider">{t('auth.or')}</div>}
          <a className="button primary" href={loginUrl({ next })}>
            {t('auth.signInWithEmail')}
          </a>
          <a className="button link" href={loginUrl({ next, signup: true })}>
            {t('auth.createAccount')}
          </a>
        </div>

        <p className="fine-print">{t('auth.invitationOnly')}</p>
      </main>
    </div>
  )
}
