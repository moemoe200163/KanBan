<script setup lang="ts">
import { useDarkMode } from '~/composables/useDarkMode'
import { useKeyboardNavigation } from '~/composables/useKeyboardNavigation'
import { Menu } from 'lucide-vue-next'

const { isDark, initDark } = useDarkMode()
const { initKeyboard, destroyKeyboard } = useKeyboardNavigation()
const sidebarCollapsed = ref(false)
const mobileMenuOpen = ref(false)

const closeMobileMenu = () => { mobileMenuOpen.value = false }

onMounted(() => {
  initDark()
  initKeyboard()
})

onUnmounted(() => {
  destroyKeyboard()
})

useHead({
  title: 'DevFlow · AI Control Plane',
  link: [
    { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' }
  ]
})
</script>

<template>
  <div class="app-shell" :class="{ dark: isDark, 'app-shell--sidebar-collapsed': sidebarCollapsed }">
    <!-- Mobile hamburger -->
    <button class="mobile-hamburger" aria-label="Open navigation" @click="mobileMenuOpen = true">
      <Menu :size="20" />
    </button>

    <!-- Mobile backdrop -->
    <Transition name="fade">
      <div v-if="mobileMenuOpen" class="mobile-backdrop" @click="closeMobileMenu" />
    </Transition>

    <!-- Sidebar: drawer on mobile, inline otherwise -->
    <div class="sidebar-wrap" :class="{ 'sidebar-wrap--mobile-open': mobileMenuOpen }">
      <Sidebar @collapsed="sidebarCollapsed = $event" @navigate="closeMobileMenu" />
    </div>

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
  .app-shell--sidebar-collapsed {
    --sidebar-w: 0px;
  }
}

/* Mobile hamburger button */
.mobile-hamburger {
  display: none;
  position: fixed;
  top: 14px;
  left: 14px;
  z-index: 130;
  width: 40px;
  height: 40px;
  align-items: center;
  justify-content: center;
  color: var(--ink);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}

/* Mobile backdrop */
.mobile-backdrop {
  display: none;
  position: fixed;
  inset: 0;
  z-index: 120;
  background: rgba(20, 20, 19, 0.42);
  backdrop-filter: blur(3px);
}

/* Sidebar wrapper for mobile drawer */
.sidebar-wrap {
  position: relative;
}

@media (max-width: 640px) {
  .mobile-hamburger {
    display: grid;
  }

  .mobile-backdrop {
    display: block;
  }

  .app-shell {
    --sidebar-w: 0px;
    grid-template-columns: minmax(0, auto) minmax(0, 1fr);
  }

  .sidebar-wrap {
    position: fixed;
    top: 0;
    left: 0;
    z-index: 125;
    height: 100dvh;
    transform: translateX(-100%);
    transition: transform 280ms cubic-bezier(0.16, 1, 0.3, 1);
  }

  .sidebar-wrap--mobile-open {
    transform: translateX(0);
  }
}
</style>
