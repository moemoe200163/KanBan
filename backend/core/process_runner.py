"""
DevFlow Backend - ECC Process Runner

Executes ECC commands as real subprocesses. This module provides
the ProcessRunner class that interfaces with the ECC binary.

Environment Variables:
    ECC_BINARY_PATH: Path to ECC binary (default: "ecc")
    ECC_TIMEOUT: Command timeout in seconds (default: 300)
"""

import asyncio
import logging
import os
from typing import AsyncIterator, Tuple, Optional

logger = logging.getLogger(__name__)

# Configuration from environment variables
ECC_BINARY_PATH = os.getenv("ECC_BINARY_PATH", "ecc")
ECC_TIMEOUT = int(os.getenv("ECC_TIMEOUT", "300"))


class ProcessRunnerError(Exception):
    """Base exception for ProcessRunner errors."""
    pass


class ProcessTimeoutError(ProcessRunnerError):
    """Raised when a command exceeds the timeout threshold."""
    pass


class ProcessNotFoundError(ProcessRunnerError):
    """Raised when the ECC binary cannot be found."""
    pass


class ProcessExecutionError(ProcessRunnerError):
    """Raised when a command fails during execution."""

    def __init__(self, message: str, stdout: str, stderr: str, exit_code: int):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code


class ProcessRunner:
    """
    Executes ECC commands as real subprocesses.

    Provides both synchronous command execution and async streaming output.

    Attributes:
        binary_path: Path to the ECC binary
        timeout: Default timeout for commands in seconds

    Example:
        runner = ProcessRunner()
        stdout, stderr, exit_code = runner.run_ecc_command(
            "/loop-start --profile=frontend",
            profile="frontend",
            harness="claude-code"
        )
    """

    def __init__(
        self,
        binary_path: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        """
        Initialize the ProcessRunner.

        Args:
            binary_path: Override ECC binary path (default: from ECC_BINARY_PATH env)
            timeout: Override default timeout in seconds (default: from ECC_TIMEOUT env)
        """
        self.binary_path = binary_path or ECC_BINARY_PATH
        self.timeout = timeout if timeout is not None else ECC_TIMEOUT

        logger.info(
            f"ProcessRunner initialized: binary={self.binary_path}, timeout={self.timeout}s"
        )

    def run_ecc_command(
        self,
        command: str,
        profile: str,
        harness: str,
        cwd: Optional[str] = None,
    ) -> Tuple[str, str, int]:
        """
        Execute an ECC command synchronously and return stdout, stderr, exit_code.

        This method blocks until the command completes or times out.
        For streaming output, use run_async_command instead.

        Args:
            command: The ECC command to execute (e.g., "/loop-start --profile=frontend")
            profile: The ECC profile to use (e.g., "frontend", "backend")
            harness: The harness to use (e.g., "claude-code", "codex")
            cwd: Optional working directory for the command

        Returns:
            Tuple of (stdout, stderr, exit_code)

        Raises:
            ProcessNotFoundError: If the ECC binary is not found
            ProcessTimeoutError: If the command exceeds the timeout
            ProcessExecutionError: If the command returns a non-zero exit code
        """
        # Build full command with profile and harness arguments
        full_command = f"{command} --profile={profile} --harness={harness}"

        logger.info(f"Executing ECC command: {full_command}")

        try:
            # Run synchronously using asyncio.run
            stdout, stderr, exit_code = asyncio.run(
                self._execute_command(full_command, cwd)
            )

            if exit_code != 0:
                raise ProcessExecutionError(
                    f"ECC command failed with exit code {exit_code}: {stderr}",
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=exit_code,
                )

            return stdout, stderr, exit_code

        except FileNotFoundError:
            raise ProcessNotFoundError(
                f"ECC binary not found at '{self.binary_path}'. "
                "Please set ECC_BINARY_PATH environment variable or install ECC."
            )
        except asyncio.TimeoutError:
            raise ProcessTimeoutError(
                f"ECC command timed out after {self.timeout} seconds"
            )

    async def run_async_command(
        self,
        command: str,
        cwd: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Execute a command asynchronously, yielding output lines as they arrive.

        This method is useful for long-running commands where you want to
        stream output in real-time rather than waiting for completion.

        Args:
            command: The full command string to execute
            cwd: Optional working directory for the command

        Yields:
            Output lines from stdout as they are produced

        Raises:
            ProcessNotFoundError: If the binary is not found
            ProcessTimeoutError: If the command exceeds the timeout

        Example:
            async for line in runner.run_async_command("ecc --version"):
                print(line, end="")
        """
        logger.debug(f"Starting async command: {command}")

        try:
            process = await asyncio.create_subprocess_exec(
                *command.split(),  # Simple split, handles basic commands
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=self._build_env(),
            )

            # Read stdout line by line as they become available
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                yield line.decode("utf-8").rstrip("\n")

            # Wait for process to complete
            await asyncio.wait_for(
                process.wait(),
                timeout=self.timeout,
            )

        except asyncio.TimeoutError:
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
            raise ProcessTimeoutError(
                f"Command timed out after {self.timeout} seconds: {command}"
            )
        except FileNotFoundError:
            raise ProcessNotFoundError(
                f"Command not found: {command.split()[0]}"
            )

    async def _execute_command(
        self,
        command: str,
        cwd: Optional[str] = None,
    ) -> Tuple[str, str, int]:
        """
        Internal async method to execute a command.

        Args:
            command: Full command string with arguments
            cwd: Optional working directory

        Returns:
            Tuple of (stdout, stderr, exit_code)
        """
        parts = command.split()

        process = await asyncio.create_subprocess_exec(
            *parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=self._build_env(),
        )

        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(),
            timeout=self.timeout,
        )

        stdout = stdout_bytes.decode("utf-8") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8") if stderr_bytes else ""

        return stdout, stderr, process.returncode

    def _build_env(self) -> dict:
        """
        Build environment variables for subprocess.

        Returns:
            Environment dictionary with ECC-specific settings
        """
        env = os.environ.copy()
        # Ensure ECC binary path is available
        env["ECC_BINARY_PATH"] = self.binary_path
        return env

    async def run_ecc_command_async(
        self,
        command: str,
        profile: str,
        harness: str,
        cwd: Optional[str] = None,
    ) -> Tuple[str, str, int]:
        """
        Async version of run_ecc_command for use in async contexts.

        Args:
            command: The ECC command to execute
            profile: The ECC profile to use
            harness: The harness to use
            cwd: Optional working directory

        Returns:
            Tuple of (stdout, stderr, exit_code)
        """
        full_command = f"{command} --profile={profile} --harness={harness}"
        logger.info(f"Executing ECC command async: {full_command}")

        try:
            stdout, stderr, exit_code = await self._execute_command(full_command, cwd)

            if exit_code != 0:
                raise ProcessExecutionError(
                    f"ECC command failed with exit code {exit_code}: {stderr}",
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=exit_code,
                )

            return stdout, stderr, exit_code

        except asyncio.TimeoutError:
            raise ProcessTimeoutError(
                f"ECC command timed out after {self.timeout} seconds"
            )
        except FileNotFoundError:
            raise ProcessNotFoundError(
                f"ECC binary not found at '{self.binary_path}'"
            )


# =============================================================================
# Factory Function
# =============================================================================

def create_process_runner(
    binary_path: Optional[str] = None,
    timeout: Optional[int] = None,
) -> ProcessRunner:
    """
    Factory function to create a ProcessRunner instance.

    Args:
        binary_path: Override ECC binary path
        timeout: Override default timeout in seconds

    Returns:
        Configured ProcessRunner instance
    """
    return ProcessRunner(binary_path=binary_path, timeout=timeout)


# =============================================================================
# Convenience Functions for Direct Use
# =============================================================================

_default_runner: Optional[ProcessRunner] = None


def get_runner() -> ProcessRunner:
    """Get or create the default ProcessRunner instance."""
    global _default_runner
    if _default_runner is None:
        _default_runner = ProcessRunner()
    return _default_runner


def run_command(
    command: str,
    profile: str,
    harness: str,
    cwd: Optional[str] = None,
) -> Tuple[str, str, int]:
    """
    Convenience function to run an ECC command using the default runner.

    Args:
        command: The ECC command to execute
        profile: The ECC profile to use
        harness: The harness to use
        cwd: Optional working directory

    Returns:
        Tuple of (stdout, stderr, exit_code)
    """
    return get_runner().run_ecc_command(command, profile, harness, cwd)