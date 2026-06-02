export const useKeyboardNavigation = () => {
  const boardStore = useBoardStore()

  const currentColumnIndex = ref(0)
  const currentCardIndex = ref(-1)

  const columns = computed(() => boardStore.columns)

  const handleKeyDown = (e: KeyboardEvent) => {
    // Don't capture when typing in inputs
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
      return
    }

    switch (e.key) {
      case 'ArrowLeft':
        e.preventDefault()
        if (currentCardIndex.value >= 0) {
          currentCardIndex.value = -1
        } else if (currentColumnIndex.value > 0) {
          currentColumnIndex.value--
        }
        break

      case 'ArrowRight':
        e.preventDefault()
        if (currentCardIndex.value >= 0) {
          currentCardIndex.value = -1
        } else if (currentColumnIndex.value < columns.value.length - 1) {
          currentColumnIndex.value++
        }
        break

      case 'ArrowDown':
        e.preventDefault()
        if (currentColumnIndex.value >= 0) {
          const col = columns.value[currentColumnIndex.value]
          if (col && currentCardIndex.value < col.issues.length - 1) {
            currentCardIndex.value++
          }
        }
        break

      case 'ArrowUp':
        e.preventDefault()
        if (currentCardIndex.value > 0) {
          currentCardIndex.value--
        } else if (currentCardIndex.value === 0) {
          currentCardIndex.value = -1
        }
        break

      case 'Enter':
        e.preventDefault()
        if (currentColumnIndex.value >= 0 && currentCardIndex.value >= 0) {
          const col = columns.value[currentColumnIndex.value]
          const issue = col?.issues[currentCardIndex.value]
          if (issue) {
            boardStore.selectIssue(issue)
          }
        }
        break

      case 'Escape':
        e.preventDefault()
        boardStore.closeDetail()
        currentCardIndex.value = -1
        currentCardIndex.value = -1
        break
    }
  }

  const initKeyboard = () => {
    if (import.meta.client) {
      window.addEventListener('keydown', handleKeyDown)
    }
  }

  const destroyKeyboard = () => {
    if (import.meta.client) {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }

  return {
    currentColumnIndex,
    currentCardIndex,
    initKeyboard,
    destroyKeyboard
  }
}
