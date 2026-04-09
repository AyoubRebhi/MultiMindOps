"""
Targeted repository parser — reads only LLM-prioritized files.
Replaces the 250-file heuristic scan with a focused 5-20 file deep parse.
"""
import logging
from pathlib import Path
from typing import Any, Dict, List

from backend.app.services.repository.llm_priority_engine import FileRanking, PriorityResult

logger = logging.getLogger(__name__)

# Maximum characters to read per file (avoids giant files blowing the context)
_MAX_FILE_CHARS = 4000
# Maximum chars for a summarized architecture context
_MAX_ARCH_CHARS = 800


class TargetedRepositoryParser:
    """
    Reads and returns the content of LLM-selected critical files only.
    Builds:
      - key_files_content  : { path → content_snippet }
      - file_relationships : detected cross-file references
      - critical_sections  : extracted key facts (base images, ports, env vars…)
      - architecture_summary : architecture hint from LLM + detected facts
    """

    def parse_targeted(
        self,
        repo_path: str,
        priority_result: PriorityResult,
    ) -> Dict[str, Any]:
        repo = Path(repo_path)
        critical_files: List[FileRanking] = priority_result.critical_files

        key_files_content: Dict[str, str] = {}
        unreadable: List[str] = []

        for ranking in critical_files:
            file_path = repo / ranking.path
            if not file_path.exists() or not file_path.is_file():
                # Try case-insensitive match (some repos use mixed case)
                match = self._find_case_insensitive(repo, ranking.path)
                if match:
                    file_path = match
                else:
                    unreadable.append(ranking.path)
                    continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                key_files_content[ranking.path] = content[:_MAX_FILE_CHARS]
            except Exception as exc:
                logger.debug("Could not read %s: %s", ranking.path, exc)
                unreadable.append(ranking.path)

        critical_sections = self._extract_critical_sections(key_files_content)
        file_relationships = self._build_file_relationships(key_files_content, critical_files)

        arch_parts = []
        if priority_result.architecture_hint:
            arch_parts.append(priority_result.architecture_hint)
        if priority_result.primary_stack:
            arch_parts.append("Stack: " + ", ".join(priority_result.primary_stack))
        if critical_sections.get("services"):
            arch_parts.append("Services: " + ", ".join(critical_sections["services"]))

        return {
            "key_files_content": key_files_content,
            "critical_files_ranked": [
                {
                    "path": r.path,
                    "priority": r.priority,
                    "reason": r.reason,
                    "category": r.category,
                }
                for r in critical_files
            ],
            "file_relationships": file_relationships,
            "critical_sections": critical_sections,
            "architecture_summary": " | ".join(arch_parts)[:_MAX_ARCH_CHARS],
            "unreadable_files": unreadable,
            "llm_used": priority_result.llm_used,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_case_insensitive(self, repo: Path, rel_path: str) -> Path | None:
        """Try to find a file ignoring case differences (Windows vs Linux repos)."""
        candidate = repo / rel_path
        # Already checked above — try parent dir listing
        parent = candidate.parent
        if not parent.exists():
            return None
        target_name = candidate.name.lower()
        for entry in parent.iterdir():
            if entry.name.lower() == target_name and entry.is_file():
                return entry
        return None

    def _extract_critical_sections(
        self, key_files_content: Dict[str, str]
    ) -> Dict[str, Any]:
        """Extract key facts from file contents without an LLM."""
        import re

        sections: Dict[str, Any] = {
            "base_images": [],
            "exposed_ports": [],
            "env_var_names": [],
            "services": [],
            "build_commands": [],
        }

        for path, content in key_files_content.items():
            filename = path.split("/")[-1].lower()

            # Dockerfile facts
            if "dockerfile" in filename:
                for match in re.finditer(r"^FROM\s+(\S+)", content, re.MULTILINE | re.IGNORECASE):
                    sections["base_images"].append(match.group(1))
                for match in re.finditer(r"^EXPOSE\s+(\d+)", content, re.MULTILINE | re.IGNORECASE):
                    sections["exposed_ports"].append(int(match.group(1)))
                for match in re.finditer(r"^ENV\s+(\w+)", content, re.MULTILINE | re.IGNORECASE):
                    sections["env_var_names"].append(match.group(1))
                for match in re.finditer(r"^RUN\s+(.+)$", content, re.MULTILINE | re.IGNORECASE):
                    cmd = match.group(1).strip()[:80]
                    if cmd:
                        sections["build_commands"].append(cmd)

            # docker-compose services
            if "docker-compose" in filename:
                for match in re.finditer(r"^\s{2}(\w[\w-]*):\s*$", content, re.MULTILINE):
                    service = match.group(1)
                    if service not in ("version", "networks", "volumes", "configs", "secrets"):
                        sections["services"].append(service)
                for match in re.finditer(r"^\s+-\s+['\"]?(\d+):\d+['\"]?", content, re.MULTILINE):
                    sections["exposed_ports"].append(int(match.group(1)))

            # .env.example / .env.template
            if ".env" in filename:
                for match in re.finditer(r"^([A-Z_][A-Z0-9_]*)=", content, re.MULTILINE):
                    sections["env_var_names"].append(match.group(1))

        # Deduplicate
        sections["base_images"] = list(dict.fromkeys(sections["base_images"]))
        sections["exposed_ports"] = sorted(set(sections["exposed_ports"]))
        sections["env_var_names"] = list(dict.fromkeys(sections["env_var_names"]))[:20]
        sections["services"] = list(dict.fromkeys(sections["services"]))
        sections["build_commands"] = sections["build_commands"][:10]

        return sections

    def _build_file_relationships(
        self,
        key_files_content: Dict[str, str],
        critical_files: List[FileRanking],
    ) -> Dict[str, Any]:
        """
        Build a lightweight cross-reference map.
        E.g. docker-compose.yml → references ["./Dockerfile", "./config/env.yml"]
        """
        import re

        relationships: Dict[str, Any] = {}
        known_paths = {r.path for r in critical_files}

        for path, content in key_files_content.items():
            refs: List[str] = []

            # Find references to other known files in our critical set
            for other_path in known_paths:
                if other_path == path:
                    continue
                filename = other_path.split("/")[-1]
                if filename in content or other_path in content:
                    refs.append(other_path)

            # docker-compose: extract build context paths
            if "docker-compose" in path.lower():
                for match in re.finditer(r"build:\s*['\"]?(\./[\w./\-]+)['\"]?", content):
                    refs.append(match.group(1))

            if refs:
                relationships[path] = {"references": list(dict.fromkeys(refs))}

        return relationships
