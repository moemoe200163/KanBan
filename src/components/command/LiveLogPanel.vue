<script setup lang="ts">
import { onMounted, onBeforeUnmount, computed } from 'vue'
import { useECCStreamSingleton } from '~/composables/useECCStream'
import { Wifi, WifiOff } from 'lucide-vue-next'

const props = defineProps<{ issueId: string }>()
const stream = useECCStreamSingleton()

onMounted(() => stream.startStream(props.issueId))
onBeforeUnmount(() => stream.stopStream(props.issueId))

const logs = computed(() => stream.getLogs(props.issueId))
const isLive = computed(() => stream.isConnected.value)
</script>

<template>
  <div class="live-log">
    <header class="live-log__head">
      <component :is="isLive ? Wifi : WifiOff" :size="14" />
      <span>{{ isLive ? 'Live' : 'Reconnecting...' }}</span>
    </header>
    <ul v-if="logs.length" class="live-log__list" data-testid="live-log-list">
      <li v-for="log in logs" :key="log.id" class="live-log__line">
        <span class="live-log__phase">{{ log.phase }}</span>
        <span class="live-log__content">{{ log.content }}</span>
      </li>
    </ul>
    <p v-else class="live-log__empty">Waiting for first event...</p>
  </div>
</template>

<style scoped>
.live-log {
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: var(--surface-dark);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  padding: 10px 12px;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--ink);
}
.live-log__head {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-size: 0.6875rem;
}
.live-log__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 240px;
  overflow-y: auto;
}
.live-log__line {
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 8px;
}
.live-log__phase {
  color: var(--sage);
  text-transform: uppercase;
  font-size: 0.625rem;
}
.live-log__content {
  word-break: break-word;
}
.live-log__empty {
  color: var(--muted);
  margin: 0;
}
</style>
