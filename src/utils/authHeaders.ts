/**
 * authHeaders — read auth token from cookie and return Authorization header.
 *
 * Used by store actions and composables that make authenticated API calls.
 * Works in both client-side Nuxt context and Pinia store actions.
 */

/** Returns Authorization header object if a valid auth_token cookie exists. */
export function authHeaders(): Record<string, string> {
  if (typeof document === 'undefined') return {}
  const match = document.cookie.match(new RegExp('(^| )auth_token=([^;]+)'))
  if (!match) return {}
  const token = decodeURIComponent(match[2])
  return token ? { Authorization: `Bearer ${token}` } : {}
}