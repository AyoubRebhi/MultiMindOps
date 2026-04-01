import re
from pathlib import Path
from typing import Any

import yaml


class SimpleHashEmbeddingFunction:
    def __init__(self, dimensions: int = 128):
        self.dimensions = dimensions

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in input]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[a-zA-Z0-9_./:-]+", text.lower())
        if not tokens:
            return vector

        for token in tokens:
            index = hash(token) % self.dimensions
            vector[index] += 1.0

        norm = sum(value * value for value in vector) ** 0.5 or 1.0
        return [value / norm for value in vector]


class TemplateCorpusService:
    def load_documents(self, corpus_root: str | Path) -> list[dict[str, Any]]:
        root = Path(corpus_root)
        documents: list[dict[str, Any]] = []

        if not root.exists():
            return documents

        for path in sorted(root.rglob("*.md")):
            parsed = self._parse_markdown_document(path)
            if parsed:
                documents.append(parsed)

        return documents

    def _parse_markdown_document(self, path: Path) -> dict[str, Any] | None:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return None

        metadata: dict[str, Any] = {}
        content = raw

        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                metadata = yaml.safe_load(parts[1]) or {}
                content = parts[2].strip()

        template_id = metadata.get("id") or path.stem
        artifact_type = metadata.get("artifact_type") or path.parent.name

        return {
            "id": str(template_id),
            "path": str(path).replace("\\", "/"),
            "artifact_type": str(artifact_type),
            "metadata": {
                **metadata,
                "id": str(template_id),
                "artifact_type": str(artifact_type),
                "source_path": str(path).replace("\\", "/"),
                "dependencies": metadata.get("dependencies") or [],
                "tags": metadata.get("tags") or [],
            },
            "content": content,
        }

    def build_document_text(self, document: dict[str, Any]) -> str:
        metadata = document.get("metadata") or {}
        metadata_parts = [
            f"artifact_type={metadata.get('artifact_type', '')}",
            f"language={metadata.get('language', '')}",
            f"framework={metadata.get('framework', '')}",
            f"project_type={metadata.get('project_type', '')}",
            f"runtime={metadata.get('runtime', '')}",
            f"dependencies={' '.join(metadata.get('dependencies') or [])}",
            f"tags={' '.join(metadata.get('tags') or [])}",
            f"description={metadata.get('description', '')}",
        ]
        return "\n".join(metadata_parts + ["", document.get("content", "")]).strip()
