<script setup lang="ts">
interface Props {
  name: string | null
  avatarUrl: string | null
  size?: 'sm' | 'md' | 'lg'
}

const props = withDefaults(defineProps<Props>(), {
  size: 'md'
})

const initials = computed(() => {
  if (!props.name) return '?'
  return props.name
    .split(' ')
    .map(n => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)
})

const sizeMap = { sm: 24, md: 32, lg: 40 }
const fontSize = computed(() => sizeMap[props.size] * 0.4)
</script>

<template>
  <div
    :class="['avatar', `avatar--${props.size}`]"
    :title="props.name || 'Unassigned'"
  >
    <img
      v-if="props.avatarUrl"
      :src="props.avatarUrl"
      :alt="props.name || 'User'"
      class="avatar__image"
    />
    <span v-else class="avatar__initials" :style="{ fontSize: `${fontSize}px` }">
      {{ initials }}
    </span>
  </div>
</template>

<style scoped>
.avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--surface-card);
  border: 2px solid var(--hairline);
  overflow: hidden;
  flex-shrink: 0;
}

.avatar--sm {
  width: 24px;
  height: 24px;
}

.avatar--md {
  width: 32px;
  height: 32px;
}

.avatar--lg {
  width: 40px;
  height: 40px;
}

.avatar__image {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar__initials {
  font-family: var(--font-display);
  font-weight: 600;
  color: var(--muted);
}
</style>