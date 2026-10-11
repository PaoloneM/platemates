/** Where Grafana is: the admin plane only (served by the admin Traefik at /grafana). */
export function hasMonitoring(isAdmin: boolean): boolean {
  return isAdmin && window.location.hostname.startsWith('admin.')
}
