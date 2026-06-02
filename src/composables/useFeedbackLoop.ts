// Feedback Loop Composable
// Handles Reject & Loop Back: captures review comments, injects as context, re-triggers AI

import type { Issue, IssueStatus } from '~/types'
import { COLUMN_CONFIG } from '~/types'

interface ReviewFeedback {
  issueId: string
  comments: string[]
  decision: 'reject' | 'request_changes'
  timestamp: string
}

export const useFeedbackLoop = () => {
  // Process reject decision and re-trigger AI with context
  const processReject = async (
    issue: Issue,
    comments: string[],
    dispatchAI: (issue: Issue) => void,
    moveIssue: (issueId: string, fromStatus: IssueStatus, toStatus: IssueStatus, newIndex: number) => Promise<boolean>
  ): Promise<{ success: boolean; message: string }> => {
    if (!comments.length) {
      return { success: false, message: 'No review comments provided' }
    }

    // Build context from review comments
    const contextInjection = buildContextInjection(issue, comments)

    console.log(`[Feedback Loop] Processing reject for ${issue.key}`)
    console.log(`[Feedback Loop] Context injection: ${contextInjection}`)

    // 1. Add activity log entry for rejection
    const rejectionEntry = {
      id: `a${Date.now()}`,
      type: 'status_change' as const,
      message: `Rejected: ${comments.length} comment(s) received. Re-triggering AI with feedback context.`,
      actor: 'human' as const,
      timestamp: new Date().toISOString()
    }

    // 2. Move issue back to In Progress (from human_review)
    const moveSuccess = await moveIssue(
      issue.id,
      issue.status,
      'in_progress',
      0
    )

    if (!moveSuccess) {
      return { success: false, message: 'Failed to move issue back to In Progress' }
    }

    // 3. Add feedback context to issue (would be stored in backend)
    // In real implementation, this would call:
    // await $fetch('/api/v1/issues/${issue.id}/feedback', {
    //   method: 'POST',
    //   body: { comments, contextInjection }
    // })

    console.log(`[Feedback Loop] ${issue.key} moved to In Progress with feedback context`)
    console.log(`[Feedback Loop] Context: ${contextInjection}`)

    // 4. Simulate dispatching AI with feedback
    setTimeout(() => {
      dispatchAI(issue)
    }, 500)

    return {
      success: true,
      message: `Feedback loop initiated. ${comments.length} comment(s) injected as context.`
    }
  }

  // Build context injection string from review comments
  const buildContextInjection = (issue: Issue, comments: string[]): string => {
    const lines = [
      `=== REJECTION FEEDBACK FOR ${issue.key} ===`,
      `Issue: ${issue.title}`,
      `Profile: ${issue.profile}`,
      '',
      '--- Review Comments ---',
      ...comments.map((c, i) => `${i + 1}. ${c}`),
      '',
      '--- Instructions ---',
      'Please address each comment above. When fixed, create a new PR and ensure all quality gates pass.',
      'Focus on: ' + comments.map(c => extractFocusArea(c)).join(', '),
      '',
      '=== END FEEDBACK ==='
    ]

    return lines.join('\n')
  }

  // Extract focus areas from comments for prioritization
  const extractFocusArea = (comment: string): string => {
    const lower = comment.toLowerCase()

    if (lower.includes('security') || lower.includes('vulnerability')) return 'security'
    if (lower.includes('performance') || lower.includes('slow')) return 'performance'
    if (lower.includes('accessibility') || lower.includes('a11y')) return 'accessibility'
    if (lower.includes('test') || lower.includes('coverage')) return 'testing'
    if (lower.includes('typo') || lower.includes('spelling')) return 'typos'
    if (lower.includes('format') || lower.includes('style') || lower.includes('lint')) return 'code-style'
    if (lower.includes('logic') || lower.includes('bug')) return 'logic-fix'

    return 'general-fix'
  }

  // Process approve decision
  const processApprove = async (
    issue: Issue
  ): Promise<{ success: boolean; message: string }> => {
    console.log(`[Feedback Loop] Processing approve for ${issue.key}`)

    // In real implementation, this would call:
    // await $fetch('/api/v1/ecc/release-ready', {
    //   method: 'POST',
    //   body: { issueId: issue.id }
    // })

    return {
      success: true,
      message: `PR approved. Ready for merge via /release-ready --merge`
    }
  }

  return {
    processReject,
    processApprove,
    buildContextInjection,
    extractFocusArea
  }
}