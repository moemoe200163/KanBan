// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  ssr: false,
  devtools: { enabled: true },
  experimental: { viteEnvironmentApi: true },
  modules: ['@pinia/nuxt', '@nuxtjs/tailwindcss'],
  compatibilityDate: '2025-01-01',
  srcDir: 'src/',
  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://localhost:8000/api/v1'
    }
  },
  css: ['~/assets/css/main.css'],
  tailwindcss: {
    cssPath: '~/assets/css/tailwind.css',
    configPath: 'tailwind.config.ts'
  },
  // Server-side redirects. Running these in a setup script (the old
  // ``navigateTo('/agents?tab=roles')`` approach) only fired after the
  // SPA shell was already mounted, so the browser saw a blank /agents/roles
  // URL for a frame. Nitro handles the redirect before any HTML ships.
  routeRules: {
    '/agents/roles': { redirect: '/agents?tab=roles' },
    '/lanes': { redirect: '/agents?tab=lanes' }
  }
})
