import { Alert, Button, Divider, Stack, Typography } from '@mui/material'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router'
import { api, type IdentityProvider, type LoginOptions, loginUrl } from '../api'
import { AuthLayout } from '../components/AuthLayout'
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
    <AuthLayout>
      <Typography variant="h1">{t('app.title')}</Typography>
      <Typography color="text.secondary">{t('auth.tagline')}</Typography>

      {invited && <Alert severity="info">{t('auth.invitedSignIn')}</Alert>}
      {params.get('login') === 'failed' && <Alert severity="error">{t('auth.failed')}</Alert>}

      <Stack spacing={1.25} sx={{ alignSelf: 'stretch', pt: 1 }}>
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

      <Typography variant="body2" color="text.secondary" sx={{ pt: 1 }}>
        {t('auth.invitationOnly')}
      </Typography>
    </AuthLayout>
  )
}
