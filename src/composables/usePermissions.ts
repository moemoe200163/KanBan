/**
 * usePermissions — feature-level permission gates built on top of useAuth.
 *
 * The gates map directly to the role matrix defined in Plan J §四
 * (super_admin / admin / ops / user). The frontend never re-derives
 * the role itself — it composes the role booleans into a flat list
 * of feature flags that templates can drop into `v-if` checks.
 *
 * Usage:
 *   const { canConfigureLLM, canDeleteIssue } = usePermissions()
 *   <button v-if="canConfigureLLM">Save</button>
 */
export function usePermissions() {
  const { isAdmin, isOps, isUser, isSuperAdmin, authUser } = useAuth()
  const currentUserId = computed(() => authUser.value?.id ?? null)

  return {
    /** Manage tenant membership, delete tenant, invite users. */
    canManageTenant: isAdmin,
    /** Configure LLM providers (baseUrl, model, apiKey, enable/disable). */
    canConfigureLLM: isOps,
    /** Create a new board. */
    canCreateBoard: isOps,
    /** Create a new issue in any board. */
    canCreateIssue: isUser,
    /** Delete an issue. */
    canDeleteIssue: isOps,
    /** Dispatch an ECC agent run. */
    canDispatch: isUser,
    /** View tenant-wide audit log. */
    canViewAudit: isOps,
    /** Edit agent role definitions. */
    canEditAgentRole: isOps,
    /** Toggle webhook enable / disable. */
    canToggleWebhook: isOps,
    /** View tenant analytics. */
    canViewAnalytics: isOps,
    /** Cross-tenant leader (super_admin only). UI uses this for
     *  the "All tenants" admin view that operators / admins never see. */
    canCrossTenant: isSuperAdmin,
    /**
     * Delete an AI Studio conversation. The rule is "ops or owner"
     * which the backend also enforces — this client-side check is
     * only there to keep the button out of sight.
     */
    canDeleteAIConversation: (conv: { ownerId?: string | null }) =>
      isOps.value ||
      (!!conv?.ownerId && conv.ownerId === currentUserId.value),
    /**
     * Edit a saved harness / execution default. Mirrors canConfigureLLM
     * for now since the two UIs share the same "Settings" surface; kept
     * separate so a future scope change is a one-line tweak.
     */
    canEditDefaults: isOps,
  }
}
