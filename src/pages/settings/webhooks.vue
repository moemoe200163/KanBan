<script setup lang="ts">
definePageMeta({
  layout: 'default'
})

// Tab configuration
const activeTab = ref('webhooks')
const tabs = [
  { id: 'webhooks', label: 'Webhooks', icon: 'webhook' },
  { id: 'agents', label: 'Agents', icon: 'bot' },
  { id: 'integrations', label: 'Integrations', icon: 'plug' },
  { id: 'budget', label: 'Budget', icon: 'credit-card' }
]

// Webhook configuration state
interface WebhookEndpoint {
  id: string
  name: string
  url: string
  events: string[]
  active: boolean
  createdAt: string
}

const webhooks = ref<WebhookEndpoint[]>([
  {
    id: 'wh_1',
    name: 'GitHub Integration',
    url: 'https://api.devflow.io/webhooks/github',
    events: ['push', 'pull_request', 'issue'],
    active: true,
    createdAt: '2024-01-15'
  },
  {
    id: 'wh_2',
    name: 'Slack Notifications',
    url: 'https://hooks.slack.com/services/T00/B00/XXX',
    events: ['task_completed', 'agent_error'],
    active: true,
    createdAt: '2024-02-20'
  },
  {
    id: 'wh_3',
    name: 'CI/CD Pipeline',
    url: 'https://ci.devflow.io/webhooks/pipeline',
    events: ['build_started', 'build_completed', 'build_failed'],
    active: false,
    createdAt: '2024-03-10'
  }
])

const availableEvents = [
  { id: 'push', label: 'Push' },
  { id: 'pull_request', label: 'Pull Request' },
  { id: 'issue', label: 'Issue' },
  { id: 'task_completed', label: 'Task Completed' },
  { id: 'task_created', label: 'Task Created' },
  { id: 'agent_error', label: 'Agent Error' },
  { id: 'agent_started', label: 'Agent Started' },
  { id: 'build_started', label: 'Build Started' },
  { id: 'build_completed', label: 'Build Completed' },
  { id: 'build_failed', label: 'Build Failed' }
]

const isEditing = ref(false)
const editingWebhook = ref<WebhookEndpoint | null>(null)
const showAddModal = ref(false)

const newWebhook = ref({
  name: '',
  url: '',
  events: [] as string[]
})

// Computed
const activeWebhooks = computed(() => webhooks.value.filter(w => w.active))
const inactiveWebhooks = computed(() => webhooks.value.filter(w => !w.active))

// Methods
function toggleWebhook(id: string) {
  const webhook = webhooks.value.find(w => w.id === id)
  if (webhook) {
    webhook.active = !webhook.active
  }
}

function deleteWebhook(id: string) {
  const index = webhooks.value.findIndex(w => w.id === id)
  if (index !== -1) {
    webhooks.value.splice(index, 1)
  }
}

function startEdit(webhook: WebhookEndpoint) {
  editingWebhook.value = { ...webhook }
  isEditing.value = true
}

function cancelEdit() {
  editingWebhook.value = null
  isEditing.value = false
}

function saveEdit() {
  if (editingWebhook.value) {
    const index = webhooks.value.findIndex(w => w.id === editingWebhook.value!.id)
    if (index !== -1) {
      webhooks.value[index] = { ...editingWebhook.value }
    }
  }
  cancelEdit()
}

function openAddModal() {
  newWebhook.value = {
    name: '',
    url: '',
    events: []
  }
  showAddModal.value = true
}

function closeAddModal() {
  showAddModal.value = false
}

function addWebhook() {
  if (newWebhook.value.name && newWebhook.value.url) {
    const webhook: WebhookEndpoint = {
      id: `wh_${Date.now()}`,
      name: newWebhook.value.name,
      url: newWebhook.value.url,
      events: [...newWebhook.value.events],
      active: true,
      createdAt: new Date().toISOString().split('T')[0]
    }
    webhooks.value.push(webhook)
    closeAddModal()
  }
}

function toggleEvent(webhook: WebhookEndpoint, eventId: string) {
  const index = webhook.events.indexOf(eventId)
  if (index === -1) {
    webhook.events.push(eventId)
  } else {
    webhook.events.splice(index, 1)
  }
}
</script>

<template>
  <div class="settings-page">
    <header class="settings-page__header">
      <h1 class="settings-page__title">Settings</h1>
    </header>

    <!-- Tab Navigation -->
    <nav class="settings-page__nav">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="settings-page__tab"
        :class="{ 'settings-page__tab--active': activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        <span class="settings-page__tab-icon">
          <svg v-if="tab.icon === 'webhook'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M18 16.98h-5.99c-1.1 0-1.95.94-2.48 1.9A4 4 0 0 1 2 17c.01-.7.2-1.4.57-2"/>
            <path d="m6 17 3.13-5.78c.53-.97.43-2.17-.26-3.07l-4.4-5.61A4 4 0 0 1 6 7.9c.01-.7.2-1.4.57-2"/>
            <path d="m18 7 3.13 5.78c.53.97.43 2.17-.26 3.07l-4.4 5.61A4 4 0 0 1 12 16.1c.01-.7.2-1.4.57-2"/>
            <path d="m6 7-3.13 5.78A2 2 0 0 0 4.9 15l4.4 5.61A4 4 0 0 1 12 22c.01-.7.2-1.4.57-2"/>
          </svg>
          <svg v-else-if="tab.icon === 'bot'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 8V4H8"/>
            <rect width="16" height="12" x="4" y="8" rx="2"/>
            <path d="M2 14h2M20 14h2M15 13v2M9 13v2"/>
          </svg>
          <svg v-else-if="tab.icon === 'plug'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 22v-5"/>
            <path d="M9 8V2"/>
            <path d="M15 8V2"/>
            <path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"/>
          </svg>
          <svg v-else-if="tab.icon === 'credit-card'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect width="20" height="14" x="2" y="5" rx="2"/>
            <line x1="2" x2="22" y1="10" y2="10"/>
          </svg>
        </span>
        {{ tab.label }}
      </button>
    </nav>

    <!-- Tab Content -->
    <div class="settings-page__content">
      <!-- Webhooks Tab -->
      <div v-if="activeTab === 'webhooks'" class="settings-page__panel">
        <div class="webhooks-panel">
          <div class="webhooks-panel__header">
            <div>
              <h2 class="webhooks-panel__title">Webhook Endpoints</h2>
              <p class="webhooks-panel__description">
                Configure webhooks to receive real-time notifications when events occur in your DevFlow workspace.
              </p>
            </div>
            <button class="webhooks-panel__add-btn" @click="openAddModal">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="12" x2="12" y1="5" y2="19"/>
                <line x1="5" x2="19" y1="12" y2="12"/>
              </svg>
              Add Webhook
            </button>
          </div>

          <!-- Active Webhooks -->
          <div v-if="activeWebhooks.length > 0" class="webhooks-section">
            <h3 class="webhooks-section__title">Active</h3>
            <div class="webhooks-list">
              <div
                v-for="webhook in activeWebhooks"
                :key="webhook.id"
                class="webhook-item"
              >
                <div class="webhook-item__main">
                  <div class="webhook-item__info">
                    <div class="webhook-item__header">
                      <span class="webhook-item__name">{{ webhook.name }}</span>
                      <span class="webhook-item__status webhook-item__status--active">Active</span>
                    </div>
                    <span class="webhook-item__url">{{ webhook.url }}</span>
                    <div class="webhook-item__events">
                      <span
                        v-for="event in webhook.events"
                        :key="event"
                        class="webhook-item__event-tag"
                      >
                        {{ event }}
                      </span>
                    </div>
                  </div>
                  <div class="webhook-item__actions">
                    <button
                      class="webhook-item__action-btn webhook-item__action-btn--toggle"
                      :class="{ 'webhook-item__action-btn--active': webhook.active }"
                      @click="toggleWebhook(webhook.id)"
                      :title="webhook.active ? 'Disable webhook' : 'Enable webhook'"
                    >
                      <svg v-if="webhook.active" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                        <circle cx="12" cy="12" r="3"/>
                      </svg>
                      <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
                        <line x1="1" x2="23" y1="1" y2="23"/>
                      </svg>
                    </button>
                    <button
                      class="webhook-item__action-btn"
                      @click="startEdit(webhook)"
                      title="Edit webhook"
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                      </svg>
                    </button>
                    <button
                      class="webhook-item__action-btn webhook-item__action-btn--danger"
                      @click="deleteWebhook(webhook.id)"
                      title="Delete webhook"
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"/>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                        <line x1="10" x2="10" y1="11" y2="17"/>
                        <line x1="14" x2="14" y1="11" y2="17"/>
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Inactive Webhooks -->
          <div v-if="inactiveWebhooks.length > 0" class="webhooks-section">
            <h3 class="webhooks-section__title">Inactive</h3>
            <div class="webhooks-list">
              <div
                v-for="webhook in inactiveWebhooks"
                :key="webhook.id"
                class="webhook-item webhook-item--inactive"
              >
                <div class="webhook-item__main">
                  <div class="webhook-item__info">
                    <div class="webhook-item__header">
                      <span class="webhook-item__name">{{ webhook.name }}</span>
                      <span class="webhook-item__status webhook-item__status--inactive">Inactive</span>
                    </div>
                    <span class="webhook-item__url">{{ webhook.url }}</span>
                    <div class="webhook-item__events">
                      <span
                        v-for="event in webhook.events"
                        :key="event"
                        class="webhook-item__event-tag"
                      >
                        {{ event }}
                      </span>
                    </div>
                  </div>
                  <div class="webhook-item__actions">
                    <button
                      class="webhook-item__action-btn webhook-item__action-btn--toggle"
                      :class="{ 'webhook-item__action-btn--active': webhook.active }"
                      @click="toggleWebhook(webhook.id)"
                      :title="webhook.active ? 'Disable webhook' : 'Enable webhook'"
                    >
                      <svg v-if="webhook.active" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                        <circle cx="12" cy="12" r="3"/>
                      </svg>
                      <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
                        <line x1="1" x2="23" y1="1" y2="23"/>
                      </svg>
                    </button>
                    <button
                      class="webhook-item__action-btn"
                      @click="startEdit(webhook)"
                      title="Edit webhook"
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                      </svg>
                    </button>
                    <button
                      class="webhook-item__action-btn webhook-item__action-btn--danger"
                      @click="deleteWebhook(webhook.id)"
                      title="Delete webhook"
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"/>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                        <line x1="10" x2="10" y1="11" y2="17"/>
                        <line x1="14" x2="14" y1="11" y2="17"/>
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Empty State -->
          <div v-if="webhooks.length === 0" class="webhooks-empty">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M18 16.98h-5.99c-1.1 0-1.95.94-2.48 1.9A4 4 0 0 1 2 17c.01-.7.2-1.4.57-2"/>
              <path d="m6 17 3.13-5.78c.53-.97.43-2.17-.26-3.07l-4.4-5.61A4 4 0 0 1 6 7.9c.01-.7.2-1.4.57-2"/>
            </svg>
            <h3>No webhooks configured</h3>
            <p>Add your first webhook endpoint to start receiving event notifications.</p>
            <button class="webhooks-empty__btn" @click="openAddModal">Add Webhook</button>
          </div>
        </div>

        <!-- Edit Modal -->
        <div v-if="isEditing && editingWebhook" class="modal-overlay" @click.self="cancelEdit">
          <div class="modal">
            <div class="modal__header">
              <h3 class="modal__title">Edit Webhook</h3>
              <button class="modal__close" @click="cancelEdit">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="18" x2="6" y1="6" y2="18"/>
                  <line x1="6" x2="18" y1="6" y2="18"/>
                </svg>
              </button>
            </div>
            <div class="modal__body">
              <div class="form-group">
                <label class="form-label">Name</label>
                <input
                  v-model="editingWebhook.name"
                  type="text"
                  class="form-input"
                  placeholder="Webhook name"
                />
              </div>
              <div class="form-group">
                <label class="form-label">URL</label>
                <input
                  v-model="editingWebhook.url"
                  type="url"
                  class="form-input"
                  placeholder="https://example.com/webhook"
                />
              </div>
              <div class="form-group">
                <label class="form-label">Events</label>
                <div class="events-grid">
                  <label
                    v-for="event in availableEvents"
                    :key="event.id"
                    class="event-checkbox"
                    :class="{ 'event-checkbox--checked': editingWebhook.events.includes(event.id) }"
                  >
                    <input
                      type="checkbox"
                      :checked="editingWebhook.events.includes(event.id)"
                      @change="toggleEvent(editingWebhook, event.id)"
                    />
                    <span>{{ event.label }}</span>
                  </label>
                </div>
              </div>
            </div>
            <div class="modal__footer">
              <button class="btn btn--secondary" @click="cancelEdit">Cancel</button>
              <button class="btn btn--primary" @click="saveEdit">Save Changes</button>
            </div>
          </div>
        </div>

        <!-- Add Modal -->
        <div v-if="showAddModal" class="modal-overlay" @click.self="closeAddModal">
          <div class="modal">
            <div class="modal__header">
              <h3 class="modal__title">Add Webhook</h3>
              <button class="modal__close" @click="closeAddModal">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="18" x2="6" y1="6" y2="18"/>
                  <line x1="6" x2="18" y1="6" y2="18"/>
                </svg>
              </button>
            </div>
            <div class="modal__body">
              <div class="form-group">
                <label class="form-label">Name</label>
                <input
                  v-model="newWebhook.name"
                  type="text"
                  class="form-input"
                  placeholder="e.g., GitHub Integration"
                />
              </div>
              <div class="form-group">
                <label class="form-label">Endpoint URL</label>
                <input
                  v-model="newWebhook.url"
                  type="url"
                  class="form-input"
                  placeholder="https://example.com/webhook"
                />
              </div>
              <div class="form-group">
                <label class="form-label">Events</label>
                <div class="events-grid">
                  <label
                    v-for="event in availableEvents"
                    :key="event.id"
                    class="event-checkbox"
                    :class="{ 'event-checkbox--checked': newWebhook.events.includes(event.id) }"
                  >
                    <input
                      type="checkbox"
                      :checked="newWebhook.events.includes(event.id)"
                      @change="
                        newWebhook.events.includes(event.id)
                          ? newWebhook.events = newWebhook.events.filter(e => e !== event.id)
                          : newWebhook.events.push(event.id)
                      "
                    />
                    <span>{{ event.label }}</span>
                  </label>
                </div>
              </div>
            </div>
            <div class="modal__footer">
              <button class="btn btn--secondary" @click="closeAddModal">Cancel</button>
              <button class="btn btn--primary" @click="addWebhook">Add Webhook</button>
            </div>
          </div>
        </div>
      </div>

      <!-- Agents Tab -->
      <div v-if="activeTab === 'agents'" class="settings-page__panel">
        <AgentStatusPanel :compact="false" />
      </div>

      <!-- Integrations Tab (placeholder) -->
      <div v-if="activeTab === 'integrations'" class="settings-page__panel">
        <div class="placeholder-panel">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M12 22v-5"/>
            <path d="M9 8V2"/>
            <path d="M15 8V2"/>
            <path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"/>
          </svg>
          <h3>Integrations</h3>
          <p>Connect DevFlow with your favorite tools and services.</p>
        </div>
      </div>

      <!-- Budget Tab (placeholder) -->
      <div v-if="activeTab === 'budget'" class="settings-page__panel">
        <div class="placeholder-panel">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <rect width="20" height="14" x="2" y="5" rx="2"/>
            <line x1="2" x2="22" y1="10" y2="10"/>
          </svg>
          <h3>Budget &amp; Billing</h3>
          <p>Manage your subscription and usage limits.</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  padding: var(--space-6);
  gap: var(--space-6);
  overflow-y: auto;
  max-width: 1200px;
  margin: 0 auto;
}

.settings-page__header {
  margin-bottom: var(--space-6);
}

.settings-page__title {
  font-size: 1.75rem;
  font-weight: 600;
  color: var(--ink);
  font-family: var(--font-display);
}

.settings-page__nav {
  display: flex;
  gap: var(--space-1);
  border-bottom: 1px solid var(--hairline);
  margin-bottom: var(--space-6);
  overflow-x: auto;
}

.settings-page__tab {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  color: var(--muted);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: 500;
  white-space: nowrap;
  transition: color var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out);
}

.settings-page__tab:hover {
  color: var(--body-strong);
}

.settings-page__tab--active {
  color: var(--primary);
  border-bottom-color: var(--primary);
}

.settings-page__tab-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0.8;
}

.settings-page__panel {
  animation: fadeIn var(--duration-normal) var(--ease-out);
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Webhooks Panel */
.webhooks-panel {
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
}

.webhooks-panel__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--space-6);
  gap: var(--space-4);
}

.webhooks-panel__title {
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--ink);
  margin: 0 0 var(--space-2);
}

.webhooks-panel__description {
  font-size: var(--text-sm);
  color: var(--muted);
  margin: 0;
  max-width: 480px;
}

.webhooks-panel__add-btn {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  background: var(--primary);
  color: var(--on-primary);
  border: none;
  border-radius: var(--radius-md);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-out),
              transform var(--duration-fast) var(--ease-out);
}

.webhooks-panel__add-btn:hover {
  background: var(--primary-hover);
}

.webhooks-panel__add-btn:active {
  background: var(--primary-active);
  transform: scale(0.98);
}

/* Webhooks Section */
.webhooks-section {
  margin-bottom: var(--space-6);
}

.webhooks-section:last-child {
  margin-bottom: 0;
}

.webhooks-section__title {
  font-size: var(--text-xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
  margin: 0 0 var(--space-3);
}

.webhooks-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

/* Webhook Item */
.webhook-item {
  background: var(--canvas);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  transition: border-color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out);
}

.webhook-item:hover {
  border-color: var(--hairline-soft);
  box-shadow: var(--shadow-sm);
}

.webhook-item--inactive {
  opacity: 0.7;
}

.webhook-item__main {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-4);
}

.webhook-item__info {
  flex: 1;
  min-width: 0;
}

.webhook-item__header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}

.webhook-item__name {
  font-weight: 600;
  color: var(--ink);
  font-size: var(--text-base);
}

.webhook-item__status {
  font-size: 0.625rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 2px 6px;
  border-radius: var(--radius-sm);
}

.webhook-item__status--active {
  background: rgba(125, 158, 125, 0.15);
  color: var(--sage-muted);
}

.webhook-item__status--inactive {
  background: var(--hairline);
  color: var(--muted);
}

.webhook-item__url {
  display: block;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--muted);
  margin-bottom: var(--space-3);
  word-break: break-all;
}

.webhook-item__events {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.webhook-item__event-tag {
  font-size: 0.625rem;
  font-weight: 500;
  padding: 2px 8px;
  background: var(--surface-cream-strong);
  color: var(--body);
  border-radius: var(--radius-sm);
}

.webhook-item__actions {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
}

.webhook-item__action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: transparent;
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  color: var(--muted);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}

.webhook-item__action-btn:hover {
  background: var(--surface-soft);
  border-color: var(--hairline-soft);
  color: var(--body-strong);
}

.webhook-item__action-btn--toggle.webhook-item__action-btn--active {
  background: rgba(125, 158, 125, 0.1);
  border-color: var(--sage-muted);
  color: var(--sage-muted);
}

.webhook-item__action-btn--danger:hover {
  background: rgba(184, 92, 77, 0.1);
  border-color: var(--clay-red-muted);
  color: var(--clay-red);
}

/* Empty State */
.webhooks-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-12) var(--space-6);
  text-align: center;
  color: var(--muted);
}

.webhooks-empty svg {
  margin-bottom: var(--space-4);
  opacity: 0.5;
}

.webhooks-empty h3 {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--body-strong);
  margin: 0 0 var(--space-2);
}

.webhooks-empty p {
  font-size: var(--text-sm);
  margin: 0 0 var(--space-6);
  max-width: 320px;
}

.webhooks-empty__btn {
  padding: var(--space-2) var(--space-4);
  background: var(--primary);
  color: var(--on-primary);
  border: none;
  border-radius: var(--radius-md);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-out);
}

.webhooks-empty__btn:hover {
  background: var(--primary-hover);
}

/* Placeholder Panel */
.placeholder-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-12);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-lg);
  text-align: center;
  color: var(--muted);
}

.placeholder-panel svg {
  margin-bottom: var(--space-4);
  opacity: 0.5;
}

.placeholder-panel h3 {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--body-strong);
  margin: 0 0 var(--space-2);
}

.placeholder-panel p {
  font-size: var(--text-sm);
  margin: 0;
}

/* Modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(20, 20, 19, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-4);
  z-index: 1000;
  animation: fadeIn var(--duration-fast) var(--ease-out);
}

.modal {
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-xl);
  width: 100%;
  max-width: 480px;
  max-height: calc(100dvh - 40px);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-xl);
  animation: slideUp var(--duration-normal) var(--ease-out);
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(16px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.modal__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-4) var(--space-6);
  border-bottom: 1px solid var(--hairline);
}

.modal__title {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--ink);
  margin: 0;
}

.modal__close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: transparent;
  border: none;
  border-radius: var(--radius-md);
  color: var(--muted);
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out);
}

.modal__close:hover {
  background: var(--surface-soft);
  color: var(--body-strong);
}

.modal__body {
  padding: var(--space-6);
  overflow-y: auto;
}

.modal__footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-6);
  border-top: 1px solid var(--hairline);
  background: var(--surface-soft);
}

/* Form Elements */
.form-group {
  margin-bottom: var(--space-5);
}

.form-group:last-child {
  margin-bottom: 0;
}

.form-label {
  display: block;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--body-strong);
  margin-bottom: var(--space-2);
}

.form-input {
  width: 100%;
  padding: var(--space-3);
  background: var(--canvas);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  color: var(--ink);
  transition: border-color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out);
}

.form-input::placeholder {
  color: var(--muted-soft);
}

.form-input:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(204, 120, 92, 0.15);
}

.events-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-2);
}

.event-checkbox {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--canvas);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  cursor: pointer;
  font-size: var(--text-sm);
  color: var(--body);
  transition: all var(--duration-fast) var(--ease-out);
}

.event-checkbox:hover {
  border-color: var(--hairline-soft);
}

.event-checkbox--checked {
  background: rgba(204, 120, 92, 0.08);
  border-color: var(--primary-muted);
  color: var(--ink);
}

.event-checkbox input {
  display: none;
}

/* Buttons */
.btn {
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}

.btn--primary {
  background: var(--primary);
  border: none;
  color: var(--on-primary);
}

.btn--primary:hover {
  background: var(--primary-hover);
}

.btn--primary:active {
  background: var(--primary-active);
}

.btn--secondary {
  background: transparent;
  border: 1px solid var(--hairline);
  color: var(--body-strong);
}

.btn--secondary:hover {
  background: var(--surface-soft);
  border-color: var(--hairline-soft);
}

/* Dark mode overrides */
:global(.dark) .webhooks-panel,
:global(.dark) .modal {
  --surface-card: var(--surface-dark);
  --hairline: rgba(255, 255, 255, 0.08);
  --hairline-soft: rgba(255, 255, 255, 0.12);
  --canvas: var(--surface-dark-elevated);
  --surface-soft: var(--surface-dark-soft);
  --surface-cream-strong: rgba(255, 255, 255, 0.06);
  --ink: var(--on-dark);
  --body-strong: var(--on-dark);
  --body: var(--on-dark-soft);
  --muted: var(--on-dark-soft);
}
</style>
