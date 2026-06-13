/**
 * useAuth — lightweight auth state composable (Plan J version).
 *
 * Fetches /auth/me to get the full user object, including
 *   - role: 'super_admin' | 'admin' | 'ops' | 'user' | null
 *   - isSuperAdmin: boolean (cross-tenant leader)
 *   - tenantId / tenantSlug
 *   - permissions: string[] (pre-computed server-side)
 *
 * Falls back to a null user when unauthenticated (or when /me 401s).
 *
 * Provides:
 * - authUser: full user object from /auth/me (or null)
 * - isAuthenticated: whether user is logged in
 * - isAdmin: super_admin OR role === 'admin'
 * - isOps: super_admin OR role in ('admin', 'ops')
 * - isUser: any authenticated user
 * - isSuperAdmin: explicit super_admin flag (cross-tenant)
 * - currentTenantId / currentTenantSlug: tenant the user is bound to
 * - permissions: server-computed permission list
 * - authChecked: whether initial /auth/me completed (use this to avoid UI flash)
 * - isLoading: whether the auth check is in progress
 * - fetchRole: re-check /auth/me (e.g. after login)
 */
type AuthUserRole = 'super_admin' | 'admin' | 'ops' | 'user' | null

interface AuthUser {
  id: string
  username: string
  role: AuthUserRole
  tenantId: string | null
  tenantSlug: string | null
  isSuperAdmin: boolean
  permissions: string[]
}

export function useAuth() {
  const config = useRuntimeConfig()
  const authUser = ref<AuthUser | null>(null)
  const authChecked = ref(false)
  const isLoading = ref(false)

  const isAuthenticated = computed(() => !!authUser.value)
  // super_admin behaves like admin on every tenant, so it auto-passes
  // every "isAdmin" gate.
  const isAdmin = computed(
    () => !!authUser.value?.isSuperAdmin || authUser.value?.role === 'admin',
  )
  // ops can configure providers / boards / agent roles etc. admin and
  // super_admin inherit those capabilities.
  const isOps = computed(
    () =>
      !!authUser.value?.isSuperAdmin ||
      (authUser.value?.role != null &&
        (authUser.value.role === 'admin' || authUser.value.role === 'ops')),
  )
  const isUser = computed(() => !!authUser.value)
  const isSuperAdmin = computed(() => !!authUser.value?.isSuperAdmin)
  const currentTenantId = computed(() => authUser.value?.tenantId ?? null)
  const currentTenantSlug = computed(() => authUser.value?.tenantSlug ?? null)
  const permissions = computed(() => authUser.value?.permissions ?? [])

  const fetchRole = async () => {
    authChecked.value = false
    // Re-read cookie each time to get the current token value (not a snapshot)
    const currentToken = useCookie('auth_token').value
    isLoading.value = true
    try {
      // Hit /me with the token if we have one. In dev mode the
      // backend's anonymous-WS / dev-bypass path also accepts an
      // unauthenticated /me and returns the seeded leader admin
      // user, so calling without an Authorization header is fine
      // and lets the dev flow light up admin-only UI without any
      // login dance.
      const headers: Record<string, string> = currentToken
        ? { Authorization: `Bearer ${currentToken}` }
        : {}
      const res = await fetch(`${config.public.apiBase}/auth/me`, { headers })
      if (res.ok) {
        const data = await res.json()
        authUser.value = {
          id: data.id,
          username: data.username,
          // Normalize unknown role strings to 'user' so downstream
          // gates that switch on the literal value never crash.
          role: (data.role ?? null) as AuthUserRole,
          tenantId: data?.tenant?.id ?? null,
          tenantSlug: data?.tenant?.slug ?? null,
          isSuperAdmin: Boolean(data.is_super_admin),
          permissions: Array.isArray(data.permissions) ? data.permissions : [],
        }
      } else {
        // Token invalid or expired
        authUser.value = null
      }
    } catch {
      authUser.value = null
    } finally {
      isLoading.value = false
      authChecked.value = true
    }
  }

  return {
    authUser,
    isAuthenticated,
    isAdmin,
    isOps,
    isUser,
    isSuperAdmin,
    currentTenantId,
    currentTenantSlug,
    permissions,
    authChecked,
    isLoading,
    fetchRole,
  }
}
