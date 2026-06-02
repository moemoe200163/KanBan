<script setup lang="ts">
interface WebhookDelivery {
  id: string
  timestamp: string
  status: 'success' | 'failed' | 'pending'
  response_code: number
  payload: string
}

const webhookUrl = ref('https://devflow.example.com/api/v1/webhooks/trigger')
const webhookSecret = ref('sk_dev_xxxxx')
const deliveries = ref<WebhookDelivery[]>([
  {
    id: 'del_001',
    timestamp: '2026-06-01T10:30:00Z',
    status: 'success',
    response_code: 200,
    payload: '{"event":"issue.created","data":{"id":"123"}}'
  },
  {
    id: 'del_002',
    timestamp: '2026-06-01T09:15:00Z',
    status: 'failed',
    response_code: 500,
    payload: '{"event":"issue.updated","data":{"id":"122"}}'
  },
  {
    id: 'del_003',
    timestamp: '2026-06-01T08:45:00Z',
    status: 'pending',
    response_code: 0,
    payload: '{"event":"issue.deleted","data":{"id":"121"}}'
  }
])
const isTesting = ref(false)
const showSecret = ref(false)

const copyWebhookUrl = async () => {
  try {
    await navigator.clipboard.writeText(webhookUrl.value)
  } catch (err) {
    console.error('Failed to copy webhook URL:', err)
  }
}

const toggleSecretVisibility = () => {
  showSecret.value = !showSecret.value
}

const sendTestWebhook = async () => {
  isTesting.value = true
  try {
    // Simulate test webhook delivery
    await new Promise(resolve => setTimeout(resolve, 1500))

    const newDelivery: WebhookDelivery = {
      id: `del_${Date.now()}`,
      timestamp: new Date().toISOString(),
      status: 'success',
      response_code: 200,
      payload: '{"event":"test","data":{"timestamp":"' + new Date().toISOString() + '"}}'
    }

    deliveries.value.unshift(newDelivery)
  } catch (err) {
    console.error('Failed to send test webhook:', err)
  } finally {
    isTesting.value = false
  }
}

const formatTimestamp = (timestamp: string) => {
  const date = new Date(timestamp)
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const getStatusLabel = (status: WebhookDelivery['status']) => {
  const labels: Record<WebhookDelivery['status'], string> = {
    success: 'Success',
    failed: 'Failed',
    pending: 'Pending'
  }
  return labels[status]
}
</script>

<template>
  <div class="webhook-config">
    <h3 class="webhook-config__title">Webhook Configuration</h3>

    <!-- Webhook URL -->
    <div class="webhook-config__section">
      <label class="webhook-config__label">Webhook URL</label>
      <div class="webhook-config__url-row">
        <input
          type="text"
          :value="webhookUrl"
          readonly
          class="webhook-config__input"
        />
        <button @click="copyWebhookUrl" class="webhook-config__copy-btn">
          Copy
        </button>
      </div>
      <p class="webhook-config__hint">
        Use this URL to configure your external service
      </p>
    </div>

    <!-- Secret Key -->
    <div class="webhook-config__section">
      <label class="webhook-config__label">Secret Key</label>
      <div class="webhook-config__secret-row">
        <input
          :type="showSecret ? 'text' : 'password'"
          :value="webhookSecret"
          readonly
          class="webhook-config__input webhook-config__input--secret"
        />
        <button
          @click="toggleSecretVisibility"
          class="webhook-config__secret-toggle"
          :aria-label="showSecret ? 'Hide secret' : 'Show secret'"
        >
          {{ showSecret ? 'Hide' : 'Show' }}
        </button>
      </div>
      <p class="webhook-config__hint">
        Keep this secret secure. It is used to sign webhook payloads.
      </p>
    </div>

    <!-- Test Button -->
    <button
      @click="sendTestWebhook"
      class="webhook-config__test-btn"
      :disabled="isTesting"
    >
      <span v-if="isTesting" class="webhook-config__spinner" />
      {{ isTesting ? 'Sending...' : 'Send Test Webhook' }}
    </button>

    <!-- Delivery History -->
    <div class="webhook-config__history">
      <h4 class="webhook-config__history-title">Recent Deliveries</h4>

      <div v-if="deliveries.length === 0" class="webhook-config__empty">
        No webhook deliveries yet
      </div>

      <div
        v-for="delivery in deliveries"
        :key="delivery.id"
        class="delivery-item"
      >
        <span
          class="delivery-item__status"
          :class="`delivery-item__status--${delivery.status}`"
          :title="getStatusLabel(delivery.status)"
        />
        <span class="delivery-item__time">{{ formatTimestamp(delivery.timestamp) }}</span>
        <span
          class="delivery-item__code"
          :class="{ 'delivery-item__code--pending': delivery.status === 'pending' }"
        >
          {{ delivery.status === 'pending' ? '---' : delivery.response_code }}
        </span>
        <span class="delivery-item__payload truncate">{{ delivery.payload }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.webhook-config {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  padding: var(--space-6);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-lg);
}

.webhook-config__title {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-weight: 600;
  color: var(--ink);
  margin: 0;
}

.webhook-config__section {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.webhook-config__label {
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--body-strong);
}

.webhook-config__url-row,
.webhook-config__secret-row {
  display: flex;
  gap: var(--space-2);
}

.webhook-config__input {
  flex: 1;
  padding: var(--space-3) var(--space-4);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--ink);
  background: var(--canvas);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  transition: border-color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out);
}

.webhook-config__input:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(204, 120, 92, 0.15);
}

.webhook-config__input--secret {
  font-family: var(--font-mono);
  letter-spacing: 0.05em;
}

.webhook-config__copy-btn {
  padding: var(--space-3) var(--space-4);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--primary);
  background: transparent;
  border: 1px solid var(--primary);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  white-space: nowrap;
}

.webhook-config__copy-btn:hover {
  background: var(--primary);
  color: var(--on-primary);
}

.webhook-config__secret-toggle {
  padding: var(--space-3) var(--space-4);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--muted);
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  white-space: nowrap;
}

.webhook-config__secret-toggle:hover {
  color: var(--ink);
  border-color: var(--muted-soft);
}

.webhook-config__hint {
  font-family: var(--font-body);
  font-size: var(--text-xs);
  color: var(--muted-soft);
  margin: 0;
}

.webhook-config__test-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-6);
  font-family: var(--font-body);
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--on-primary);
  background: var(--primary);
  border: 1px solid var(--primary);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  align-self: flex-start;
}

.webhook-config__test-btn:hover:not(:disabled) {
  background: var(--primary-hover);
  border-color: var(--primary-hover);
}

.webhook-config__test-btn:active:not(:disabled) {
  background: var(--primary-active);
  border-color: var(--primary-active);
}

.webhook-config__test-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.webhook-config__spinner {
  width: 16px;
  height: 16px;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.webhook-config__history {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.webhook-config__history-title {
  font-family: var(--font-body);
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--ink);
  margin: 0;
}

.webhook-config__empty {
  padding: var(--space-6);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  color: var(--muted);
  text-align: center;
  background: var(--surface-soft);
  border-radius: var(--radius-md);
}

.delivery-item {
  display: grid;
  grid-template-columns: var(--space-3) var(--space-32) var(--space-16) 1fr;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--canvas);
  border: 1px solid var(--hairline-soft);
  border-radius: var(--radius-md);
  transition: border-color var(--duration-fast) var(--ease-out);
}

.delivery-item:hover {
  border-color: var(--hairline);
}

.delivery-item__status {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  justify-self: center;
}

.delivery-item__status--success {
  background: var(--sage);
}

.delivery-item__status--failed {
  background: var(--clay-red);
}

.delivery-item__status--pending {
  background: var(--amber);
  animation: pulse-glow 1.5s ease-in-out infinite;
}

@keyframes pulse-glow {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.delivery-item__time {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--muted);
}

.delivery-item__code {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--ink);
}

.delivery-item__code--pending {
  color: var(--muted-soft);
}

.delivery-item__payload {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--muted);
  max-width: 300px;
}

/* Dark Mode */
.dark .webhook-config {
  background: var(--surface-dark-elevated);
  border-color: var(--hairline);
}

.dark .webhook-config__title,
.dark .webhook-config__history-title {
  color: var(--on-dark);
}

.dark .webhook-config__label {
  color: var(--on-dark-soft);
}

.dark .webhook-config__input {
  color: var(--on-dark);
  background: var(--surface-dark);
  border-color: var(--hairline);
}

.dark .webhook-config__input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(204, 120, 92, 0.25);
}

.dark .webhook-config__copy-btn {
  color: var(--primary);
  border-color: var(--primary);
}

.dark .webhook-config__copy-btn:hover {
  background: var(--primary);
  color: var(--on-primary);
}

.dark .webhook-config__secret-toggle {
  color: var(--on-dark-soft);
  background: var(--surface-dark-soft);
  border-color: var(--hairline);
}

.dark .webhook-config__secret-toggle:hover {
  color: var(--on-dark);
  border-color: var(--muted-soft);
}

.dark .webhook-config__hint {
  color: var(--on-dark-soft);
}

.dark .webhook-config__empty {
  background: var(--surface-dark-soft);
  color: var(--on-dark-soft);
}

.dark .delivery-item {
  background: var(--surface-dark);
  border-color: var(--hairline);
}

.dark .delivery-item:hover {
  border-color: var(--muted-soft);
}

.dark .delivery-item__time {
  color: var(--on-dark-soft);
}

.dark .delivery-item__code {
  color: var(--on-dark);
}

.dark .delivery-item__payload {
  color: var(--muted);
}
</style>
