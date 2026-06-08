<script setup lang="ts">
import { useDarkMode } from '~/composables/useDarkMode'
import { useKeyboardNavigation } from '~/composables/useKeyboardNavigation'

const { isDark, initDark } = useDarkMode()
const { initKeyboard, destroyKeyboard } = useKeyboardNavigation()
const sidebarCollapsed = ref(false)

onMounted(() => {
  initDark()
  initKeyboard()
})

onUnmounted(() => {
  destroyKeyboard()
})
</script>

<template>
  <div class="app-shell" :class="{ dark: isDark, 'app-shell--sidebar-collapsed': sidebarCollapsed }">
    <Sidebar @collapsed="sidebarCollapsed = $event" />
    <main class="app-shell__main">
      <NuxtPage />
    </main>
  </div>
</template>

<style>
.app-shell {
  --sidebar-w: 260px;
  display: grid;
  grid-template-columns: var(--sidebar-w) minmax(0, 1fr);
  height: 100dvh;
  background:
    radial-gradient(circle at top left, rgba(204, 120, 92, 0.08), transparent 30rem),
    var(--canvas);
  color: var(--ink);
}

.app-shell--sidebar-collapsed {
  --sidebar-w: 64px;
}

.app-shell__main {
  min-width: 0;
  min-height: 0;
  height: 100dvh;
  overflow: hidden;
}

@media (max-width: 920px) {
  .app-shell {
    --sidebar-w: 64px;
  }
  .app-shell--sidebar-collapsed {
    --sidebar-w: 64px;
  }
}

@media (max-width: 640px) {
  .app-shell {
    --sidebar-w: 0px;
    grid-template-columns: minmax(0, auto) minmax(0, 1fr);
  }
  .app-shell--sidebar-collapsed {
    --sidebar-w: 0px;
  }
}
</style>
