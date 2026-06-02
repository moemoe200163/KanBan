# DevFlow — ECC-Driven Agent Orchestration System

> **Revised Architecture** — Align with Expressive Code Commits as the agent execution layer

---

## Historical Context — Archive

This document describes the **original/planned architecture direction** as of the ECC-aligned redesign (v2).

| File | Purpose | Status |
|------|---------|--------|
| **PLAN.md** | Architecture direction, component structure, implementation phases | Historical - contains original architectural decisions |
| **SPEC.md** | Historical v1 product spec (AI-driven Jira clone concept) | Archive - outdated |
| **Design.md** | Current source of truth for design decisions, visual system, and implementation guidance | **Active** |

**When documents conflict:**
- For architecture/technical direction: follow PLAN.md
- For design/visual/UI matters: follow **Design.md** (current)

---

## 1. Core Concept

DevFlow is no longer a "Jira clone with AI features." It is a **Control Plane for ECC (Expressive Code Commits)** — a system that maps human-readable issue states to ECC terminal commands, leverages ECC's built-in memory/parallel execution/quality gates, and orchestrates multi-agent workflows through existing ECC capabilities.

**Philosophy**: Don't build agent infrastructure. **Bridge to ECC's agent infrastructure.**

---

## 2. Architecture Shift

### Before (DevFlow v1 — Rejected)
```
Nuxt 3 → FastAPI → Celery → LLM API
         ↓
    Custom Memory System (reinvented)
    Custom Parallel Execution (reinvented)
    Custom Quality Gates (reinvented)
```

### After (DevFlow v2 — ECC-Aligned)
```
Nuxt 4 → FastAPI (Control Plane) → ECC Skills/Profiles
         ↓                           ↓
    Issue State Changes         ┌──► Claude Code Harness
    trigger ECC Commands        ├──► Codex Harness
    (e.g., /loop-start)         ├──► Cursor Harness
                                 └──► OpenCode/Gemini Harness

    ECC handles: Memory, Parallel Execution, Quality Gates
```

---

## 3. Design Language — Earth Tone Palette

### Color System

```css
:root {
  /* Earth Tones — Warm Natural */
  --earth-900: #1A1614;      /* Deep soil — primary bg */
  --earth-800: #2D2620;      /* Dark bark — card surfaces */
  --earth-700: #3D3428;      /* Warm brown — elevated */
  --earth-600: #524636;      /* Medium brown — borders */
  --earth-500: #7A6552;      /* Tan — muted elements */

  /* Accent — Terracotta */
  --accent: #C67B4E;         /* Primary action */
  --accent-hover: #D4896A;
  --accent-muted: #A8633F;

  /* Accent — Sage Green */
  --sage: #7D9E7D;           /* Success/Done */
  --sage-muted: #5C7A5C;

  /* Accent — Dusty Blue */
  --dusty-blue: #6B8BA4;     /* Human Review */
  --dusty-blue-muted: #4A6577;

  /* Accent — Amber (Blocked/Warning) */
  --amber: #D4A84B;          /* Blocked/Caution */
  --amber-muted: #B8923F;

  /* Accent — Clay Red (Critical) */
  --clay-red: #B85C4D;       /* Critical/Error */

  /* Text */
  --text-primary: #F5F0E8;   /* Warm white */
  --text-secondary: #B8AFA3;
  --text-tertiary: #8C8279;
  --text-muted: #5C554D;

  /* Borders */
  --border-subtle: rgba(122, 101, 82, 0.3);
  --border-default: rgba(122, 101, 82, 0.5);
  --border-strong: rgba(122, 101, 82, 0.8);
}
```

### Typography

```css
--font-display: 'Outfit', sans-serif;  /* Modern, warm */
--font-body: 'Source Sans 3', sans-serif;
--font-mono: 'JetBrains Mono', monospace;
```

### Motion

- Natural, organic easing: `cubic-bezier(0.25, 0.1, 0.25, 1)`
- Subtle, grounded transitions (200-300ms)
- No aggressive animations — calm and professional

---

## 4. ECC Integration Points

### 4.1 Command Mapping

| Board Action | ECC Command | Description |
|--------------|-------------|-------------|
| Card → In Progress | `/loop-start --profile={profile}` | Start AI execution loop |
| Card → Blocked | `/harness-pause` | Pause current agent |
| Card → Human Review | `/quality-gate --verify` | Run quality checks |
| Card → Done | `/release-ready --merge` | Proceed to merge |
| Card → Backlog | `/loop-reset` | Reset to initial state |

### 4.2 ECC Skill Mapping

Each Issue carries a `profile` field that maps to ECC skill profiles:

| Profile | ECC Skills | Use Case |
|---------|------------|----------|
| `frontend` | vue, nuxt, css, testing, a11y | UI development |
| `backend` | fastapi, prisma, docker, postgresql | Server-side |
| `security` | agent-shield, vuln-scan, auth-audit | Security work |
| `refactor` | ast-parser, complexity-check, test coverage | Code improvement |
| `debug` | error-trace, log-analysis, reproduce | Issue investigation |

### 4.3 Multi-Harness Support

```typescript
interface HarnessConfig {
  type: 'claude-code' | 'codex' | 'cursor' | 'opencode' | 'gemini'
  endpoint: string
  credentials: Record<string, string>
  defaultProfile: string
}
```

The board can dispatch to different agent environments while maintaining output parity through ECC's cross-harness alignment.

---

## 5. Data Model (Prisma)

```prisma
model Issue {
  id           String   @id @default(cuid())
  key          String   @unique  // "DEV-142"
  title        String
  description   String?
  status       IssueStatus @default(backlog)
  priority     Priority @default(medium)

  // ECC Integration
  profile      String?  // "frontend", "backend", "security"
  eccCommand   String?  // Custom command override
  harnessType  String?  // Target harness: "claude-code", "codex"
  memoryRef    String?  // Reference to ECC memory entry

  // Relationships
  dependencies Issue[]  @relation("IssueDependencies")
  dependentOn  Issue[]  @relation("IssueDependencies")
  labels       Label[]
  assigneeId   String?
  assignee     User?    @relation(fields: [assigneeId], references: [id])

  // Tracking
  prUrl        String?
  ciStatus     String?
  aiAgentId    String?
  activityLog  Activity[]
  createdAt    DateTime @default(now())
  updatedAt    DateTime @updatedAt
}

model User {
  id        String  @id @default(cuid())
  name      String
  email     String  @unique
  avatarUrl String?
  issues    Issue[]
}

model Label {
  id     String  @id @default(cuid())
  name   String
  color  String
  issues Issue[]
}

model Activity {
  id        String   @id @default(cuid())
  issueId   String
  issue     Issue    @relation(fields: [issueId], references: [id])
  type      String   // "status_change", "ai_started", "pr_created"
  message   String
  actor     String   // "human" | "ai" | "system"
  metadata  Json?
  createdAt DateTime @default(now())
}

enum IssueStatus {
  backlog
  in_progress
  blocked
  human_review
  done
}

enum Priority {
  critical
  high
  medium
  low
}
```

---

## 6. System Components

### 6.1 Nuxt 4 Frontend (Control Plane UI)

```
frontend/
├── app.vue
├── pages/
│   └── board.vue              # Main Kanban interface
├── components/
│   ├── board/
│   │   ├── KanbanBoard.vue    # Board container
│   │   ├── KanbanColumn.vue   # Status column
│   │   ├── IssueCard.vue      # Draggable card
│   │   └── IssueDetail.vue    # Slide-over panel
│   ├── indicators/
│   │   ├── AIStatusBadge.vue  # ECC agent status
│   │   ├── HarnessBadge.vue   # Current harness type
│   │   ├── QualityGateBadge.vue # Quality gate result
│   │   └── MemoryRefBadge.vue # ECC memory reference
│   └── common/
│       ├── StatusBadge.vue
│       ├── PriorityBadge.vue
│       └── ProfileChip.vue    # ECC profile indicator
├── composables/
│   ├── useECC.ts              # ECC command dispatcher
│   ├── useHarness.ts          # Harness configuration
│   └── useBoard.ts
├── stores/
│   └── board.ts
└── types/
    └── index.ts
```

### 6.2 FastAPI Backend (Control Plane)

```
backend/
├── app/
│   ├── main.py                # FastAPI + CORS
│   ├── api/
│   │   └── v1/
│   │       ├── board.py        # Board + Issue CRUD
│   │       ├── ecc.py          # ECC command dispatch
│   │       └── webhooks.py     # CI/Quality Gate webhooks
│   ├── core/
│   │   ├── config.py          # Harness endpoints, credentials
│   │   ├── dispatcher.py      # Maps state → ECC commands
│   │   └── memory.py          # ECC memory layer adapter
│   └── models/
│       └── schemas.py         # Pydantic models
├── prisma/
│   └── schema.prisma
└── requirements.txt
```

### 6.3 Key API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/board` | Full board state |
| PATCH | `/api/v1/issues/{id}` | Update issue (triggers ECC) |
| POST | `/api/v1/ecc/dispatch` | Direct ECC command |
| GET | `/api/v1/ecc/status` | AI agent + quality gate status |
| POST | `/api/v1/webhooks/ci` | CI status from harness |
| POST | `/api/v1/webhooks/quality-gate` | Quality gate results |
| GET | `/api/v1/harness/configs` | Available harnesses |
| PATCH | `/api/v1/harness/active` | Switch active harness |

---

## 7. State → Command Flow

```
User drags card from Backlog → In Progress
         │
         ▼
    FastAPI PATCH /api/v1/issues/{id}
         │
         ▼
    Prisma updates status
         │
         ▼
    Dispatcher checks profile:
    - profile: "frontend"
    - eccCommand: null (use default)
         │
         ▼
    Execute: `ecc /loop-start --profile=frontend --issue={key}`
         │
         ▼
    ECC starts agent loop, memory observer activates
         │
         ▼
    Agent produces PR → CI webhook fires
         │
         ▼
    Quality gate runs → auto-advance or block
         │
         ▼
    On success: Issue → Human Review (human final check)
    On block: Issue → Blocked with error context
         │
         ▼
    Human approves → /release-ready --merge
         │
         ▼
    Issue → Done, dependencies auto-unblocked
```

---

## 8. Implementation Phases

### Phase 1: Nuxt 4 Board UI
- [x] Earth tone design system
- [ ] Nuxt 4 project with TypeScript
- [ ] KanbanBoard + KanbanColumn + IssueCard
- [ ] vuedraggable integration
- [ ] IssueDetail slide-over
- [ ] AI Status + Profile indicators
- [ ] Static mock data

### Phase 2: FastAPI Control Plane
- [ ] FastAPI setup with async/await
- [ ] Prisma schema + migrations
- [ ] Board/Issue CRUD endpoints
- [ ] ECC command dispatcher
- [ ] Webhook handlers (CI, quality gate)

### Phase 3: ECC Integration
- [ ] ECC CLI wrapper in backend
- [ ] Profile → skill mapping
- [ ] Memory layer adapter
- [ ] Multi-harness support

### Phase 4: Autopilot & Quality Gates
- [ ] Release-readiness gates
- [ ] AgentShield security scan
- [ ] Benchmark optimization loop
- [ ] Cron-based autopilot scheduling

---

## 9. Key Differences from v1 Plan

| Aspect | v1 (Rejected) | v2 (ECC-Aligned) |
|--------|--------------|------------------|
| Frontend | Nuxt 3 | Nuxt 4 (ECC native support) |
| Memory | Custom AST index | ECC Observer memory |
| Task Queue | Celery + Redis | ECC parallel-execution-optimizer |
| Quality | Manual CI + human | ECC quality-gate + AgentShield |
| Agents | Single harness | Multi-harness (Claude/Codex/Cursor) |
| Design | Dark + Terracotta | Earth tones (warm browns/sage) |
| Backend Role | API server | ECC control plane |

---

## 10. Confirmation Needed

1. **Design Direction**: Earth tone palette (warm browns, sage, dusty blue) — acceptable?
2. **Nuxt 4**: ECC has dedicated support for Nuxt 4 — proceed?
3. **FastAPI as Control Plane**: Backend dispatches ECC commands, not raw LLM calls — aligned?
4. **Multi-harness**: Support for Claude Code / Codex / Cursor in same board — needed?
5. **Phase 1 Scope**: Nuxt 4 board UI with mock data — confirm?

---

## Sources
- [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md) — Design system reference