/**
 * useAuth — lightweight auth state composable.
 *
 * Fetches /auth/me once to get the real user role.
 * Falls back to token-existence check when unauthenticated.
 *
 * Provides:
 * - authUser: full user object from /auth/me (or null)
 * - isAuthenticated: whether user is logged in (token exists and /auth/me returned a user)
 * - isAdmin: whether user has admin role
 * - authChecked: whether initial auth check has completed (use this to avoid UI flash)
 * - isLoading: whether the auth check is in progress
 * - fetchRole: call this to re-check auth state (e.g., after login)
 */
export function useAuth() {
  const config = useRuntimeConfig()
  const authUser = ref<{ id: string; username: string; role: string | null } | null>(null)
  const authChecked = ref(false)
  const isLoading = ref(false)

  const isAuthenticated = computed(() => !!authUser.value)
  const isAdmin = computed(() => authUser.value?.role === 'admin')

  const fetchRole = async () => {
    authChecked.value = false
    // Re-read cookie each time to get the current token value (not a snapshot)
    const currentToken = useCookie('auth_token').value
    if (!currentToken) {
      authUser.value = null
      authChecked.value = true
      return
    }
    isLoading.value = true
    try {
      const res = await fetch(`${config.public.apiBase}/auth/me`, {
        headers: { Authorization: `Bearer ${currentToken}` },
      })
      if (res.ok) {
        const data = await res.json()
        authUser.value = { id: data.id, username: data.username, role: data.role ?? null }
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
    authChecked,
    isLoading,
    fetchRole,
  }
}
