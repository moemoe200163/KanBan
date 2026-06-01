"""
Claude Code Local Adapter
"""
import asyncio
import os
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime, timezone
import logging

from .base import BaseAIAdapter, ExecutionResult

logger = logging.getLogger(__name__)


class ClaudeLocalAdapter(BaseAIAdapter):
    """Adapter for Claude Code CLI execution."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.claude_path = self.config.get("claude_path", "claude")
        self.github_token = self.config.get("github_token") or os.getenv("GITHUB_TOKEN")
        self.github_repo = self.config.get("github_repo")
        self.working_dir = self.config.get("working_dir", "/Users/user/Code/kanban")
        self.timeout = self.config.get("timeout", 300)
        self._broadcaster: Optional[Callable] = None
        self._job_id: Optional[str] = None

    @property
    def supported_harnesses(self) -> List[str]:
        return ["claude-code"]

    async def dispatch(
        self,
        issue: Dict[str, Any],
        context: Dict[str, Any],
    ) -> ExecutionResult:
        import time
        start_time = time.time()
        issue_key = issue.get("key", "UNKNOWN")

        try:
            working_dir = context.get("working_dir", self.working_dir)
            prompt = self._build_prompt(issue)
            stdout, stderr = await self.execute(
                task_id=f"dispatch_{issue_key}",
                prompt=prompt,
                workspace=working_dir,
            )

            pr_url = None
            if self.github_token and self.github_repo:
                pr_url = await self._create_pr(
                    context.get("branch_name", f"feature/{issue_key.lower()}"),
                    f"feat({issue_key}): {issue.get('title', '')}",
                    self._build_pr_body(issue, stdout),
                )

            return ExecutionResult(
                success=True,
                output=stdout,
                error=None,
                pr_url=pr_url,
                duration_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                output=None,
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )

    async def execute(
        self,
        task_id: str,
        prompt: str,
        workspace: str,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> ExecutionResult:
        import time
        start_time = time.time()

        if on_log:
            self._broadcaster = on_log
            self._job_id = task_id

        cmd = [self.claude_path, "-p", prompt]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workspace,
                env=self._build_env(),
            )

            if self._broadcaster:
                asyncio.create_task(self._stream_process_output(process))

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout,
            )

            stdout = stdout_bytes.decode("utf-8") if stdout_bytes else ""
            stderr = stderr_bytes.decode("utf-8") if stderr_bytes else ""

            if process.returncode != 0:
                return ExecutionResult(
                    success=False,
                    output=stdout,
                    error=f"Claude CLI exited with code {process.returncode}: {stderr}",
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            return ExecutionResult(success=True, output=stdout, duration_ms=int((time.time() - start_time) * 1000))
        except asyncio.TimeoutError:
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
            return ExecutionResult(success=False, error=f"Timed out after {self.timeout}s", duration_ms=int((time.time() - start_time) * 1000))
        except FileNotFoundError:
            return ExecutionResult(success=False, error=f"Claude CLI not found at '{self.claude_path}'", duration_ms=int((time.time() - start_time) * 1000))
        except Exception as e:
            return ExecutionResult(success=False, error=str(e), duration_ms=int((time.time() - start_time) * 1000))

    async def test_environment(self) -> bool:
        try:
            process = await asyncio.create_subprocess_exec(
                self.claude_path, "--version",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(process.communicate(), timeout=5)
            return process.returncode == 0
        except Exception:
            return False

    async def _stream_process_output(self, process: asyncio.subprocess.Process) -> None:
        if not self._broadcaster:
            return

        async def read_and_emit(stream, stream_name: str):
            try:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace")
                    if len(text) > 2000:
                        text = text[:2000] + "\n... (truncated)"
                    await self._broadcaster(self._job_id, {"type": "log", "stream": stream_name, "text": text, "timestamp": datetime.now(timezone.utc).isoformat()})
            except Exception:
                pass

        await asyncio.gather(
            read_and_emit(process.stdout, "stdout"),
            read_and_emit(process.stderr, "stderr"),
        )

    def _build_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        if self.github_token:
            env["GITHUB_TOKEN"] = self.github_token
        return env

    def _build_prompt(self, issue: Dict[str, Any]) -> str:
        issue_key = issue.get("key", "UNKNOWN")
        title = issue.get("title", "")
        description = issue.get("description", "")
        profile = issue.get("profile", "default")
        labels = issue.get("labels", [])

        prompt_parts = [f"# Issue: {issue_key}", f"## Title: {title}", f"## Profile: {profile}"]
        if labels:
            prompt_parts.append(f"## Labels: {', '.join(labels)}")
        if description:
            prompt_parts.append(f"## Description:\n{description}")
        prompt_parts.append(self._get_profile_instructions(profile))
        prompt_parts.append("\n---\n## Instructions\n1. Analyze the issue\n2. Implement changes\n3. Return summary")
        return "\n\n".join(prompt_parts)

    def _get_profile_instructions(self, profile: str) -> str:
        instructions = {
            "frontend": "Follow frontend best practices.",
            "backend": "Follow REST API conventions.",
            "security": "Run security scans.",
            "refactor": "Maintain functionality.",
            "debug": "Reproduce issue first.",
        }
        return instructions.get(profile, "Follow project conventions.")

    async def _create_pr(self, branch: str, title: str, body: str, base: str = "main") -> Optional[str]:
        import httpx
        if not self.github_token or not self.github_repo:
            return None

        headers = {"Authorization": f"token {self.github_token}", "Accept": "application/vnd.github.v3+json", "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                ref_response = await client.get(f"https://api.github.com/repos/{self.github_repo}/branches/{base}", headers=headers)
                if ref_response.status_code != 200:
                    return None
                pr_response = await client.post(f"https://api.github.com/repos/{self.github_repo}/pulls", headers=headers, json={"title": title, "body": body, "head": branch, "base": base})
                if pr_response.status_code == 201:
                    return pr_response.json().get("html_url")
        except Exception as e:
            logger.warning(f"Failed to create PR: {e}")
        return None

    def _build_pr_body(self, issue: Dict[str, Any], output: str) -> str:
        issue_key = issue.get("key", "UNKNOWN")
        title = issue.get("title", "")
        description = issue.get("description", "") or "No description."
        max_output_length = 5000
        if len(output) > max_output_length:
            output = output[:max_output_length] + "\n\n... (truncated)"
        return f"## Summary\n\nImplementation for **{issue_key}**: {title}\n\n## Issue Description\n\n{description}\n\n## Changes Made\n\n{output}\n\n---\n*Generated by DevFlow*"