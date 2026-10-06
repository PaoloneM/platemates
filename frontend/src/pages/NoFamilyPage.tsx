import { Button, Typography } from '@mui/material'
import { useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { csrfToken } from '../api'
import { useAuth } from '../auth/context'
import { AuthLayout } from '../components/AuthLayout'

/** Signed in, but not a member of any family yet: access is invitation-only. */
export function NoFamilyPage() {
  const { t } = useTranslation()
  const { me } = useAuth()
  const form = useRef<HTMLFormElement>(null)
  const email = me?.authenticated ? me.user.email : ''
  return (
    <AuthLayout>
      <Typography variant="h1">{t('noFamily.title')}</Typography>
      <Typography>{t('noFamily.body', { email })}</Typography>
      <Typography color="text.secondary">{t('noFamily.hint')}</Typography>
      <form ref={form} method="post" action="/oidc/logout/">
        <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken()} />
        <Button variant="outlined" type="submit">
          {t('auth.logout')}
        </Button>
      </form>
    </AuthLayout>
  )
}
