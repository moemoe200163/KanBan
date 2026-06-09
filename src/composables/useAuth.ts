/**
 * useAuth — lightweight auth state composable.
 *
 * Fetches /auth/me once to get the real user role.
 * Falls back to token-existence check when unauthenticated.
 */
export function useAuth() {
  const config = useRuntimeConfig()
  const token = useCookie('auth_token').value
  const userRole = ref<string | null>(null)
  const isAdmin = ref(false)
  const isLoading = ref(false)

  const fetchRole = async () => {
    if (!token) {
      isAdmin.value = false
      userRole.value = null
      return
    }
    isLoading.value = true
    try {
      const res = await fetch(`${config.public.apiBase}/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.ok) {
        const data = await res.json()
        userRole.value = data.role
        isAdmin.value = data.role === 'admin'
      } else {
        // Token invalid or expired
        userRole.value = null
        isAdmin.value = false
      }
    } catch {
      userRole.value = null
      isAdmin.value = false
    } finally {
      isLoading.value = false
    }
  }

  return { token, userRole, isAdmin, isLoading, fetchRole }
}
