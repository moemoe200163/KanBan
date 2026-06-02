"""
DevFlow Memory System - Context Memory for AI Agents

Manages context memory for AI agents to avoid redundant codebase exploration.
Stores task contexts, file signatures, and long-term session data.

Required Environment Variables:
- MEMORY_BASE_PATH: Base path for memory storage (default: "memory")
"""

import json
import os
import re
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from dataclasses import dataclass, asdict


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class FileSignature:
    """Represents a function or class signature extracted from source code."""
    file_path: str
    name: str
    type: str  # 'function', 'class', 'method'
    signature: str  # Full signature string
    line_number: int
    dependencies: List[str]
    hash: str  # Content hash for change detection


@dataclass
class TaskContext:
    """Context for a task/issue being processed."""
    issue_id: str
    title: str
    description: str
    status: str
    created_at: str
    updated_at: str
    file_signatures: Dict[str, FileSignature]  # file_path -> signature
    explored_paths: List[str]  # Directories/files already explored
    agent_id: Optional[str] = None


# ============================================================================
# MemorySystem Implementation
# ============================================================================

class MemorySystem:
    """
    Context memory for AI agents.

    Stores:
    - context.json: Current task context by issue_id
    - signatures/: Cached file signatures for change detection
    - sessions/: Long-term session memory by agent_id

    Architecture:
        memory/
        ├── context.json       # Issue contexts
        ├── signatures/        # Cached file signatures
        │   └── {project}/     # Per-project signatures
        │       └── {file_hash}.json
        └── sessions/          # Long-term agent sessions
            └── {agent_id}.json
    """

    def __init__(self, base_path: Optional[str] = None):
        """
        Initialize the MemorySystem.

        Args:
            base_path: Base directory for memory storage.
                      Defaults to MEMORY_BASE_PATH env var or "memory".
        """
        self.base_path = Path(base_path or os.environ.get("MEMORY_BASE_PATH", "memory"))
        self.context_path = self.base_path / "context.json"
        self.signatures_path = self.base_path / "signatures"
        self.sessions_path = self.base_path / "sessions"

        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Create memory directory structure if it doesn't exist."""
        self.base_path.mkdir(exist_ok=True, parents=True)
        self.signatures_path.mkdir(exist_ok=True, parents=True)
        self.sessions_path.mkdir(exist_ok=True, parents=True)

        # Initialize context.json if it doesn't exist
        if not self.context_path.exists():
            self._write_json(self.context_path, {})

    # =========================================================================
    # JSON Helpers
    # =========================================================================

    def _read_json(self, path: Path) -> Dict[str, Any]:
        """Read and parse a JSON file safely."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            return {}

    def _write_json(self, path: Path, data: Dict[str, Any]) -> None:
        """Write data to a JSON file with proper formatting."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # =========================================================================
    # Context Management
    # =========================================================================

    def save_context(self, issue_id: str, context: Dict[str, Any]) -> None:
        """
        Save task context to context.json.

        Args:
            issue_id: Unique identifier for the issue/task
            context: Dictionary containing:
                - title: Task title
                - description: Task description
                - status: Current status
                - file_signatures: Dict of FileSignature objects
                - explored_paths: List of already explored paths
                - agent_id: Optional agent handling this task

        Raises:
            IOError: If unable to write to storage
        """
        all_contexts = self._read_json(self.context_path)

        # Build TaskContext with timestamps
        task_context = {
            "issue_id": issue_id,
            "title": context.get("title", ""),
            "description": context.get("description", ""),
            "status": context.get("status", "pending"),
            "created_at": context.get("created_at", datetime.now().isoformat()),
            "updated_at": datetime.now().isoformat(),
            "file_signatures": self._serialize_signatures(
                context.get("file_signatures", {})
            ),
            "explored_paths": context.get("explored_paths", []),
            "agent_id": context.get("agent_id"),
        }

        all_contexts[issue_id] = task_context
        self._write_json(self.context_path, all_contexts)

    def load_context(self, issue_id: str) -> Optional[Dict[str, Any]]:
        """
        Load task context by issue_id.

        Args:
            issue_id: Unique identifier for the issue/task

        Returns:
            Task context dictionary if found, None otherwise
        """
        all_contexts = self._read_json(self.context_path)
        context = all_contexts.get(issue_id)

        if context:
            # Deserialize file signatures back to FileSignature objects
            context["file_signatures"] = self._deserialize_signatures(
                context.get("file_signatures", {})
            )

        return context

    def list_contexts(self) -> List[str]:
        """List all issue_ids with stored contexts."""
        return list(self._read_json(self.context_path).keys())

    def delete_context(self, issue_id: str) -> bool:
        """Delete a context by issue_id. Returns True if deleted."""
        all_contexts = self._read_json(self.context_path)
        if issue_id in all_contexts:
            del all_contexts[issue_id]
            self._write_json(self.context_path, all_contexts)
            return True
        return False

    # =========================================================================
    # File Signature Extraction
    # =========================================================================

    def get_file_signatures(self, project_path: str) -> Dict[str, str]:
        """
        Extract function and class signatures from important files.

        Analyzes Python files in the project to build a map of:
        - File path -> content hash (for change detection)
        - Function/class signatures with line numbers

        Args:
            project_path: Path to the project directory

        Returns:
            Dictionary mapping file paths to their content hashes.
            Additional signature data is cached in signatures_path.
        """
        project_path = Path(project_path)
        signatures: Dict[str, str] = {}

        if not project_path.exists():
            return signatures

        # Patterns for extracting signatures
        function_pattern = re.compile(
            r"^(?:async\s+)?def\s+(\w+)\s*\((.*?)\)\s*(?:->.*?)?:\s*(?:#.*)?$",
            re.MULTILINE
        )
        class_pattern = re.compile(
            r"^class\s+(\w+)(?:\([^)]*\))?\s*:\s*(?:#.*)?$",
            re.MULTILINE
        )
        method_pattern = re.compile(
            r"^\s+(?:async\s+)?def\s+(\w+)\s*\((.*?)\)\s*(?:->.*?)?:\s*(?:#.*)?$",
            re.MULTILINE
        )

        # Process Python files
        for py_file in project_path.rglob("*.py"):
            # Skip common non-source directories
            if any(
                part.startswith(".") or part in {"__pycache__", "node_modules", "venv", ".venv"}
                for part in py_file.parts
            ):
                continue

            try:
                content = py_file.read_text(encoding="utf-8")
                file_hash = hashlib.md5(content.encode()).hexdigest()
                signatures[str(py_file)] = file_hash

                # Extract signatures and cache them
                self._cache_file_signatures(py_file, content, file_hash, function_pattern, class_pattern, method_pattern)

            except (IOError, UnicodeDecodeError) as e:
                continue

        return signatures

    def _cache_file_signatures(
        self,
        file_path: Path,
        content: str,
        file_hash: str,
        function_pattern: re.Pattern,
        class_pattern: re.Pattern,
        method_pattern: re.Pattern
    ) -> None:
        """Extract and cache signatures for a single file."""
        signatures: List[Dict[str, Any]] = []
        lines = content.split("\n")

        for line_num, line in enumerate(lines, start=1):
            # Check for class definitions
            class_match = class_pattern.match(line)
            if class_match:
                signatures.append({
                    "file_path": str(file_path),
                    "name": class_match.group(1),
                    "type": "class",
                    "signature": line.strip(),
                    "line_number": line_num,
                    "dependencies": [],
                    "hash": file_hash
                })
                continue

            # Check for function definitions (top-level only in this pass)
            func_match = function_pattern.match(line)
            if func_match:
                name = func_match.group(1)
                params = func_match.group(2)

                # Determine dependencies from parameters
                deps = self._extract_dependencies(params)

                signatures.append({
                    "file_path": str(file_path),
                    "name": name,
                    "type": "function",
                    "signature": f"def {name}({params})",
                    "line_number": line_num,
                    "dependencies": deps,
                    "hash": file_hash
                })
                continue

            # Check for method definitions (indented)
            method_match = method_pattern.match(line)
            if method_match:
                name = method_match.group(1)
                params = method_match.group(2)

                # Skip private/dunder methods unless they are important
                if name.startswith("__") and name != "__init__":
                    continue

                deps = self._extract_dependencies(params)

                signatures.append({
                    "file_path": str(file_path),
                    "name": name,
                    "type": "method",
                    "signature": f"def {name}({params})",
                    "line_number": line_num,
                    "dependencies": deps,
                    "hash": file_hash
                })

        # Save to cache if we found any signatures
        if signatures:
            cache_file = self.signatures_path / f"{file_hash}.json"
            existing = self._read_json(cache_file)

            # Only update if content changed
            if existing.get("content_hash") != file_hash:
                self._write_json(cache_file, {
                    "file_path": str(file_path),
                    "content_hash": file_hash,
                    "signatures": signatures,
                    "cached_at": datetime.now().isoformat()
                })

    def _extract_dependencies(self, params_str: str) -> List[str]:
        """Extract type dependencies from a parameter string."""
        deps = []

        # Match type annotations like "param: Type" or "param: Type1 | Type2"
        type_pattern = re.compile(r"\s*(\w+)\s*:\s*([\w\s|\[\],\.]+)")

        for match in type_pattern.finditer(params_str):
            type_annotation = match.group(2).strip()
            # Extract base types (first type in Union/Optional)
            base_type = type_annotation.split("|")[0].strip().split("[")[0]
            if base_type and base_type not in {"self", "cls"}:
                deps.append(base_type)

        return deps

    def get_signature(self, file_hash: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached signatures for a file by its hash."""
        cache_file = self.signatures_path / f"{file_hash}.json"
        return self._read_json(cache_file) if cache_file.exists() else None

    def has_changed(self, file_path: str, previous_hash: str) -> bool:
        """
        Check if a file has changed since last signature extraction.

        Args:
            file_path: Path to the file
            previous_hash: Hash from previous signature extraction

        Returns:
            True if file has changed, False otherwise
        """
        try:
            current_content = Path(file_path).read_text(encoding="utf-8")
            current_hash = hashlib.md5(current_content.encode()).hexdigest()
            return current_hash != previous_hash
        except (IOError, UnicodeDecodeError):
            return True  # Assume changed if can't read

    # =========================================================================
    # Signature Serialization Helpers
    # =========================================================================

    def _serialize_signatures(
        self, signatures: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """Convert FileSignature objects to serializable dicts."""
        result = {}
        for path, sig in signatures.items():
            if isinstance(sig, FileSignature):
                result[path] = asdict(sig)
            else:
                result[path] = sig
        return result

    def _deserialize_signatures(
        self, signatures: Dict[str, Dict[str, Any]]
    ) -> Dict[str, FileSignature]:
        """Convert dicts back to FileSignature objects."""
        result = {}
        for path, data in signatures.items():
            if isinstance(data, dict) and "file_path" in data:
                result[path] = FileSignature(**data)
            else:
                result[path] = data
        return result

    # =========================================================================
    # Session Management
    # =========================================================================

    def save_session(self, agent_id: str, data: Dict[str, Any]) -> None:
        """
        Save long-term session memory for an agent.

        Args:
            agent_id: Unique identifier for the agent
            data: Session data to persist, can include:
                - history: List of past interactions
                - preferences: Agent preferences
                - learned_context: Accumulated knowledge
                - last_active: Timestamp
        """
        session_file = self.sessions_path / f"{agent_id}.json"

        # Load existing session or create new
        existing = self._read_json(session_file)

        # Merge new data with existing
        session = {
            "agent_id": agent_id,
            "updated_at": datetime.now().isoformat(),
            "data": data,
            "history": existing.get("history", []),
        }

        # Append to history if significant interaction
        if data.get("interaction"):
            session["history"].append({
                "timestamp": datetime.now().isoformat(),
                "type": data.get("interaction_type", "update"),
                "summary": data.get("interaction", "")[:200]  # Truncate long summaries
            })

            # Keep only last 100 history entries
            session["history"] = session["history"][-100:]

        self._write_json(session_file, session)

    def load_session(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Load long-term session memory for an agent.

        Args:
            agent_id: Unique identifier for the agent

        Returns:
            Session data dictionary if found, None otherwise
        """
        session_file = self.sessions_path / f"{agent_id}.json"

        if not session_file.exists():
            return None

        return self._read_json(session_file)

    def list_sessions(self) -> List[str]:
        """List all agent_ids with stored sessions."""
        return [f.stem for f in self.sessions_path.glob("*.json")]

    def delete_session(self, agent_id: str) -> bool:
        """Delete a session by agent_id. Returns True if deleted."""
        session_file = self.sessions_path / f"{agent_id}.json"
        if session_file.exists():
            session_file.unlink()
            return True
        return False

    def get_session_history(
        self, agent_id: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get recent session history for an agent.

        Args:
            agent_id: Unique identifier for the agent
            limit: Maximum number of history entries to return

        Returns:
            List of recent history entries
        """
        session = self.load_session(agent_id)
        if not session:
            return []

        history = session.get("history", [])
        return history[-limit:] if limit > 0 else history

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def clear_all(self) -> None:
        """Clear all memory data. Use with caution."""
        # Clear contexts
        self._write_json(self.context_path, {})

        # Clear signatures
        for sig_file in self.signatures_path.glob("*.json"):
            sig_file.unlink()

        # Clear sessions
        for session_file in self.sessions_path.glob("*.json"):
            session_file.unlink()

    def get_memory_stats(self) -> Dict[str, Any]:
        """Get statistics about memory usage."""
        return {
            "base_path": str(self.base_path),
            "contexts_count": len(self.list_contexts()),
            "sessions_count": len(self.list_sessions()),
            "signatures_count": len(list(self.signatures_path.glob("*.json"))),
            "storage_bytes": sum(
                f.stat().st_size
                for f in self.base_path.rglob("*")
                if f.is_file()
            )
        }


# ============================================================================
# Module Exports
# ============================================================================

__all__ = ["MemorySystem", "FileSignature", "TaskContext"]
