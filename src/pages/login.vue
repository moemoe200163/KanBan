<script setup lang="ts">
/**
 * /login — username + password sign-in page (Plan J).
 *
 * Calls POST /auth/token, stores the JWT in the `auth_token` cookie
 * (the same one useAuth and every store already reads), and then
 * re-fetches the user state via useAuth.fetchRole() so the rest of
 * the app picks up the new role / tenant / permissions on the next
 * render. We then route the user back to the page they came from
 * (via `?redirect=...` or the home page as a fallback).
 *
 * The page is intentionally self-contained — no sidebar, no
 * app-shell chrome — so it works as a deep link even when the
 * other tabs are misconfigured.
 */
import { useAuth } from '~/composables/useAuth'
import { Shield, Loader2, LogIn, AlertCircle } from 'lucide-vue-next'

definePageMeta({
  // Strip the app shell so /login is a true sign-in page even
  // when the rest of the SPA hasn't loaded its auth state.
  layout: false,
})

const config = useRuntimeConfig()
const route = useRoute()
const router = useRouter()
const { fetchRole, isAuthenticated } = useAuth()

const username = ref('')
const password = ref('')
const isSubmitting = ref(false)
const error = ref<string | null>(null)

// If the visitor is already signed in, bounce straight to the
// page they were heading to. Without this guard, hitting /login
// while authenticated would just re-render the form.
onMounted(async () => {
  await fetchRole()
  if (isAuthenticated.value) {
    void router.replace(resolveRedirect())
  }
})

const resolveRedirect = (): string => {
  const raw = route.query.redirect
  if (typeof raw === 'string' && raw && raw.startsWith('/')) return raw
  return '/'
}

const submit = async () => {
  if (isSubmitting.value) return
  if (!username.value.trim() || !password.value) {
    error.value = 'Username and password are required.'
    return
  }
  error.value = null
  isSubmitting.value = true
  try {
    const res = await fetch(`${config.public.apiBase}/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: username.value.trim(),
        password: password.value,
      }),
    })
    if (!res.ok) {
      // 401 surfaces a friendly message; anything else gets the
      // raw status so the user can see what's actually wrong.
      if (res.status === 401) {
        error.value = 'Invalid username or password.'
      } else {
        error.value = `Login failed (HTTP ${res.status}).`
      }
      return
    }
    const data = (await res.json()) as { access_token?: string }
    if (!data.access_token) {
      error.value = 'Server did not return an access token.'
      return
    }
    // Persist the token. The cookie is read by useAuth and every
    // store action that talks to /api/v1 — keeping the name
    // consistent is what makes a hard reload of the SPA stay
    // signed in.
    const cookie = useCookie<string | null>('auth_token', {
      maxAge: 60 * 60 * 24,
      sameSite: 'lax',
    })
    cookie.value = data.access_token

    // Refresh the user object so role / tenant / permissions
    // are accurate before we navigate away.
    await fetchRole()
    await router.replace(resolveRedirect())
  } catch (e: any) {
    error.value = e?.message || 'Network error during login.'
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-card">
      <header class="login-card__header">
        <Shield :size="22" class="login-card__icon" />
        <h1>Sign in to DevFlow</h1>
        <p>Workspace, boards, and ECC dispatch — all behind your tenant.</p>
      </header>

      <form class="login-form" @submit.prevent="submit">
        <div class="field">
          <label for="login-username">Username</label>
          <input
            id="login-username"
            v-model="username"
            type="text"
            autocomplete="username"
            class="field__input"
            :disabled="isSubmitting"
            required
          />
        </div>

        <div class="field">
          <label for="login-password">Password</label>
          <input
            id="login-password"
            v-model="password"
            type="password"
            autocomplete="current-password"
            class="field__input"
            :disabled="isSubmitting"
            required
          />
        </div>

        <div v-if="error" class="login-error" role="alert">
          <AlertCircle :size="14" />
          <span>{{ error }}</span>
        </div>

        <button type="submit" class="login-submit" :disabled="isSubmitting">
          <Loader2 v-if="isSubmitting" :size="16" class="spin" />
          <LogIn v-else :size="16" />
          {{ isSubmitting ? 'Signing in…' : 'Sign in' }}
        </button>
      </form>

      <footer class="login-card__footer">
        <p>Dev seed accounts: <code>admin@default</code> / <code>ops@default</code> / <code>user@default</code> — password <code>dev123!</code></p>
      </footer>
    </section>
  </main>
</template>

<style scoped>
.login-page {
  display: grid;
  place-items: center;
  min-height: 100dvh;
  padding: 24px;
  background:
    radial-gradient(circle at top left, rgba(204, 120, 92, 0.10), transparent 30rem),
    var(--canvas);
  color: var(--ink);
}

.login-card {
  display: flex; flex-direction: column; gap: 22px;
  width: 100%; max-width: 420px;
  padding: 28px;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 16px;
  box-shadow: 0 18px 40px -16px rgba(20, 20, 19, 0.18);
}

.login-card__header { display: flex; flex-direction: column; gap: 4px; }
.login-card__icon { color: var(--primary); }
.login-card__header h1 {
  margin: 4px 0 0; font-family: var(--font-display);
  font-size: 1.35rem; font-weight: 700; color: var(--ink);
}
.login-card__header p {
  margin: 0; color: var(--muted); font-size: 0.875rem;
}

.login-form { display: flex; flex-direction: column; gap: 14px; }
.field { display: flex; flex-direction: column; gap: 4px; }
.field label { font-size: 0.8125rem; font-weight: 600; color: var(--ink); }
.field__input {
  padding: 9px 12px; border-radius: 8px; border: 1px solid var(--hairline);
  background: var(--surface-soft); color: var(--ink);
  font-size: 0.9375rem; font-family: var(--font-body);
}
.field__input:focus { outline: none; border-color: var(--primary); }
.field__input:disabled { opacity: 0.6; cursor: not-allowed; }

.login-error {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 12px; border-radius: 8px;
  background: color-mix(in srgb, var(--clay-red) 10%, transparent);
  color: var(--clay-red); font-size: 0.85rem;
}

.login-submit {
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  padding: 10px 16px; border-radius: 10px; border: none;
  background: var(--primary); color: var(--on-primary);
  font-size: 0.9375rem; font-weight: 600; cursor: pointer;
  transition: opacity 150ms;
}
.login-submit:hover { opacity: 0.92; }
.login-submit:disabled { opacity: 0.6; cursor: not-allowed; }

.login-card__footer {
  border-top: 1px solid var(--hairline); padding-top: 14px;
  color: var(--muted); font-size: 0.75rem;
}
.login-card__footer p { margin: 0; line-height: 1.5; }
.login-card__footer code {
  font-family: var(--font-mono); color: var(--ink);
  background: var(--surface-soft); padding: 1px 4px; border-radius: 4px;
}

.spin { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
</style>
