# DevFlow — AI-Driven Jira Kanban System

> **Historical v1 Product Specification** — See Design.md for current design

---

## 1. Concept & Vision

DevFlow 是一套融合人類敏捷流程與 AI 自動化開發的看板系統。設計語言師法 Claude 的溫暖大地色系與編輯式佈局，打造專業、開發者友善的工業風格介面。系統作為 AI 代理工作流的神經中樞，讓人類專注於决策與 review，而重複性的開發任務則交由 AI 接管。

**核心感受**：精準、沉穩、可信賴。猶如一位資深工程師在黑暗中為你點亮一盞灯——不喧嘩，但足夠明亮。

---

## 2. Design Language

### Aesthetic Direction
**Claude-Inspired Editorial Dark** — 深邃的暗色介面搭配溫暖的赤陶色點綴，乾淨的編排層次，強調資訊密度與可讀性的平衡。

### Color Palette

```css
:root {
  /* Core Background */
  --bg-primary: #0D0D0F;        /* Near-black base */
  --bg-secondary: #141417;      /* Card surfaces */
  --bg-tertiary: #1C1C21;       /* Elevated elements */
  --bg-hover: #252529;          /* Hover states */

  /* Borders & Dividers */
  --border-subtle: #2A2A30;
  --border-default: #3A3A42;
  --border-strong: #4A4A55;

  /* Text Hierarchy */
  --text-primary: #FAFAFA;
  --text-secondary: #A0A0A8;
  --text-tertiary: #6B6B75;
  --text-muted: #4A4A55;

  /* Accent — Warm Terracotta */
  --accent-primary: #E07A4B;    /* Primary action */
  --accent-hover: #F0885A;      /* Accent hover */
  --accent-muted: #C4603A;      /* Accent pressed */
  --accent-subtle: rgba(224, 122, 75, 0.12);

  /* Status Colors */
  --status-todo: #6B7280;
  --status-progress: #E07A4B;
  --status-review: #A78BFA;
  --status-blocked: #EF4444;
  --status-done: #22C55E;

  /* Priority Indicators */
  --priority-critical: #EF4444;
  --priority-high: #F59E0B;
  --priority-medium: #3B82F6;
  --priority-low: #6B7280;
}
```

### Typography

```css
/* Display & Headings — JetBrains Mono */
--font-display: 'JetBrains Mono', monospace;

/* Body Text — Inter */
--font-body: 'Inter', sans-serif;

/* Scale */
--text-xs: 0.75rem;     /* 12px — metadata */
--text-sm: 0.8125rem;    /* 13px — secondary */
--text-base: 0.875rem;   /* 14px — body */
--text-lg: 1rem;         /* 16px — subheading */
--text-xl: 1.25rem;      /* 20px — heading */
--text-2xl: 1.5rem;      /* 24px — page title */
```

### Spatial System

```css
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-5: 20px;
--space-6: 24px;
--space-8: 32px;
--space-10: 40px;
--space-12: 48px;

--radius-sm: 4px;
--radius-md: 8px;
--radius-lg: 12px;
--radius-xl: 16px;
```

### Motion Philosophy

- **拖曳卡片**: `transform` + `box-shadow` 提升，200ms ease-out
- **狀態變更**: 漸變色彩過渡 300ms，配合 scale 微脈動
- **面板滑入**: 從右側 translateX，400ms cubic-bezier(0.16, 1, 0.3, 1)
- **載入骨架**: shimmer 動畫 1.5s infinite

---

## 3. Layout & Structure

### Page Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Sidebar (64px collapsed)  │  Main Board Area                  │
│  ┌──────────────────────┐  │  ┌─────────────────────────────────┤
│  │ Logo                 │  │  │ Board Header + Filters          │
│  │ Nav Items            │  │  ├─────────────────────────────────┤
│  │ - Board              │  │  │                                 │
│  │ - Backlog            │  │  │  Kanban Columns                 │
│  │ - Analytics          │  │  │  ┌────┐ ┌────┐ ┌────┐ ┌────┐  │
│  │ - Settings           │  │  │  │    │ │    │ │    │ │    │  │
│  │                      │  │  │  │    │ │    │ │    │ │    │  │
│  │ ────────────────────  │  │  │  └────┘ └────┘ └────┘ └────┘  │
│  │ AI Status Indicator   │  │  │                                 │
│  │                      │  │  │                                 │
│  └──────────────────────┘  │  └─────────────────────────────────┤
└─────────────────────────────────────────────────────────────────┘
```

### Kanban Board Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ [Search] [Filter: Status ▾] [Assignee ▾] [+ New Issue]  [🤖 AI] │
├─────────────────────────────────────────────────────────────────┤
│ BACKLOG        │ IN PROGRESS  │ BLOCKED     │ HUMAN REVIEW │ DONE │
│ ══════════════ │ ═══════════  │ ══════════  │ ════════════  │ ═══  │
│ ┌───────────┐  │ ┌─────────┐  │ ┌────────┐ │ ┌─────────┐   │ ░░░░ │
│ │ Card      │  │ │ Card    │  │ │ Card   │ │ │ Card    │   │ ░░░░ │
│ │ ───────── │  │ │ ─────── │  │ └────────┘ │ ─────── │   │ ░░░░ │
│ │ Title     │  │ │ Title   │  │             │ Title   │   │ ░░░░ │
│ │ ├ Label   │  │ │ ├ Label │  │             │ ├ Label │   │      │
│ │ │ Meta    │  │ │ │ Meta  │  │             │ │ Meta  │   │      │
│ └───────────┘  │ └─────────┘  │             └─────────┘   │      │
│                │              │                             │      │
│ [+ Add Card]   │ [+ Add Card] │ [+ Add Card]   [+ Add Card]  │      │
└─────────────────────────────────────────────────────────────────┘
```

### Issue Detail Panel (Slide-over)

```
┌────────────────────────────────────────┐
│ Issue Key   [STATUS BADGE]        [✕]  │
│ Title of the issue                    │
│ ──────────────────────────────────────  │
│ Description (Markdown)                 │
│                                        │
│ ──────────────────────────────────────  │
│ Assignee    │ Priority   │ Story Pts  │
│ Labels      │ Dependencies│ PR Link    │
│                                        │
│ ──────────────────────────────────────  │
│ Activity LOG                           │
│ - Status changed to In Progress        │
│ - AI Agent started execution            │
│ - PR created: #123                     │
└────────────────────────────────────────┘
```

---

## 4. Features & Interactions

### Core Features

1. **Kanban Board with Drag-and-Drop**
   - Columns: Backlog → In Progress → Blocked → Human Review → Done
   - Drag card between columns triggers status update webhook
   - Visual feedback: card elevates with shadow, column highlights on hover

2. **Issue Card Design**
   - Issue key (e.g., `DEV-142`) prominent display
   - Title with truncation (2 lines max)
   - Labels: colored chips with icon prefix
   - Priority indicator: left border color
   - Assignee avatar (or AI agent icon for automated tasks)
   - Story points badge
   - Dependency indicator: chain icon with count

3. **AI Agent Integration**
   - AI Status Indicator: idle / running / error
   - Card shows "🤖 AI" badge when assigned to agent
   - Drag to "In Progress" triggers AI agent dispatch

4. **Issue Detail Panel**
   - Slide-over from right, 480px width
   - Full markdown description rendering
   - Activity timeline
   - Quick actions: change status, assign, set priority

### Interaction Details

| Action | Behavior |
|--------|----------|
| Hover card | Scale 1.02, shadow elevation, border highlight |
| Drag start | Opacity 0.8, rotate 2deg, shadow deepens |
| Drag over column | Column background lightens, border glow |
| Drop card | Snap animation, status badge updates, toast notification |
| Click card | Detail panel slides in from right |
| Keyboard | `←/→` navigate columns, `Enter` open detail, `Esc` close |

### Edge Cases

- **Blocked status**: Red border, pulsing animation, shows blocker reason
- **Dependencies unmet**: Drag target disabled, tooltip "Unmet dependencies"
- **AI running**: Card shows spinner, progress indicator in detail panel
- **Conflict state**: Orange warning badge, shows conflict details

---

## 5. Component Inventory

### IssueCard
- **Default**: bg-secondary, border-subtle, text-primary title
- **Hover**: bg-hover, border-default, scale 1.02
- **Dragging**: opacity 0.85, rotate 2deg, shadow-lg
- **Blocked**: border-left red, subtle red overlay
- **AI Running**: Pulsing AI badge, spinner overlay

### Column
- **Default**: bg-primary, subtle header border
- **Drop Target Active**: bg-tertiary, accent border glow
- **Empty**: Dashed border placeholder, "Drop issues here"

### StatusBadge
- **Backlog**: gray bg, gray text
- **In Progress**: accent-primary bg, white text
- **Blocked**: red bg, white text
- **Human Review**: purple bg, white text
- **Done**: green bg, white text

### PriorityIndicator
- **Critical**: Red left border, flame icon
- **High**: Orange left border, double chevron up
- **Medium**: Blue left border, minus icon
- **Low**: Gray left border, chevron down

### Button
- **Primary**: accent-primary bg, white text, hover: accent-hover
- **Secondary**: transparent, border-default, text-secondary, hover: bg-hover
- **Ghost**: transparent, text-secondary, hover: bg-tertiary
- **Disabled**: opacity 0.5, cursor not-allowed

### AIStatusIndicator
- **Idle**: Gray dot, "AI Ready" text
- **Running**: Animated spinner, "AI Working..." text, task name
- **Error**: Red dot, "AI Error" text, hover shows error message

---

## 6. Technical Architecture

### Frontend Stack (Nuxt 3)

```
nuxt-app/
├── app.vue
├── pages/
│   └── board.vue              # Main Kanban board page
├── components/
│   ├── KanbanBoard.vue        # Board container
│   ├── KanbanColumn.vue       # Single column
│   ├── IssueCard.vue          # Draggable card
│   ├── IssueDetail.vue        # Slide-over panel
│   ├── StatusBadge.vue
│   ├── PriorityIndicator.vue
│   ├── LabelChip.vue
│   ├── AvatarStack.vue
│   ├── AIStatusIndicator.vue
│   └── common/
│       ├── Button.vue
│       ├── Input.vue
│       ├── Dropdown.vue
│       └── Toast.vue
├── composables/
│   ├── useBoard.ts            # Board state management
│   ├── useDragDrop.ts         # DnD logic
│   ├── useIssueDetail.ts      # Detail panel state
│   └── useAIStatus.ts         # AI agent status
├── stores/
│   └── board.ts               # Pinia store
├── types/
│   └── index.ts               # Shared TypeScript types
└── assets/
    └── css/
        └── main.css           # Global styles & variables
```

### Backend Stack (FastAPI)

```
backend/
├── app/
│   ├── main.py                # FastAPI app entry
│   ├── api/
│   │   ├── v1/
│   │   │   ├── board.py       # Board endpoints
│   │   │   ├── issues.py      # Issue CRUD
│   │   │   └── ai.py          # AI agent endpoints
│   ├── core/
│   │   ├── config.py          # Settings
│   │   ├── database.py        # Prisma client
│   │   └── dispatcher.py     # Task dispatcher
│   ├── models/
│   │   └── issue.py           # Pydantic models
│   └── services/
│       ├── issue_service.py
│       └── ai_service.py
├── prisma/
│   └── schema.prisma
└── requirements.txt
```

### API Design

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/board` | GET | Get board with columns and issues |
| `/api/v1/issues` | POST | Create new issue |
| `/api/v1/issues/{id}` | PATCH | Update issue (status, assignee, etc.) |
| `/api/v1/issues/{id}` | DELETE | Delete issue |
| `/api/v1/issues/{id}/move` | POST | Move issue to column (triggers AI dispatch) |
| `/api/v1/ai/status` | GET | Get AI agent status |
| `/api/v1/ai/dispatch` | POST | Manual AI dispatch |
| `/api/v1/ai/webhook/ci` | POST | CI status webhook |

### Data Models

```typescript
interface Issue {
  id: string;
  key: string;              // e.g., "DEV-142"
  title: string;
  description: string;
  status: IssueStatus;
  priority: Priority;
  labels: string[];
  assigneeId: string | null;
  storyPoints: number | null;
  dependencies: string[];    // Issue IDs
  prUrl: string | null;
  aiAgentId: string | null;
  createdAt: Date;
  updatedAt: Date;
}

type IssueStatus = 'backlog' | 'in_progress' | 'blocked' | 'human_review' | 'done';

type Priority = 'critical' | 'high' | 'medium' | 'low';
```

### OpenAPI Type Generation

- Backend defines OpenAPI spec via FastAPI
- Frontend uses `openapi-typescript` to generate TS types
- Ensures type safety between frontend and backend

---

## 7. Deployment

### Docker Compose

```yaml
services:
  nuxt:
    build: ./nuxt-app
    ports:
      - "3000:3000"
    environment:
      - NUXT_API_URL=http://fastapi:8000

  fastapi:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/devflow
      - REDIS_URL=redis://redis:6379

  db:
    image: postgres:15
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine

  celery:
    build: ./backend
    command: celery -A app.core.celery worker
    volumes:
      - ./backend:/app
```

---

## 8. Implementation Phases

### Phase 1: Core Board UI
- [x] Design system & tokens
- [ ] Nuxt 3 project setup with TypeScript
- [ ] KanbanBoard + KanbanColumn components
- [ ] IssueCard with drag-and-drop
- [ ] Pinia store for board state

### Phase 2: Issue Management
- [ ] IssueDetail slide-over panel
- [ ] CRUD operations UI
- [ ] Status transitions

### Phase 3: Backend Integration
- [ ] FastAPI setup
- [ ] Prisma schema
- [ ] API endpoints
- [ ] Real-time updates (WebSocket or SSE)

### Phase 4: AI Agent Integration
- [ ] AI status indicator
- [ ] Dispatch webhook on status change
- [ ] CI status webhook handler

### Phase 5: Automation
- [ ] Celery task queue setup
- [ ] Memory system
- [ ] Autopilot scheduling

---

## Sources
- [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md) — Design system reference