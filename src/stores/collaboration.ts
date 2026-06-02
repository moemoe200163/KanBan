import { defineStore } from 'pinia'

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

interface Comment {
  id: string
  issueId: string
  author: string
  authorAvatar: string
  content: string
  createdAt: string
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
  comments: Record<string, Comment[]>
  activeWebhooks: Webhook[]
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
  },
  {
    id: 'act4',
    actor: 'Alex Chen',
    action: 'assigned',
    target: 'DEV-003 to themselves',
    timestamp: new Date(Date.now() - 45 * 60 * 1000).toISOString()
  },
  {
    id: 'act5',
    actor: 'Jamie Rivera',
    action: 'unblocked',
    target: 'DEV-007',
    timestamp: new Date(Date.now() - 60 * 60 * 1000).toISOString()
  }
]

const generateMockComments = (): Record<string, Comment[]> => ({
  'DEV-002': [
    {
      id: 'c1',
      issueId: 'DEV-002',
      author: 'Alex Chen',
      authorAvatar: 'https://i.pravatar.cc/150?u=alex',
      content: 'Looking great! Consider adding keyboard hints for screen reader users.',
      createdAt: new Date(Date.now() - 20 * 60 * 1000).toISOString()
    },
    {
      id: 'c2',
      issueId: 'DEV-002',
      author: 'Sam Taylor',
      authorAvatar: 'https://i.pravatar.cc/150?u=sam',
      content: 'The drag-and-drop feels smooth. Good work on the accessibility attributes.',
      createdAt: new Date(Date.now() - 10 * 60 * 1000).toISOString()
    }
  ],
  'DEV-001': [
    {
      id: 'c3',
      issueId: 'DEV-001',
      author: 'Jamie Rivera',
      authorAvatar: 'https://i.pravatar.cc/150?u=jamie',
      content: 'Auth flow works well. The session handling is solid.',
      createdAt: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString()
    }
  ]
})

export const useCollaborationStore = defineStore('collaboration', {
  state: (): CollaborationState => ({
    members: [],
    activities: [],
    comments: {},
    activeWebhooks: []
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

    getCommentsByIssue: (state) => (issueId: string): Comment[] => {
      return state.comments[issueId] || []
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
    async fetchMembers() {
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 300))
      this.members = generateMockMembers()
    },

    async fetchActivities() {
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 200))
      this.activities = generateMockActivities()
    },

    async fetchComments(issueId: string) {
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 150))
      const mockComments = generateMockComments()
      this.comments = { ...this.comments, [issueId]: mockComments[issueId] || [] }
    },

    addActivity(activity: Omit<ActivityItem, 'id' | 'timestamp'>) {
      const newActivity: ActivityItem = {
        id: `act_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
        actor: activity.actor,
        action: activity.action,
        target: activity.target,
        timestamp: new Date().toISOString()
      }

      // Prepend to activities (newest first)
      this.activities.unshift(newActivity)

      // Keep only the most recent 100 activities
      if (this.activities.length > 100) {
        this.activities = this.activities.slice(0, 100)
      }
    },

    addComment(issueId: string, content: string, authorInfo?: { name: string; avatar: string }) {
      const newComment: Comment = {
        id: `cmt_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
        issueId,
        author: authorInfo?.name || 'Anonymous',
        authorAvatar: authorInfo?.avatar || 'https://i.pravatar.cc/150?u=anonymous',
        content,
        createdAt: new Date().toISOString()
      }

      // Initialize comments array for issue if not exists
      if (!this.comments[issueId]) {
        this.comments[issueId] = []
      }

      this.comments[issueId].push(newComment)

      // Also add as activity
      this.addActivity({
        actor: newComment.author,
        action: 'commented on',
        target: issueId
      })

      return newComment
    },

    updateComment(issueId: string, commentId: string, content: string) {
      const comments = this.comments[issueId]
      if (!comments) return false

      const comment = comments.find(c => c.id === commentId)
      if (!comment) return false

      comment.content = content
      return true
    },

    deleteComment(issueId: string, commentId: string) {
      const comments = this.comments[issueId]
      if (!comments) return false

      const index = comments.findIndex(c => c.id === commentId)
      if (index === -1) return false

      comments.splice(index, 1)
      return true
    },

    updateMemberStatus(memberId: string, status: TeamMember['status']) {
      const member = this.members.find(m => m.id === memberId)
      if (!member) return false

      member.status = status
      member.lastSeen = new Date().toISOString()

      // Add activity for status change
      const statusLabel = status === 'online' ? 'came online' : status === 'away' ? 'went away' : 'went offline'
      this.addActivity({
        actor: member.name,
        action: statusLabel,
        target: ''
      })

      return true
    },

    updateMemberRole(memberId: string, role: string) {
      const member = this.members.find(m => m.id === memberId)
      if (!member) return false

      member.role = role
      return true
    },

    addWebhook(webhook: Omit<Webhook, 'id' | 'createdAt'>) {
      const newWebhook: Webhook = {
        id: `wh_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
        url: webhook.url,
        events: webhook.events,
        enabled: webhook.enabled,
        createdAt: new Date().toISOString()
      }

      this.activeWebhooks.push(newWebhook)
      return newWebhook
    },

    updateWebhook(webhookId: string, updates: Partial<Omit<Webhook, 'id' | 'createdAt'>>) {
      const webhook = this.activeWebhooks.find(w => w.id === webhookId)
      if (!webhook) return null

      if (updates.url !== undefined) webhook.url = updates.url
      if (updates.events !== undefined) webhook.events = updates.events
      if (updates.enabled !== undefined) webhook.enabled = updates.enabled

      return webhook
    },

    deleteWebhook(webhookId: string) {
      const index = this.activeWebhooks.findIndex(w => w.id === webhookId)
      if (index === -1) return false

      this.activeWebhooks.splice(index, 1)
      return true
    },

    toggleWebhook(webhookId: string) {
      const webhook = this.activeWebhooks.find(w => w.id === webhookId)
      if (!webhook) return null

      webhook.enabled = !webhook.enabled
      return webhook
    },

    // Real-time collaboration handlers
    handleMemberPresenceUpdate(payload: { memberId: string; status: TeamMember['status'] }) {
      this.updateMemberStatus(payload.memberId, payload.status)
    },

    handleNewActivity(payload: { actor: string; action: string; target: string }) {
      this.addActivity(payload)
    },

    handleNewComment(payload: { issueId: string; author: string; authorAvatar: string; content: string }) {
      this.addComment(payload.issueId, payload.content, {
        name: payload.author,
        avatar: payload.authorAvatar
      })
    },

    handleCommentUpdate(payload: { issueId: string; commentId: string; content: string }) {
      return this.updateComment(payload.issueId, payload.commentId, payload.content)
    },

    handleCommentDelete(payload: { issueId: string; commentId: string }) {
      return this.deleteComment(payload.issueId, payload.commentId)
    },

    // Bulk operations
    initializeCollaboration() {
      // Initialize with mock data for demo purposes
      this.members = generateMockMembers()
      this.activities = generateMockActivities()
      this.comments = generateMockComments()
    },

    clearActivities() {
      this.activities = []
    },

    clearComments(issueId?: string) {
      if (issueId) {
        delete this.comments[issueId]
      } else {
        this.comments = {}
      }
    }
  }
})