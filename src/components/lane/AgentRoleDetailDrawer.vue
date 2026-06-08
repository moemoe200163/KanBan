<script setup lang="ts">
/**
 * AgentRoleDetailDrawer — slide-in panel showing full agent role details.
 *
 * Props:
 *   role    — AgentRole to display (null = closed)
 *   visible — controls open/close
 *
 * Emits:
 *   close — request to close drawer
 *   edit  — request to edit this role
 */

import type { AgentRole } from '~/types'
import { X, Pencil } from 'lucide-vue-next'

defineProps<{
  role: AgentRole | null
  visible: boolean
}>()

const emit = defineEmits<{
  'close': []
  'edit': [role: AgentRole]
}>()

const RETRY_LABELS: Record<string, string> = {
  none: 'None',
  fixed: 'Fixed delay',
  exponential: 'Exponential backoff',
}
</script>

<template>
  <Teleport to="body">
    <Transition name="drawer">
      <aside
        v-if="visible && role"
        class="role-drawer"
        data-testid="agent-role-detail-drawer"
      >
        <header class="role-drawer__head">
          <div class="role-drawer__title">
            <h2>{{ role.displayName }}</h2>
            <span class="role-drawer__key">{{ role.key }}</span>
            <span
              v-if="role.isSystem"
              class="role-drawer__badge role-drawer__badge--system"
            >
              System
            </span>
            <span
              v-if="!role.enabled"
              class="role-drawer__badge role-drawer__badge--disabled"
            >
              Disabled
            </span>
          </div>
          <div class="role-drawer__head-actions">
            <button
              class="role-drawer__edit-btn"
              title="Edit role"
              @click="emit('edit', role)"
            >
              <Pencil :size="14" />
              Edit
            </button>
            <button class="role-drawer__close" @click="emit('close')">
              <X :size="16" />
            </button>
          </div>
        </header>

        <section class="role-drawer__section">
          <h3>Description</h3>
          <p class="role-drawer__desc">{{ role.description || '(no description)' }}</p>
        </section>

        <section class="role-drawer__section">
          <h3>Configuration</h3>
          <dl class="role-drawer__dl">
            <div class="role-drawer__dl-row">
              <dt>Default Provider</dt>
              <dd>{{ role.defaultProvider || '(not set)' }}</dd>
            </div>
            <div class="role-drawer__dl-row">
              <dt>Default Model</dt>
              <dd>{{ role.defaultModel || '(not set)' }}</dd>
            </div>
            <div class="role-drawer__dl-row">
              <dt>Timeout</dt>
              <dd>{{ role.timeoutSeconds }}s</dd>
            </div>
            <div class="role-drawer__dl-row">
              <dt>Retry Policy</dt>
              <dd>{{ RETRY_LABELS[role.retryPolicy] || role.retryPolicy }}</dd>
            </div>
            <div class="role-drawer__dl-row">
              <dt>Max Retries</dt>
              <dd>{{ role.retryMax }}</dd>
            </div>
            <div class="role-drawer__dl-row">
              <dt>Human Approval</dt>
              <dd>{{ role.humanApprovalRequired ? 'Required' : 'Not required' }}</dd>
            </div>
            <div class="role-drawer__dl-row">
              <dt>Enabled</dt>
              <dd>{{ role.enabled ? 'Yes' : 'No' }}</dd>
            </div>
          </dl>
        </section>

        <section class="role-drawer__section">
          <h3>Allowed Profiles</h3>
          <div class="role-drawer__chips">
            <span
              v-for="profile in role.allowedProfiles"
              :key="profile"
              class="role-drawer__chip"
            >
              {{ profile }}
            </span>
            <span v-if="!role.allowedProfiles.length" class="role-drawer__empty">(none)</span>
          </div>
        </section>

        <section class="role-drawer__section">
          <h3>Allowed Commands</h3>
          <div class="role-drawer__chips">
            <span
              v-for="cmd in role.allowedCommands"
              :key="cmd"
              class="role-drawer__chip role-drawer__chip--cmd"
            >
              {{ cmd }}
            </span>
            <span v-if="!role.allowedCommands.length" class="role-drawer__empty">(none)</span>
          </div>
        </section>

        <section class="role-drawer__section">
          <h3>Required Completion Fields</h3>
          <div class="role-drawer__chips">
            <span
              v-for="field in role.requiredCompletionFields"
              :key="field"
              class="role-drawer__chip role-drawer__chip--field"
            >
              {{ field }}
            </span>
            <span v-if="!role.requiredCompletionFields.length" class="role-drawer__empty">(none)</span>
          </div>
        </section>

        <section class="role-drawer__section">
          <h3>Next Roles</h3>
          <div class="role-drawer__chips">
            <span
              v-for="nr in role.nextRoles"
              :key="nr"
              class="role-drawer__chip role-drawer__chip--next"
            >
              {{ nr }}
            </span>
            <span v-if="!role.nextRoles.length" class="role-drawer__empty">(none)</span>
          </div>
        </section>

        <footer v-if="role.createdAt || role.updatedAt" class="role-drawer__footer">
          <span v-if="role.createdAt">Created: {{ new Date(role.createdAt).toLocaleDateString() }}</span>
          <span v-if="role.updatedAt">Updated: {{ new Date(role.updatedAt).toLocaleDateString() }}</span>
        </footer>
      </aside>
    </Transition>
  </Teleport>
</template>

<style scoped>
.role-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(440px, 100vw);
  background: var(--surface-card);
  border-left: 1px solid var(--hairline);
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 18px;
  overflow-y: auto;
  z-index: 50;
  box-shadow: -8px 0 24px rgba(0, 0, 0, 0.08);
}

.role-drawer__head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.role-drawer__title {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.role-drawer__title h2 {
  font-family: var(--font-display);
  font-size: 1.1rem;
  margin: 0;
  color: var(--ink);
}

.role-drawer__key {
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--muted);
}

.role-drawer__badge {
  display: inline-flex;
  align-self: flex-start;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 0.6875rem;
  font-weight: 600;
}

.role-drawer__badge--system {
  background: rgba(107, 139, 164, 0.15);
  color: #6b8ba4;
}

.role-drawer__badge--disabled {
  background: rgba(142, 139, 130, 0.15);
  color: #8e8b82;
}

.role-drawer__head-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.role-drawer__edit-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--ink);
  background: var(--canvas);
  border: 1px solid var(--hairline);
  border-radius: 6px;
  cursor: pointer;
}

.role-drawer__close {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  background: transparent;
  border: 1px solid var(--hairline);
  border-radius: 6px;
  cursor: pointer;
  color: var(--muted);
}

.role-drawer__section h3 {
  margin: 0 0 8px;
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--muted);
}

.role-drawer__desc {
  margin: 0;
  color: var(--ink);
  font-size: 0.875rem;
  line-height: 1.5;
}

.role-drawer__dl {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
}

.role-drawer__dl-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--hairline);
}

.role-drawer__dl-row:last-child {
  border-bottom: none;
}

.role-drawer__dl-row dt {
  font-size: 0.8125rem;
  color: var(--muted);
}

.role-drawer__dl-row dd {
  margin: 0;
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--ink);
  font-family: var(--font-mono);
}

.role-drawer__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.role-drawer__chip {
  display: inline-flex;
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 600;
  background: rgba(107, 139, 164, 0.12);
  color: #6b8ba4;
}

.role-drawer__chip--cmd {
  background: rgba(204, 120, 92, 0.12);
  color: #cc785c;
}

.role-drawer__chip--field {
  background: rgba(212, 168, 75, 0.12);
  color: #d4a84b;
}

.role-drawer__chip--next {
  background: rgba(125, 158, 125, 0.12);
  color: #7d9e7d;
}

.role-drawer__empty {
  font-size: 0.8125rem;
  color: var(--muted);
  font-style: italic;
}

.role-drawer__footer {
  display: flex;
  gap: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--hairline);
  font-size: 0.75rem;
  color: var(--muted);
}

.drawer-enter-active,
.drawer-leave-active {
  transition: transform 200ms ease-out;
}

.drawer-enter-from,
.drawer-leave-to {
  transform: translateX(100%);
}
</style>
