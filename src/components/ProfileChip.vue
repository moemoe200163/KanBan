<script setup lang="ts">
import { PROFILE_CONFIG } from '~/types'
import type { ECCProfile } from '~/types'

interface Props {
  profile: ECCProfile
  size?: 'sm' | 'md'
}

const props = withDefaults(defineProps<Props>(), {
  size: 'md'
})

const config = computed(() => PROFILE_CONFIG[props.profile])

const profileIcons: Record<ECCProfile, string> = {
  frontend: '🎨',
  backend: '⚙️',
  security: '🔒',
  refactor: '🔧',
  debug: '🔍',
  general: '📋'
}
</script>

<template>
  <span
    :class="['profile-chip', `profile-chip--${props.size}`]"
    :style="{
      backgroundColor: `${config.color}20`,
      color: config.color,
      borderColor: `${config.color}40`
    }"
    :title="`Profile: ${config.label}`"
  >
    <span class="profile-chip__icon">{{ profileIcons[props.profile] }}</span>
    <span class="profile-chip__label">{{ config.label }}</span>
  </span>
</template>

<style scoped>
.profile-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-family: var(--font-body);
  font-weight: 500;
  border: 1px solid;
  border-radius: var(--radius-sm);
}

.profile-chip--sm {
  padding: 1px var(--space-2);
  font-size: 0.625rem;
}

.profile-chip--md {
  padding: 2px var(--space-2);
  font-size: var(--text-xs);
}

.profile-chip__icon {
  font-size: 0.75em;
}

.profile-chip__label {
  text-transform: capitalize;
}
</style>