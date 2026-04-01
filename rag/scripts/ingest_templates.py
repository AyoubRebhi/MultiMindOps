import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.rag_config import rag_config
from backend.app.services.template_corpus_service import (  # noqa: E402
    SimpleHashEmbeddingFunction,
    TemplateCorpusService,
)

try:  # noqa: E402
    import chromadb
except Exception as exc:  # pragma: no cover - optional dependency
    chromadb = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest infrastructure templates into ChromaDB.")
    parser.add_argument("--reset", action="store_true", help="Delete existing collection before indexing.")
    args = parser.parse_args()

    if chromadb is None:
        print(f"ChromaDB is unavailable: {type(IMPORT_ERROR).__name__}: {IMPORT_ERROR}")
        return 1

    corpus_service = TemplateCorpusService()
    documents = corpus_service.load_documents(rag_config.corpus_path)
    if not documents:
        print(f"No corpus documents found in {rag_config.corpus_path}")
        return 1

    rag_config.chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(rag_config.chroma_path))
    if args.reset:
        try:
            client.delete_collection(rag_config.collection_name)
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=rag_config.collection_name,
        embedding_function=SimpleHashEmbeddingFunction(),
    )

    collection.upsert(
        ids=[document["id"] for document in documents],
        documents=[corpus_service.build_document_text(document) for document in documents],
        metadatas=[_serialize_metadata(document["metadata"]) for document in documents],
    )

    print(
        f"Indexed {len(documents)} templates into "
        f"{rag_config.collection_name} at {rag_config.chroma_path}"
    )
    return 0


def _serialize_metadata(metadata: dict) -> dict:
    serialized = {}
    for key, value in metadata.items():
        if isinstance(value, list):
            serialized[key] = ", ".join(str(item) for item in value)
        else:
            serialized[key] = value
    return serialized


if __name__ == "__main__":
    raise SystemExit(main())
