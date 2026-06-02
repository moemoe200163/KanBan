// Dependency Graph Composable
// Handles auto-unlock when tasks move to Done

import type { Issue, IssueStatus } from '~/types'
import { COLUMN_CONFIG } from '~/types'

export const useDependencyGraph = () => {
  // Find all issues that depend on a given issue key
  const findDependents = (issues: Issue[], targetKey: string): Issue[] => {
    return issues.filter(issue =>
      issue.dependencies.includes(targetKey) && issue.status === 'blocked'
    )
  }

  // Check if all dependencies of an issue are resolved (in 'done' status)
  const canUnlock = (issue: Issue, allIssues: Issue[]): { unlocked: boolean; blockers: string[] } => {
    if (issue.dependencies.length === 0) {
      return { unlocked: true, blockers: [] }
    }

    const doneKeys = new Set(
      allIssues
        .filter(i => i.status === 'done')
        .map(i => i.key)
    )

    const blockers = issue.dependencies.filter(dep => !doneKeys.has(dep))

    return {
      unlocked: blockers.length === 0,
      blockers
    }
  }

  // Process auto-unlock when a task moves to Done
  const processUnlock = async (
    completedIssueKey: string,
    allIssues: Issue[],
    moveIssue: (issueId: string, fromStatus: IssueStatus, toStatus: IssueStatus, newIndex: number) => Promise<boolean>,
    addActivityLog: (issueId: string, entry: { type: string; message: string; actor: 'human' | 'ai' | 'system'; timestamp: string }) => void
  ): Promise<{ unlocked: string[]; failed: string[] }> => {
    const unlocked: string[] = []
    const failed: string[] = []

    // Find all blocked issues that depend on the completed issue
    const dependentIssues = findDependents(allIssues, completedIssueKey)

    console.log(`[Dependency Graph] ${completedIssueKey} completed. Found ${dependentIssues.length} dependent(s)`)

    for (const issue of dependentIssues) {
      // Check if ALL dependencies are now resolved
      const { unlocked: canBeUnlocked, blockers } = canUnlock(issue, allIssues)

      if (canBeUnlocked) {
        console.log(`[Dependency Graph] Unblocking ${issue.key} (all dependencies resolved)`)

        // Move from blocked to backlog (or in_progress if we want auto-dispatch)
        const success = await moveIssue(issue.id, 'blocked', 'backlog', 0)

        if (success) {
          unlocked.push(issue.key)
          addActivityLog(issue.id, {
            type: 'status_change',
            message: `Unblocked: ${completedIssueKey} completed. All dependencies resolved.`,
            actor: 'system',
            timestamp: new Date().toISOString()
          })

          console.log(`[Dependency Graph] ${issue.key} moved to Backlog`)
        } else {
          failed.push(issue.key)
        }
      } else {
        console.log(`[Dependency Graph] ${issue.key} still blocked by: ${blockers.join(', ')}`)
      }
    }

    return { unlocked, failed }
  }

  // Recursively check dependency chain (for deep dependency trees)
  const getDependencyChain = (issue: Issue, allIssues: Issue[], visited: Set<string> = new Set()): Issue[] => {
    if (visited.has(issue.id)) return []

    visited.add(issue.id)
    const chain: Issue[] = [issue]

    for (const depKey of issue.dependencies) {
      const depIssue = allIssues.find(i => i.key === depKey)
      if (depIssue) {
        chain.push(...getDependencyChain(depIssue, allIssues, visited))
      }
    }

    return chain
  }

  // Get topologically sorted order for dependency resolution
  const getResolutionOrder = (issues: Issue[]): Issue[] => {
    const sorted: Issue[] = []
    const visited = new Set<string>()
    const issueMap = new Map(issues.map(i => [i.key, i]))

    const visit = (issue: Issue) => {
      if (visited.has(issue.key)) return
      visited.add(issue.key)

      // Visit all dependencies first
      for (const depKey of issue.dependencies) {
        const dep = issueMap.get(depKey)
        if (dep) visit(dep)
      }

      sorted.push(issue)
    }

    for (const issue of issues) {
      if (issue.status === 'blocked') {
        visit(issue)
      }
    }

    return sorted
  }

  // Validate no circular dependencies
  const validateNoCycles = (issues: Issue[]): { hasCycle: boolean; cycle: string[] | null } => {
    const visited = new Set<string>()
    const recursionStack = new Set<string>()
    const issueMap = new Map(issues.map(i => [i.key, i]))

    const dfs = (key: string, path: string[]): string[] | null => {
      visited.add(key)
      recursionStack.add(key)

      const issue = issueMap.get(key)
      if (!issue) return null

      for (const depKey of issue.dependencies) {
        if (!visited.has(depKey)) {
          const cycle = dfs(depKey, [...path, depKey])
          if (cycle) return cycle
        } else if (recursionStack.has(depKey)) {
          return [...path, depKey]
        }
      }

      recursionStack.delete(key)
      return null
    }

    for (const issue of issues) {
      if (!visited.has(issue.key)) {
        const cycle = dfs(issue.key, [issue.key])
        if (cycle) {
          return { hasCycle: true, cycle }
        }
      }
    }

    return { hasCycle: false, cycle: null }
  }

  return {
    findDependents,
    canUnlock,
    processUnlock,
    getDependencyChain,
    getResolutionOrder,
    validateNoCycles
  }
}
