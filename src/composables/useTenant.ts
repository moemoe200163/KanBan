/**
 * useTenant — tenant context (Plan J MVP, single tenant per user).
 *
 * Plan J ships with 1 user = 1 tenant, so this composable is mostly
 * a thin wrapper around the tenant fields on `useAuth().authUser`.
 * The `switchTenant(slug)` surface is intentionally a no-op stub —
 * Plan K will introduce the real multi-tenant switcher (one-user-
 * many-tenant) once OAuth is in place.
 */
interface TenantSummary {
  id: string
  slug: string
  name?: string
  plan?: string
}

export function useTenant() {
  const { authUser, currentTenantId, currentTenantSlug, fetchRole } = useAuth()

  const currentTenant = computed<TenantSummary | null>(() => {
    const u = authUser.value
    if (!u) return null
    // super_admin has no tenant binding — `currentTenantSlug` is null
    // for them, which is the correct MVP behavior.
    if (!u.tenantId) return null
    return {
      id: u.tenantId,
      slug: u.tenantSlug ?? '',
    }
  })

  const hasTenant = computed(() => currentTenant.value !== null)

  /**
   * Switch the active tenant.
   *
   * Plan J MVP: this is a no-op that just re-fetches `/auth/me`.
   * Plan K: call `POST /tenants/{slug}/switch` (TBD) which re-issues
   * the JWT with the new `tenant_id` and updates the user store.
   *
   * We keep the surface so call sites don't have to change when
   * Plan K lands.
   */
  const switchTenant = async (_slug: string): Promise<void> => {
    // No-op in MVP. A future implementation will POST to a
    // switch endpoint and re-fetch /auth/me to refresh the JWT
    // claims. Re-fetching here means callers get a refresh
    // when the real implementation lands.
    await fetchRole()
  }

  return {
    currentTenant,
    currentTenantId,
    currentTenantSlug,
    hasTenant,
    switchTenant,
  }
}
