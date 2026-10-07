# Authentication

Keycloak is the identity provider; Django is its OIDC client. Users sign in with email and
password, or with Google, Microsoft or Apple, which Keycloak brokers. Access to the application
is **invitation-only**: anyone can authenticate, but a user sees nothing until they accept an
invitation to a team.

## How a login works

```
SPA "Continue with Google"
  └─► /oidc/authenticate/?next=/&lang=it&idp=google           Django (mozilla-django-oidc)
        └─► /auth/realms/mymenu/.../auth?kc_idp_hint=google&ui_locales=it&code_challenge=...
              └─► Google ──► Keycloak (links or creates the Keycloak account)
        ◄── /oidc/callback/?code=...                            Django exchanges the code (PKCE)
  ◄── session cookie, redirect to `next`                        SPA calls /api/me/
```

- **Keycloak lives under `/auth` on the app's own origin** (Traefik forwards it; so does the Vite
  proxy in development) and has no fixed hostname: it builds its URLs from the forwarded
  request. The URLs Django sends the browser to are relative (`/auth/...`), so login works from
  whatever address the app is opened at: `http://localhost:8080` on the Mac,
  `https://<name>.local:8443` or the LAN IP from a phone. One address, one certificate.
- **User data comes from the ID token**, verified with Keycloak's signing keys, not from the
  userinfo endpoint: Keycloak issues tokens for the address the browser used, and its userinfo
  endpoint, called by the backend on the internal address, rejects them (found when first
  logging in from a phone).
- **No token reaches the browser.** Django runs the authorization code flow with PKCE and turns a
  successful login into an ordinary Django session; the SPA is authenticated by that cookie, like
  the admin. Only the ID token is kept, server-side in the session, as `id_token_hint` for logout.
- **Users are matched on the OIDC `sub` claim** (`accounts.OIDCIdentity`), never on email. Keycloak
  is responsible for linking a Google/Microsoft/Apple login to an existing account with the same
  email; profile data (email, names) is refreshed from Keycloak on every login.
- **The login screen is the SPA's own** (`frontend/src/pages/LoginPage.tsx`). Social buttons skip
  Keycloak's page entirely (`kc_idp_hint`). "Sign in with email" shows Keycloak's login form and
  "Create an account" its registration form (`prompt=create`). Both use the custom `mymenu` theme
  (`keycloak/themes/mymenu`), which restyles the stock `keycloak.v2` theme with CSS and messages
  only, so Keycloak upgrades do not break it.
- **Logout** is a POST to `/oidc/logout/`; Django ends its session, then redirects to Keycloak's
  end-session endpoint so the Keycloak session ends too.
- **Language** is a per-user preference (`accounts.UserProfile.language`), so it follows the
  user across browsers and devices. Signed out, the SPA uses the browser's last choice or
  language; once signed in, the saved preference wins, and changing language in the SPA saves
  it (`PATCH /api/me/`). A brand-new user starts with the language they used on Keycloak's
  registration page (its `locale` claim); a user with no preference adopts the SPA's current
  one. The SPA also passes its language to Keycloak (`ui_locales`), so login pages match. The
  realm supports `it` (default) and `en`. Not synced back to Keycloak: Keycloak's own emails
  use the language the user last picked on Keycloak's pages.

## Invitation-only access

| Who | Can |
|---|---|
| Anyone | Create a Keycloak account and sign in |
| Signed in, no team | See the "waiting for an invitation" screen, accept an invitation link |
| Team member | Use the team's data |
| Team owner | Also invite people (`POST /api/invitations/`) and revoke invitations |
| Staff | Also create teams |

An invitation is a single-use link, `/invite/<token>`, valid 14 days. Opened while signed out, it
shows the login screen first and comes back to the invitation afterwards.

**Bootstrap** (the first team has no owner to invite you):

```bash
# 1. Sign in once through the app, so your user exists.
# 2. Create the team with yourself as owner (and staff, for the admin). Idempotent: running it
#    again with the same name and owner changes nothing.
cd backend && uv run python manage.py create_team "Famiglia Rossi" --owner you@example.com --staff
# In Docker:  docker compose exec backend python manage.py create_team ...
```

Until there is a UI for it, invitations are created from the admin (`/admin/accounts/invitation/`)
or the API; the invitation link is `<app URL>/invite/<token>`.

## Configuring Keycloak

Everything is driven by `.env` and applied by `manage.py setup_keycloak`, which is idempotent and
convergent: re-running it changes nothing, and running it after editing `.env` brings Keycloak in
line, including removing a Google/Microsoft/Apple provider whose credentials were removed. The
`keycloak-setup` compose service runs it on every `docker compose up`. Never configure the realm
by hand in the Keycloak console: the next setup run would overwrite it.

- Keycloak admin console: http://localhost:8180/auth/admin/ on the Mac only (user
  `KEYCLOAK_ADMIN`, password `KEYCLOAK_ADMIN_PASSWORD` from `.env`). Traefik refuses `/auth/admin/`,
  so it is not reachable through the app's address from other devices.
- Keycloak keeps its data in its own database (`keycloak`) on the same PostgreSQL server. The
  one-shot `db-init` compose service creates it if missing, on every `up`, so fresh and existing
  volumes behave the same.

### Keycloak admin password

Keycloak creates its admin from `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` **only on its very
first start** (empty `keycloak` database). Changing them in `.env` afterwards has no effect on
Keycloak, and `setup_keycloak` then fails to log in. To realign, create an admin with the
current `.env` values under a **new** username (Keycloak refuses an existing one):

```bash
# 1. In .env, set KEYCLOAK_ADMIN to a new name (e.g. admin2) and the password you want.
# 2. Create that admin directly in Keycloak's database:
docker compose run --rm --no-deps keycloak bootstrap-admin user \
  --username:env KC_BOOTSTRAP_ADMIN_USERNAME --password:env KC_BOOTSTRAP_ADMIN_PASSWORD --optimized
# 3. Re-run the setup:
docker compose up keycloak-setup
```

The old admin can then be deleted from the Keycloak console (master realm → Users).

### Social providers

Each provider is enabled when its variables are set in `.env`; then re-run the setup
(`docker compose up keycloak-setup`, or `uv run python manage.py setup_keycloak` natively) and
recreate the backend (`docker compose up -d backend`; a plain `restart` does not reload `.env`)
so the login screen shows the new button. Every provider needs this
**redirect URI** registered on its side:

```
<app URL>/auth/realms/mymenu/broker/<google|microsoft|apple>/endpoint
e.g. http://localhost:8080/auth/realms/mymenu/broker/google/endpoint
```

**Google**: Google Cloud Console → APIs & Services → Credentials → Create credentials → OAuth
client ID → type "Web application". Add the redirect URI above under "Authorized redirect URIs".
Configure the OAuth consent screen (scopes `openid`, `email`, `profile`). Set
`GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. While the app is in "Testing" mode on the consent
screen, only the test users listed there can sign in.

**Microsoft**: Microsoft Entra admin center → App registrations → New registration. Supported
account types: "Accounts in any organizational directory and personal Microsoft accounts".
Redirect URI: platform "Web", the URI above. Then Certificates & secrets → New client secret.
Set `MICROSOFT_CLIENT_ID` (the Application ID) and `MICROSOFT_CLIENT_SECRET` (the secret's
*value*, not its ID).

**Apple**: needs a paid Apple Developer account, and Apple accepts only **https** redirect URIs
on a real domain, so it cannot work against `localhost`. In the developer portal: create an App
ID with "Sign in with Apple", a Services ID (this is the client ID) configured with your domain
and the redirect URI, and a key with "Sign in with Apple" (download the `.p8`). Put the key in
`secrets/` (gitignored) and set `APPLE_CLIENT_ID` (Services ID), `APPLE_TEAM_ID`, `APPLE_KEY_ID`
and `APPLE_PRIVATE_KEY_FILE=secrets/AuthKey_XXXX.p8`. Apple is not a built-in Keycloak provider:
`keycloak/Dockerfile` installs the community extension
[klausbetz/apple-identity-provider-keycloak](https://github.com/klausbetz/apple-identity-provider-keycloak)
1.17.0, pinned by checksum. It uses internal Keycloak SPIs: check its compatibility table before
upgrading Keycloak.

### Email

With `SMTP_*` set, the realm enables password reset and email verification. Without SMTP both
stay off: email/password accounts work, but a forgotten password can only be reset by an admin
from the Keycloak console.

## HTTP, HTTPS and other devices

Keycloak's session cookies are `Secure`. Browsers accept them over plain HTTP **only on
`localhost`**: from any other device the app must be served over HTTPS with a certificate that
device trusts.

- **Home network** (phones, tablets): `python3 scripts/setup_lan_https.py`, then trust the
  generated certificate authority on each device once. See "Using the app from a phone" in
  `docs/operations.md`.
- **Elsewhere** (a cloud VM, the Raspberry Pi reachable from outside): put the app behind a TLS
  reverse proxy or tunnel with a real certificate, add its URL to `APP_PUBLIC_URLS`,
  `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`, re-run the setup and register the new
  redirect URIs with Google/Microsoft/Apple. Nothing else changes: Keycloak takes its address
  from the forwarded request.

### "Invalid parameter: redirect_uri"

Keycloak shows this when the app was opened from a URL that is not in `APP_PUBLIC_URLS`. To the
browser, `localhost` and `127.0.0.1` are different origins, so both are listed by default. For
any other URL, add it to `APP_PUBLIC_URLS` *and* to `DJANGO_CSRF_TRUSTED_ORIGINS` (otherwise
logout fails the CSRF check), re-run the setup and recreate the backend.
`setup_lan_https.py` does this for the home network addresses.

## Local superusers

`ModelBackend` is still enabled, so `manage.py createsuperuser` gives a local account for
`/admin/` that works even when Keycloak is down. It is separate from any Keycloak account.
