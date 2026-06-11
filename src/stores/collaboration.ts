import { defineStore } from 'pinia'
import type { IssueEvent, IssueComment, IssueArtifact } from '~/types'
import { authHeaders } from '~/utils/authHeaders'

interface TeamMember {
  id: string
  name: string
  avatar: string
  status: 'online' | 'away' | 'offline'
  role: string
  lastSeen: string
}

interface ActivityItem {
  id: string
  actor: string
  action: string
  target: string
  timestamp: string
}

interface Webhook {
  id: string
  url: string
  events: string[]
  enabled: boolean
  createdAt: string
}

interface CollaborationState {
  members: TeamMember[]
  activities: ActivityItem[]
  activeWebhooks: Webhook[]
  // P2: Real collaboration data from API
  eventsByIssue: Record<string, IssueEvent[]>
  commentsByIssue: Record<string, IssueComment[]>
  artifactsByIssue: Record<string, IssueArtifact[]>
  isLoadingEvents: boolean
  isLoadingComments: boolean
  isLoadingArtifacts: boolean
}

const generateMockMembers = (): TeamMember[] => [
  {
    id: 'u1',
    name: 'Alex Chen',
    avatar: 'https://i.pravatar.cc/150?u=alex',
    status: 'online',
    role: 'Backend Engineer',
    lastSeen: new Date().toISOString()
  },
  {
    id: 'u2',
    name: 'Jamie Rivera',
    avatar: 'https://i.pravatar.cc/150?u=jamie',
    status: 'online',
    role: 'Frontend Engineer',
    lastSeen: new Date().toISOString()
  },
  {
    id: 'u3',
    name: 'Sam Taylor',
    avatar: 'https://i.pravatar.cc/150?u=sam',
    status: 'away',
    role: 'DevOps Engineer',
    lastSeen: new Date(Date.now() - 15 * 60 * 1000).toISOString()
  },
  {
    id: 'u4',
    name: 'Morgan Lee',
    avatar: 'https://i.pravatar.cc/150?u=morgan',
    status: 'offline',
    role: 'Product Manager',
    lastSeen: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString()
  }
]

const generateMockActivities = (): ActivityItem[] => [
  {
    id: 'act1',
    actor: 'Alex Chen',
    action: 'moved',
    target: 'DEV-001 to Done',
    timestamp: new Date(Date.now() - 5 * 60 * 1000).toISOString()
  },
  {
    id: 'act2',
    actor: 'Jamie Rivera',
    action: 'commented on',
    target: 'DEV-002',
    timestamp: new Date(Date.now() - 12 * 60 * 1000).toISOString()
  },
  {
    id: 'act3',
    actor: 'Sam Taylor',
    action: 'created',
    target: 'DEV-009',
    timestamp: new Date(Date.now() - 30 * 60 * 1000).toISOString()
  }
]

export const useCollaborationStore = defineStore('collaboration', {
  state: (): CollaborationState => ({
    members: [],
    activities: [],
    activeWebhooks: [],
    // P2: Real collaboration data
    eventsByIssue: {},
    commentsByIssue: {},
    artifactsByIssue: {},
    isLoadingEvents: false,
    isLoadingComments: false,
    isLoadingArtifacts: false
  }),

  getters: {
    onlineMembers: (state): TeamMember[] => {
      return state.members.filter(m => m.status === 'online')
    },

    awayMembers: (state): TeamMember[] => {
      return state.members.filter(m => m.status === 'away')
    },

    offlineMembers: (state): TeamMember[] => {
      return state.members.filter(m => m.status === 'offline')
    },

    recentActivities: (state): ActivityItem[] => {
      return state.activities.slice(0, 20)
    },

    getEventsByIssue: (state) => (issueId: string): IssueEvent[] => {
      return state.eventsByIssue[issueId] || []
    },

    getCommentsByIssue: (state) => (issueId: string): IssueComment[] => {
      return state.commentsByIssue[issueId] || []
    },

    getArtifactsByIssue: (state) => (issueId: string): IssueArtifact[] => {
      return state.artifactsByIssue[issueId] || []
    },

    getMemberById: (state) => (memberId: string): TeamMember | undefined => {
      return state.members.find(m => m.id === memberId)
    },

    enabledWebhooks: (state): Webhook[] => {
      return state.activeWebhooks.filter(w => w.enabled)
    },

    totalOnlineCount: (state): number => {
      return state.members.filter(m => m.status === 'online').length
    }
  },

  actions: {
    // P2: Fetch events from API
    async fetchEvents(issueId: string) {
      this.isLoadingEvents = true
      try {
        const config = useRuntimeConfig()
        const data = await $fetch<{ events: IssueEvent[]; total: number }>(
          `${config.public.apiBase}/issues/${issueId}/events`
        )
        this.eventsByIssue[issueId] = data.events
      } catch (error) {
        console.warn('[CollaborationStore] fetchEvents failed:', error)
        this.eventsByIssue[issueId] = []
      } finally {
        this.isLoadingEvents = false
      }
    },

    // P2: Fetch comments from API
    async fetchComments(issueId: string) {
      this.isLoadingComments = true
      try {
        const config = useRuntimeConfig()
        const data = await $fetch<{ comments: IssueComment[]; total: number }>(
          `${config.public.apiBase}/issues/${issueId}/comments`
        )
        this.commentsByIssue[issueId] = data.comments
      } catch (error) {
        console.warn('[CollaborationStore] fetchComments failed:', error)
        this.commentsByIssue[issueId] = []
      } finally {
        this.isLoadingComments = false
      }
    },

    // P2: Create comment via API
    async createComment(issueId: string, body: string, authorName?: string) {
      try {
        const config = useRuntimeConfig()
        const comment = await $fetch<IssueComment>(
          `${config.public.apiBase}/issues/${issueId}/comments`,
          {
            method: 'POST',
            body: { body, authorName },
            headers: authHeaders(),
          }
        )
        // Add to local state
        if (!this.commentsByIssue[issueId]) {
          this.commentsByIssue[issueId] = []
        }
        this.commentsByIssue[issueId].push(comment)
        // Refresh events to show the comment event
        await this.fetchEvents(issueId)
        return comment
      } catch (error) {
        console.error('[CollaborationStore] createComment failed:', error)
        throw error
      }
    },

    // P2: Fetch artifacts from API
    async fetchArtifacts(issueId: string) {
      this.isLoadingArtifacts = true
      try {
        const config = useRuntimeConfig()
        const data = await $fetch<{ artifacts: IssueArtifact[]; total: number }>(
          `${config.public.apiBase}/issues/${issueId}/artifacts`
        )
        this.artifactsByIssue[issueId] = data.artifacts
      } catch (error) {
        console.warn('[CollaborationStore] fetchArtifacts failed:', error)
        this.artifactsByIssue[issueId] = []
      } finally {
        this.isLoadingArtifacts = false
      }
    },

    // P2: Create artifact via API
    async createArtifact(issueId: string, artifact: {
      title: string
      artifactType: IssueArtifact['artifactType']
      jobId?: string
      source?: string
      pathOrUrl?: string
      summary?: string
    }) {
      try {
        const config = useRuntimeConfig()
        const created = await $fetch<IssueArtifact>(
          `${config.public.apiBase}/issues/${issueId}/artifacts`,
          {
            method: 'POST',
            body: artifact,
            headers: authHeaders(),
          }
        )
        // Add to local state
        if (!this.artifactsByIssue[issueId]) {
          this.artifactsByIssue[issueId] = []
        }
        this.artifactsByIssue[issueId].push(created)
        // Refresh events
        await this.fetchEvents(issueId)
        return created
      } catch (error) {
        console.error('[CollaborationStore] createArtifact failed:', error)
        throw error
      }
    },

    // Legacy: Fetch members (still mock)
    async fetchMembers() {
      await new Promise(resolve => setTimeout(resolve, 300))
      this.members = generateMockMembers()
    },

    // Legacy: Fetch activities (still mock)
    async fetchActivities() {
      await new Promise(resolve => setTimeout(resolve, 200))
      this.activities = generateMockActivities()
    },

    addActivity(activity: Omit<ActivityItem, 'id' | 'timestamp'>) {
      const newActivity: ActivityItem = {
        id: `act_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
        actor: activity.actor,
        action: activity.action,
        target: activity.target,
        timestamp: new Date().toISOString()
      }
      this.activities.unshift(newActivity)
      if (this.activities.length > 100) {
        this.activities = this.activities.slice(0, 100)
      }
    },

    // Real-time collaboration handlers
    handleMemberPresenceUpdate(payload: { memberId: string; status: TeamMember['status'] }) {
      const member = this.members.find(m => m.id === payload.memberId)
      if (member) {
        member.status = payload.status
        member.lastSeen = new Date().toISOString()
      }
    },

    handleNewActivity(payload: { actor: string; action: string; target: string }) {
      this.addActivity(payload)
    },

    // Initialize (for demo/fallback)
    initializeCollaboration() {
      this.members = generateMockMembers()
      this.activities = generateMockActivities()
    }
  }
})
