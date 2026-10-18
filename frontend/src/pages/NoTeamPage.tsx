import MailIcon from '@mui/icons-material/MailOutlined'
import { Button, Stack, Typography } from '@mui/material'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { csrfToken } from '../api'
import { useAuth } from '../auth/context'
import { AuthLayout } from '../components/AuthLayout'
import { RequestInviteDialog } from '../components/RequestInviteDialog'

/** Signed in, but not a member of any team yet: access is invitation-only. */
export function NoTeamPage() {
  const { t } = useTranslation()
  const { me } = useAuth()
  const form = useRef<HTMLFormElement>(null)
  const [asking, setAsking] = useState(false)
  const email = me?.authenticated ? me.user.email : ''
  return (
    <AuthLayout>
      <Typography variant="h1">{t('noTeam.title')}</Typography>
      <Typography>{t('noTeam.body', { email })}</Typography>
      <Typography color="text.secondary">{t('noTeam.hint')}</Typography>
      {/* No one to ask: the administrators can invite them. */}
      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', justifyContent: 'center', rowGap: 1 }}>
        <Button variant="contained" startIcon={<MailIcon />} onClick={() => setAsking(true)}>
          {t('requestInvite.action')}
        </Button>
        <form ref={form} method="post" action="/oidc/logout/">
          <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken()} />
          <Button variant="outlined" type="submit">
            {t('auth.logout')}
          </Button>
        </form>
      </Stack>
      {asking && <RequestInviteDialog initialEmail={email} onClose={() => setAsking(false)} />}
    </AuthLayout>
  )
}
