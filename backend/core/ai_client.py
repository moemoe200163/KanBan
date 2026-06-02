"""
DevFlow AI Client - Claude Code CLI Integration

This module provides the AIClient class for dispatching Claude Code CLI
to handle issues, executing AI commands, and managing PR creation via
GitHub API.

Environment Variables Required:
    GITHUB_TOKEN: GitHub personal access token for PR creation
    CLAUDE_PATH: Path to Claude Code CLI (optional, defaults to "claude")
"""

import asyncio
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """
    Result of an AI execution attempt.

    Attributes:
        success: Whether the execution completed successfully
        output: Standard output from the command (None on failure)
        error: Error message if execution failed (None on success)
        pr_url: URL of created PR if applicable (None otherwise)
        duration_ms: Execution time in milliseconds
    """
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    pr_url: Optional[str] = None
    duration_ms: int = 0


class AIClientError(Exception):
    """Base exception for AIClient errors."""
    pass


class ClaudeExecutionError(AIClientError):
    """Raised when Claude Code CLI execution fails."""
    pass


class GitHubAPIError(AIClientError):
    """Raised when GitHub API calls fail."""
    pass


class AIClient:
    """
    Client for dispatching Claude Code CLI and managing AI execution.

    This class handles the execution flow:
    1. Prepare context from issue and memory system
    2. Execute Claude Code CLI with issue details
    3. Monitor progress via WebSocket (integration point)
    4. Create PR via GitHub API
    5. Return execution result

    Attributes:
        config: Configuration dictionary containing:
            - claude_path: Path to Claude Code CLI (default: "claude")
            - github_token: GitHub PAT for API calls
            - github_repo: Repository in format "owner/repo"
            - working_dir: Default working directory for CLI execution
            - timeout: Command timeout in seconds (default: 300)
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the AIClient with configuration.

        Args:
            config: Configuration dictionary. Required keys:
                - github_token: GitHub personal access token
                - github_repo: Repository in format "owner/repo"
                Optional keys:
                - claude_path: Path to Claude CLI (default: "claude")
                - working_dir: Default working directory
                - timeout: Command timeout in seconds (default: 300)
        """
        self.config = config
        self.claude_path = config.get("claude_path", "claude")
        self.github_token = config.get("github_token") or os.getenv("GITHUB_TOKEN")
        self.github_repo = config.get("github_repo")
        self.working_dir = config.get("working_dir", "/Users/user/Code/kanban")
        self.timeout = config.get("timeout", 300)  # 5 minutes default

        if not self.github_token:
            raise AIClientError("github_token is required in config or GITHUB_TOKEN env var")
        if not self.github_repo:
            raise AIClientError("github_repo is required in config")

        self._github_headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        }

        # WebSocket broadcaster for real-time log streaming
        self._broadcaster: Optional[Callable] = None
        self._job_id: Optional[str] = None

        logger.info(
            f"AIClient initialized: claude_path={self.claude_path}, "
            f"repo={self.github_repo}, timeout={self.timeout}s"
        )

    async def dispatch(self, issue: Dict[str, Any], context: Dict[str, Any]) -> ExecutionResult:
        """
        Dispatch Claude Code CLI to handle an issue.

        This is the main entry point for AI execution. It:
        1. Prepares a prompt from issue details and context
        2. Executes Claude Code CLI
        3. Creates a PR with the results
        4. Returns the execution result

        Args:
            issue: Issue dictionary containing:
                - key: Issue key (e.g., "DEV-142")
                - title: Issue title
                - description: Issue description
                - profile: ECC profile (e.g., "frontend", "backend")
                - labels: List of labels
            context: Context dictionary containing:
                - memory: Optional memory system reference
                - working_dir: Override working directory
                - branch_name: Optional branch name to use
                - pr_title: Optional PR title override
                - pr_body: Optional PR body override

        Returns:
            ExecutionResult with success status, output, error, and PR URL
        """
        start_time = time.time()
        issue_key = issue.get("key", "UNKNOWN")
        logger.info(f"Dispatching AI execution for issue: {issue_key}")

        try:
            # Step 1: Prepare context
            working_dir = context.get("working_dir", self.working_dir)
            branch_name = context.get("branch_name") or f"feature/{issue_key.lower()}"
            prompt = self._build_prompt(issue, context)

            logger.debug(f"Prepared prompt for {issue_key}: {len(prompt)} chars")
            logger.debug(f"Working directory: {working_dir}")
            logger.debug(f"Branch: {branch_name}")

            # Step 2: Execute Claude Code CLI
            stdout, stderr = await self.execute_claude(prompt, working_dir)

            if stderr:
                logger.warning(f"Claude stderr for {issue_key}: {stderr}")

            # Step 3: Create PR
            pr_title = context.get("pr_title") or f"feat({issue_key}): {issue.get('title', '')}"
            pr_body = context.get("pr_body") or self._build_pr_body(issue, stdout)

            pr_url = await self.create_pr(branch_name, pr_title, pr_body)
            logger.info(f"PR created for {issue_key}: {pr_url}")

            duration_ms = int((time.time() - start_time) * 1000)

            return ExecutionResult(
                success=True,
                output=stdout,
                error=None,
                pr_url=pr_url,
                duration_ms=duration_ms,
            )

        except ClaudeExecutionError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Claude execution failed for {issue_key}: {e}")
            return ExecutionResult(
                success=False,
                output=None,
                error=str(e),
                pr_url=None,
                duration_ms=duration_ms,
            )

        except GitHubAPIError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"GitHub API error for {issue_key}: {e}")
            return ExecutionResult(
                success=False,
                output=None,
                error=f"GitHub API error: {e}",
                pr_url=None,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Unexpected error dispatching {issue_key}: {e}", exc_info=True)
            return ExecutionResult(
                success=False,
                output=None,
                error=f"Unexpected error: {e}",
                pr_url=None,
                duration_ms=duration_ms,
            )

    async def execute_claude(self, prompt: str, working_dir: str) -> tuple[str, str]:
        """
        Execute Claude Code CLI and return stdout, stderr.

        This method runs the Claude Code CLI with the provided prompt.
        It uses asyncio to run the subprocess non-blocking.

        Args:
            prompt: The prompt/instruction to send to Claude Code
            working_dir: Directory to execute in

        Returns:
            Tuple of (stdout, stderr) from the command

        Raises:
            ClaudeExecutionError: If the command fails or times out
        """
        logger.debug(f"Executing Claude CLI in {working_dir}")

        # Build the command
        # Claude Code CLI is typically invoked with:
        # claude --print --no-input <prompt>
        # or claude -p <prompt> for non-interactive mode
        cmd = [
            self.claude_path,
            "-p",
            prompt,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=self._build_env(),
            )

            # Start streaming output to WebSocket if broadcaster is set
            streaming_task = None
            if self._broadcaster:
                streaming_task = asyncio.create_task(self._stream_process_output(process))

            # Wait for completion with timeout
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout,
                )
            finally:
                # Ensure streaming task is cancelled if still running
                if streaming_task and not streaming_task.done():
                    streaming_task.cancel()

            stdout = stdout_bytes.decode("utf-8") if stdout_bytes else ""
            stderr = stderr_bytes.decode("utf-8") if stderr_bytes else ""

            if process.returncode != 0:
                raise ClaudeExecutionError(
                    f"Claude CLI exited with code {process.returncode}: {stderr}"
                )

            logger.debug(f"Claude CLI completed successfully, output: {len(stdout)} chars")
            return stdout, stderr

        except asyncio.TimeoutError:
            # Kill the process on timeout
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
            raise ClaudeExecutionError(f"Claude CLI timed out after {self.timeout}s")

        except FileNotFoundError:
            raise ClaudeExecutionError(
                f"Claude CLI not found at '{self.claude_path}'. "
                "Please install Claude Code CLI or set claude_path in config."
            )

        except Exception as e:
            raise ClaudeExecutionError(f"Failed to execute Claude CLI: {e}")

    async def create_pr(
        self,
        branch: str,
        title: str,
        body: str,
        base: str = "main",
    ) -> Optional[str]:
        """
        Create a Pull Request via GitHub API.

        Args:
            branch: The branch name containing the changes
            title: PR title
            body: PR body/description
            base: Target branch to merge into (default: "main")

        Returns:
            PR URL if successful, None otherwise

        Raises:
            GitHubAPIError: If the API call fails
        """
        logger.info(f"Creating PR: {title} from branch '{branch}' into '{base}'")

        # First, get the commit SHA of the base branch
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Verify branch exists and get its SHA
                ref_url = f"https://api.github.com/repos/{self.github_repo}/branches/{base}"
                ref_response = await client.get(ref_url, headers=self._github_headers)

                if ref_response.status_code == 404:
                    raise GitHubAPIError(f"Branch '{base}' not found in {self.github_repo}")
                if ref_response.status_code != 200:
                    raise GitHubAPIError(
                        f"Failed to fetch branch info: {ref_response.status_code} "
                        f"{ref_response.text}"
                    )

                base_sha = ref_response.json()["commit"]["sha"]

                # Create the PR
                pr_url = f"https://api.github.com/repos/{self.github_repo}/pulls"
                pr_payload = {
                    "title": title,
                    "body": body,
                    "head": branch,
                    "base": base,
                }

                pr_response = await client.post(
                    pr_url,
                    headers=self._github_headers,
                    json=pr_payload,
                )

                if pr_response.status_code == 201:
                    pr_data = pr_response.json()
                    pr_number = pr_data["number"]
                    pr_html_url = pr_data["html_url"]
                    logger.info(f"PR #{pr_number} created successfully: {pr_html_url}")
                    return pr_html_url

                elif pr_response.status_code == 422:
                    # PR already exists or branch has no new commits
                    error_data = pr_response.json()
                    if "errors" in error_data:
                        for error in error_data["errors"]:
                            if error.get("field") == "head" and "already exists" in str(error):
                                # Find existing PR
                                existing_pr = await self._find_existing_pr(branch)
                                if existing_pr:
                                    return existing_pr
                    raise GitHubAPIError(f"PR creation failed: {error_data}")

                else:
                    raise GitHubAPIError(
                        f"Failed to create PR: {pr_response.status_code} {pr_response.text}"
                    )

        except httpx.TimeoutException:
            raise GitHubAPIError("GitHub API request timed out")
        except httpx.RequestError as e:
            raise GitHubAPIError(f"GitHub API request failed: {e}")

    async def _find_existing_pr(self, branch: str) -> Optional[str]:
        """
        Find an existing open PR for a branch.

        Args:
            branch: Branch name to search for

        Returns:
            PR URL if found, None otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                search_url = f"https://api.github.com/repos/{self.github_repo}/pulls"
                response = await client.get(
                    search_url,
                    headers=self._github_headers,
                    params={"state": "open", "head": f"{self.github_repo.split('/')[0]}:{branch}"},
                )

                if response.status_code == 200:
                    prs = response.json()
                    if prs:
                        return prs[0]["html_url"]

        except Exception as e:
            logger.warning(f"Failed to search for existing PR: {e}")

        return None

    def _build_prompt(self, issue: Dict[str, Any], context: Dict[str, Any]) -> str:
        """
        Build the prompt for Claude Code CLI from issue and context.

        Args:
            issue: Issue dictionary
            context: Context dictionary

        Returns:
            Formatted prompt string
        """
        issue_key = issue.get("key", "UNKNOWN")
        title = issue.get("title", "")
        description = issue.get("description", "")
        profile = issue.get("profile", "default")
        labels = issue.get("labels", [])

        # Build the prompt with clear instructions
        prompt_parts = [
            f"# Issue: {issue_key}",
            f"## Title: {title}",
            f"## Profile: {profile}",
        ]

        if labels:
            prompt_parts.append(f"## Labels: {', '.join(labels)}")

        if description:
            prompt_parts.append(f"## Description:\n{description}")

        # Add memory context if available
        if context.get("memory"):
            memory_ref = context["memory"]
            prompt_parts.append(f"## Memory Context:\nReference: {memory_ref}")

        # Add task instructions based on profile
        prompt_parts.append(self._get_profile_instructions(profile))

        # Add footer with instructions
        prompt_parts.append(
            "\n---\n"
            "## Instructions\n"
            "1. Analyze the issue and implement the required changes\n"
            "2. Ensure all tests pass before completing\n"
            "3. Create commits with descriptive messages following conventional commits\n"
            "4. Push changes and create a PR when ready\n"
            "5. Return a summary of what was done in your output"
        )

        return "\n\n".join(prompt_parts)

    def _get_profile_instructions(self, profile: str) -> str:
        """
        Get profile-specific instructions for the prompt.

        Args:
            profile: The ECC profile name

        Returns:
            Profile-specific instruction string
        """
        profile_instructions = {
            "frontend": (
                "\n## Profile-Specific Instructions (Frontend)\n"
                "- Follow the project's frontend coding style\n"
                "- Ensure responsive design works on all breakpoints\n"
                "- Run lint and type checks before completing\n"
                "- Test accessibility (keyboard nav, screen reader)\n"
            ),
            "backend": (
                "\n## Profile-Specific Instructions (Backend)\n"
                "- Follow REST API conventions\n"
                "- Ensure database migrations are included if needed\n"
                "- Run backend tests and verify API contracts\n"
                "- Check error handling is comprehensive\n"
            ),
            "security": (
                "\n## Profile-Specific Instructions (Security)\n"
                "- Run security scans (nuclei, semgrep)\n"
                "- Verify no hardcoded secrets or credentials\n"
                "- Ensure input validation is comprehensive\n"
                "- Document any security considerations\n"
            ),
            "refactor": (
                "\n## Profile-Specific Instructions (Refactor)\n"
                "- Maintain existing functionality\n"
                "- Improve code quality without changing behavior\n"
                "- Ensure test coverage is maintained or improved\n"
                "- Document any architectural changes\n"
            ),
            "debug": (
                "\n## Profile-Specific Instructions (Debug)\n"
                "- Reproduce the issue first\n"
                "- Identify root cause\n"
                "- Implement fix\n"
                "- Verify the fix resolves the issue\n"
            ),
        }

        return profile_instructions.get(
            profile,
            "\n## Profile-Specific Instructions\n"
            "- Follow project conventions\n"
            "- Write clean, maintainable code\n"
            "- Test your changes\n"
        )

    def _build_pr_body(self, issue: Dict[str, Any], output: str) -> str:
        """
        Build the PR body from issue and execution output.

        Args:
            issue: Issue dictionary
            output: Output from Claude execution

        Returns:
            Formatted PR body string
        """
        issue_key = issue.get("key", "UNKNOWN")
        title = issue.get("title", "")
        description = issue.get("description", "") or "No description provided."

        # Truncate output if too long (GitHub has limits)
        max_output_length = 5000
        if len(output) > max_output_length:
            output = output[:max_output_length] + "\n\n... (output truncated)"

        body = f"""## Summary

Implementation for **{issue_key}**: {title}

## Issue Description

{description}

## Changes Made

{output if output else "See commit history for details."}

---
*Generated by DevFlow AI Client*
"""
        return body

    def _build_env(self) -> Dict[str, str]:
        """
        Build the environment variables for subprocess.

        Returns:
            Environment dictionary with GitHub token if available
        """
        env = os.environ.copy()
        # Pass GitHub token to subprocess if available
        if self.github_token:
            env["GITHUB_TOKEN"] = self.github_token
        return env

    def set_broadcaster(self, broadcaster: Callable, job_id: str) -> None:
        """
        Set the WebSocket broadcaster for real-time log streaming.

        Args:
            broadcaster: Callable that accepts (job_id, log_entry) and broadcasts
            job_id: The job ID to associate with this execution
        """
        self._broadcaster = broadcaster
        self._job_id = job_id

    async def _emit_log(self, stream: str, text: str) -> None:
        """
        Emit a log entry via the broadcaster if configured.

        Args:
            stream: "stdout" or "stderr"
            text: Log text content
        """
        if self._broadcaster and self._job_id:
            # Truncate very long lines to prevent flooding
            if len(text) > 2000:
                text = text[:2000] + "\n... (truncated)"
            try:
                await self._broadcaster(self._job_id, {
                    "type": "log",
                    "stream": stream,
                    "text": text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                logger.warning(f"Failed to emit log: {e}")

    async def _stream_process_output(self, process: asyncio.subprocess.Process) -> None:
        """
        Stream process stdout/stderr in real-time via broadcaster.

        Args:
            process: The asyncio subprocess handle
        """
        if not self._broadcaster:
            return

        # Read stderr in a separate task to avoid blocking
        async def read_stderr():
            try:
                while True:
                    line = await process.stderr.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace")
                    await self._emit_log("stderr", text)
            except Exception:
                pass

        # Read stdout
        try:
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                await self._emit_log("stdout", text)
        except Exception:
            pass

        # Wait for stderr reading to complete
        await read_stderr()


# =============================================================================
# Factory Function for Easy Instantiation
# =============================================================================

def create_ai_client(
    claude_path: Optional[str] = None,
    github_token: Optional[str] = None,
    github_repo: Optional[str] = None,
    working_dir: Optional[str] = None,
    timeout: int = 300,
) -> AIClient:
    """
    Factory function to create an AIClient with type-safe parameters.

    This is the recommended way to create an AIClient instance.

    Args:
        claude_path: Path to Claude CLI (defaults to "claude")
        github_token: GitHub personal access token
        github_repo: Repository in format "owner/repo"
        working_dir: Default working directory
        timeout: Command timeout in seconds

    Returns:
        Configured AIClient instance

    Raises:
        AIClientError: If required parameters are missing
    """
    config: Dict[str, Any] = {
        "timeout": timeout,
    }

    if claude_path:
        config["claude_path"] = claude_path
    if github_token:
        config["github_token"] = github_token
    if github_repo:
        config["github_repo"] = github_repo
    if working_dir:
        config["working_dir"] = working_dir

    return AIClient(config)
