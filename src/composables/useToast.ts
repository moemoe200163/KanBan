export interface Toast {
  id: string
  message: string
  undoAction?: () => void
  undoLabel?: string
  durationMs?: number
}

const toasts = ref<Toast[]>([])
const timers = new Map<string, ReturnType<typeof setTimeout>>()

export function useToast() {
  const add = (message: string, undoAction?: () => void, undoLabel = 'Undo', durationMs = 3000) => {
    const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2)}`
    toasts.value.push({ id, message, undoAction, undoLabel, durationMs })

    if (durationMs > 0) {
      const timer = setTimeout(() => {
        remove(id)
      }, durationMs)
      timers.set(id, timer)
    }

    return id
  }

  const remove = (id: string) => {
    const timer = timers.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.delete(id)
    }
    const idx = toasts.value.findIndex(t => t.id === id)
    if (idx !== -1) toasts.value.splice(idx, 1)
  }

  const clear = () => {
    timers.forEach(timer => clearTimeout(timer))
    timers.clear()
    toasts.value = []
  }

  return { toasts: readonly(toasts), add, remove, clear }
}