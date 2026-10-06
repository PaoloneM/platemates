// Same mark as the Keycloak login theme (keycloak/themes/mymenu/login/resources/img/logo.svg).
export function Logo({ size = 56 }: { size?: number }) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} aria-hidden="true">
      <circle cx="32" cy="32" r="30" fill="var(--accent)" />
      <circle cx="32" cy="32" r="17" fill="none" stroke="var(--on-accent)" strokeWidth="3" />
      <path
        d="M14 14v12a4 4 0 0 0 4 4v20M18 14v10M22 14v12a4 4 0 0 1-4 4"
        fill="none"
        stroke="var(--on-accent)"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <path
        d="M48 50V14c-4 2-6 8-6 14s2 7 6 7"
        fill="none"
        stroke="var(--on-accent)"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
