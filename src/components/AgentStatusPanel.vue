<script setup lang="ts">
// Agent status interface
export interface AgentInfo {
  id: string
  name: string
  role: string
  status: 'idle' | 'running' | 'error'
  currentTask?: string
  lastActive?: string
}

// Props
interface Props {
  compact?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  compact: false
})

// Agents data (will connect to store)
const agents = ref<AgentInfo[]>([
  { id: 'architect', name: 'Architect', role: 'System Designer', status: 'idle' },
  { id: 'frontend', name: 'Frontend', role: 'Nuxt Specialist', status: 'idle' },
  { id: 'backend', name: 'Backend', role: 'FastAPI Expert', status: 'idle' },
  { id: 'security', name: 'Security', role: 'Agent Shield', status: 'idle' },
  { id: 'qa', name: 'QA', role: 'Quality Assurance', status: 'idle' }
])

// Status color configuration
const statusColors = {
  idle: 'var(--sage)',
  running: 'var(--primary)',
  error: 'var(--clay-red)'
}
</script>

<template>
  <div
    class="agent-status-panel"
    :class="{ 'agent-status-panel--compact': compact }"
  >
    <div class="agent-status-panel__header">
      <h3 class="agent-status-panel__title">Team Agents</h3>
    </div>
    <div class="agent-status-panel__list">
      <div
        v-for="agent in agents"
        :key="agent.id"
        class="agent-item"
        :class="[`agent-item--${agent.status}`]"
      >
        <!-- Status dot -->
        <span
          class="agent-item__dot"
          :style="{ backgroundColor: statusColors[agent.status] }"
        />
        <!-- Agent info -->
        <div class="agent-item__info">
          <span class="agent-item__name">{{ agent.name }}</span>
          <span class="agent-item__role">{{ agent.role }}</span>
        </div>
        <!-- Running animation indicator -->
        <span
          v-if="agent.status === 'running'"
          class="agent-item__running-indicator"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-status-panel {
  --panel-bg: var(--surface-dark);
  --panel-border: rgba(255, 255, 255, 0.06);
  --text-primary: var(--on-dark);
  --text-secondary: var(--on-dark-soft);
  --text-muted: var(--on-dark-soft);

  background-color: var(--panel-bg);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  width: 100%;
  max-width: 280px;
}

.agent-status-panel--compact {
  max-width: 100%;
  padding: var(--space-3);
  border-radius: var(--radius-md);
}

.agent-status-panel__header {
  margin-bottom: var(--space-4);
}

.agent-status-panel--compact .agent-status-panel__header {
  margin-bottom: var(--space-3);
}

.agent-status-panel__title {
  font-family: var(--font-body);
  font-size: var(--text-xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-secondary);
  margin: 0;
}

.agent-status-panel--compact .agent-status-panel__title {
  font-size: 0.625rem;
}

.agent-status-panel__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.agent-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  background-color: rgba(255, 255, 255, 0.02);
  border: 1px solid transparent;
  cursor: default;
  transition:
    background-color var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out),
    transform var(--duration-fast) var(--ease-out);
}

.agent-status-panel--compact .agent-item {
  padding: var(--space-2) var(--space-3);
  gap: var(--space-2);
}

.agent-item:hover {
  background-color: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.08);
}

.agent-item:active {
  transform: scale(0.99);
}

.agent-item--running {
  background-color: rgba(204, 120, 92, 0.08);
  border-color: rgba(204, 120, 92, 0.15);
}

.agent-item--running:hover {
  background-color: rgba(204, 120, 92, 0.12);
  border-color: rgba(204, 120, 92, 0.2);
}

.agent-item--error {
  background-color: rgba(184, 92, 77, 0.08);
  border-color: rgba(184, 92, 77, 0.15);
}

.agent-item--error:hover {
  background-color: rgba(184, 92, 77, 0.12);
  border-color: rgba(184, 92, 77, 0.2);
}

.agent-item__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  transition: transform var(--duration-fast) var(--ease-out);
}

.agent-status-panel--compact .agent-item__dot {
  width: 6px;
  height: 6px;
}

.agent-item:hover .agent-item__dot {
  transform: scale(1.2);
}

.agent-item--idle .agent-item__dot {
  opacity: 0.7;
}

.agent-item--running .agent-item__dot {
  animation: pulse-glow 2s ease-in-out infinite;
}

.agent-item--error .agent-item__dot {
  opacity: 1;
}

@keyframes pulse-glow {
  0%, 100% {
    opacity: 1;
    box-shadow: 0 0 0 0 rgba(204, 120, 92, 0.4);
  }
  50% {
    opacity: 0.7;
    box-shadow: 0 0 0 4px rgba(204, 120, 92, 0);
  }
}

.agent-item__info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.agent-status-panel--compact .agent-item__info {
  gap: 1px;
}

.agent-item__name {
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-primary);
  line-height: 1.2;
}

.agent-status-panel--compact .agent-item__name {
  font-size: var(--text-xs);
}

.agent-item__role {
  font-family: var(--font-body);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: 1.2;
  opacity: 0.7;
}

.agent-status-panel--compact .agent-item__role {
  font-size: 0.625rem;
}

.agent-item__running-indicator {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: var(--primary);
  flex-shrink: 0;
  animation: pulse-glow 1.5s ease-in-out infinite;
}

.agent-status-panel--compact .agent-item__running-indicator {
  width: 5px;
  height: 5px;
}

/* Dark mode overrides (in case panel is used outside dark context) */
.dark .agent-status-panel {
  --panel-bg: var(--surface-dark);
  --panel-border: rgba(255, 255, 255, 0.06);
  --text-primary: var(--on-dark);
  --text-secondary: var(--on-dark-soft);
}
</style>
