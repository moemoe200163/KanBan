<script setup lang="ts">
/**
 * Snake Game — Agent Run Pilot demo artifact.
 *
 * Self-contained HTML5 Canvas game. Accessible only via /games/snake
 * (NOT in sidebar). Dark theme matching DevFlow design tokens.
 */

const CELL = 20
const COLS = 20
const ROWS = 20
const INITIAL_SPEED = 150
const SPEED_INCREMENT = 2
const MIN_SPEED = 60

const canvasRef = ref<HTMLCanvasElement>()
const score = ref(0)
const highScore = ref(0)
const gameOver = ref(false)
const started = ref(false)

type Point = { x: number; y: number }
type Direction = 'up' | 'down' | 'left' | 'right'

let snake: Point[] = []
let food: Point = { x: 10, y: 10 }
let direction: Direction = 'right'
let nextDirection: Direction = 'right'
let speed = INITIAL_SPEED
let lastTime = 0
let animFrame = 0
let touchStart: { x: number; y: number } | null = null

function initGame() {
  const midX = Math.floor(COLS / 2)
  const midY = Math.floor(ROWS / 2)
  snake = [
    { x: midX, y: midY },
    { x: midX - 1, y: midY },
    { x: midX - 2, y: midY },
  ]
  direction = 'right'
  nextDirection = 'right'
  speed = INITIAL_SPEED
  score.value = 0
  gameOver.value = false
  started.value = true
  spawnFood()
}

function spawnFood() {
  let pos: Point
  do {
    pos = {
      x: Math.floor(Math.random() * COLS),
      y: Math.floor(Math.random() * ROWS),
    }
  } while (snake.some(s => s.x === pos.x && s.y === pos.y))
  food = pos
}

function tick() {
  direction = nextDirection
  const head = { ...snake[0] }

  switch (direction) {
    case 'up': head.y--; break
    case 'down': head.y++; break
    case 'left': head.x--; break
    case 'right': head.x++; break
  }

  // Wall collision
  if (head.x < 0 || head.x >= COLS || head.y < 0 || head.y >= ROWS) {
    endGame()
    return
  }

  // Self collision
  if (snake.some(s => s.x === head.x && s.y === head.y)) {
    endGame()
    return
  }

  snake.unshift(head)

  // Eat food
  if (head.x === food.x && head.y === food.y) {
    score.value++
    if (score.value > highScore.value) highScore.value = score.value
    speed = Math.max(MIN_SPEED, speed - SPEED_INCREMENT)
    spawnFood()
  } else {
    snake.pop()
  }
}

function endGame() {
  gameOver.value = true
  started.value = false
  cancelAnimationFrame(animFrame)
}

function gameLoop(time: number) {
  if (gameOver.value) return
  animFrame = requestAnimationFrame(gameLoop)
  if (time - lastTime < speed) return
  lastTime = time
  tick()
  draw()
}

function draw() {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const w = canvas.width
  const h = canvas.height
  const cellW = w / COLS
  const cellH = h / ROWS

  // Background
  ctx.fillStyle = '#181715'
  ctx.fillRect(0, 0, w, h)

  // Grid lines (subtle)
  ctx.strokeStyle = '#252320'
  ctx.lineWidth = 0.5
  for (let x = 0; x <= COLS; x++) {
    ctx.beginPath()
    ctx.moveTo(x * cellW, 0)
    ctx.lineTo(x * cellW, h)
    ctx.stroke()
  }
  for (let y = 0; y <= ROWS; y++) {
    ctx.beginPath()
    ctx.moveTo(0, y * cellH)
    ctx.lineTo(w, y * cellH)
    ctx.stroke()
  }

  // Food
  ctx.fillStyle = '#cc785c'
  ctx.beginPath()
  ctx.arc(
    food.x * cellW + cellW / 2,
    food.y * cellH + cellH / 2,
    cellW / 2 - 2,
    0,
    Math.PI * 2,
  )
  ctx.fill()

  // Snake
  snake.forEach((seg, i) => {
    const alpha = 1 - (i / snake.length) * 0.5
    ctx.fillStyle = i === 0
      ? '#e8a888'
      : `rgba(204, 120, 92, ${alpha})`
    ctx.fillRect(
      seg.x * cellW + 1,
      seg.y * cellH + 1,
      cellW - 2,
      cellH - 2,
    )
    // Rounded corners for head
    if (i === 0) {
      ctx.fillStyle = '#181715'
      // eyes
      const eyeSize = 2
      let ex1: number, ey1: number, ex2: number, ey2: number
      switch (direction) {
        case 'right':
          ex1 = seg.x * cellW + cellW - 5; ey1 = seg.y * cellH + 4
          ex2 = seg.x * cellW + cellW - 5; ey2 = seg.y * cellH + cellH - 6
          break
        case 'left':
          ex1 = seg.x * cellW + 3; ey1 = seg.y * cellH + 4
          ex2 = seg.x * cellW + 3; ey2 = seg.y * cellH + cellH - 6
          break
        case 'up':
          ex1 = seg.x * cellW + 4; ey1 = seg.y * cellH + 3
          ex2 = seg.x * cellW + cellW - 6; ey2 = seg.y * cellH + 3
          break
        default: // down
          ex1 = seg.x * cellW + 4; ey1 = seg.y * cellH + cellH - 5
          ex2 = seg.x * cellW + cellW - 6; ey2 = seg.y * cellH + cellH - 5
          break
      }
      ctx.fillRect(ex1, ey1, eyeSize, eyeSize)
      ctx.fillRect(ex2, ey2, eyeSize, eyeSize)
    }
  })
}

function startGame() {
  initGame()
  lastTime = 0
  animFrame = requestAnimationFrame(gameLoop)
}

function handleKey(e: KeyboardEvent) {
  if (gameOver.value && e.code === 'Space') {
    startGame()
    return
  }
  if (!started.value) return

  const keyMap: Record<string, Direction> = {
    ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right',
    KeyW: 'up', KeyS: 'down', KeyA: 'left', KeyD: 'right',
  }
  const dir = keyMap[e.code]
  if (!dir) return
  e.preventDefault()

  // Prevent 180-degree turn
  const opposites: Record<Direction, Direction> = {
    up: 'down', down: 'up', left: 'right', right: 'left',
  }
  if (opposites[dir] !== direction) {
    nextDirection = dir
  }
}

function handleTouchStart(e: TouchEvent) {
  const t = e.touches[0]
  touchStart = { x: t.clientX, y: t.clientY }
}

function handleTouchEnd(e: TouchEvent) {
  if (!touchStart || !started.value) return
  const t = e.changedTouches[0]
  const dx = t.clientX - touchStart.x
  const dy = t.clientY - touchStart.y
  touchStart = null

  const minSwipe = 30
  if (Math.abs(dx) < minSwipe && Math.abs(dy) < minSwipe) return

  let dir: Direction
  if (Math.abs(dx) > Math.abs(dy)) {
    dir = dx > 0 ? 'right' : 'left'
  } else {
    dir = dy > 0 ? 'down' : 'up'
  }

  const opposites: Record<Direction, Direction> = {
    up: 'down', down: 'up', left: 'right', right: 'left',
  }
  if (opposites[dir] !== direction) {
    nextDirection = dir
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKey)
  // Draw initial state
  const canvas = canvasRef.value
  if (canvas) {
    const ctx = canvas.getContext('2d')
    if (ctx) {
      ctx.fillStyle = '#181715'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.fillStyle = '#cc785c'
      ctx.font = '14px monospace'
      ctx.textAlign = 'center'
      ctx.fillText('Press SPACE to start', canvas.width / 2, canvas.height / 2)
    }
  }
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKey)
  cancelAnimationFrame(animFrame)
})
</script>

<template>
  <div class="snake-page">
    <div class="snake-header">
      <h1>Snake</h1>
      <div class="snake-scores">
        <span class="score">Score: {{ score }}</span>
        <span class="score score--hi">Best: {{ highScore }}</span>
      </div>
    </div>

    <div class="snake-canvas-wrap">
      <canvas
        ref="canvasRef"
        :width="COLS * CELL"
        :height="ROWS * CELL"
        class="snake-canvas"
        @touchstart.prevent="handleTouchStart"
        @touchend.prevent="handleTouchEnd"
      />

      <!-- Overlay -->
      <div v-if="!started" class="snake-overlay" @click="startGame">
        <template v-if="gameOver">
          <p class="overlay-title">Game Over</p>
          <p class="overlay-sub">Score: {{ score }}</p>
          <p class="overlay-hint">Press SPACE or tap to restart</p>
        </template>
        <template v-else>
          <p class="overlay-title">Snake</p>
          <p class="overlay-hint">Press SPACE or tap to start</p>
          <p class="overlay-controls">Arrow keys / WASD / Swipe</p>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.snake-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  min-height: 100vh;
  padding: 24px;
  background: var(--surface-dark, #181715);
  color: var(--text, #e8e4de);
}

.snake-header {
  display: flex;
  align-items: center;
  gap: 24px;
}

.snake-header h1 {
  font-family: var(--font-display, monospace);
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--primary, #cc785c);
}

.snake-scores {
  display: flex;
  gap: 16px;
}

.score {
  font-family: var(--font-mono, monospace);
  font-size: 0.875rem;
  color: #999;
}

.score--hi {
  color: var(--primary, #cc785c);
}

.snake-canvas-wrap {
  position: relative;
  border: 1px solid #333;
  border-radius: 8px;
  overflow: hidden;
}

.snake-canvas {
  display: block;
  background: #181715;
}

.snake-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: rgba(24, 23, 21, 0.85);
  cursor: pointer;
}

.overlay-title {
  font-family: var(--font-display, monospace);
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--primary, #cc785c);
}

.overlay-sub {
  font-family: var(--font-mono, monospace);
  font-size: 1rem;
  color: #ccc;
}

.overlay-hint {
  font-size: 0.8125rem;
  color: #888;
}

.overlay-controls {
  font-size: 0.6875rem;
  color: #666;
  margin-top: 4px;
}
</style>
