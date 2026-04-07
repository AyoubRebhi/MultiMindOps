#!/usr/bin/env python3
"""
Script d'ingestion du corpus DevSecOps dans Qdrant.

Pipeline :
  1. Charger les documents Markdown depuis rag/corpus/
  2. Chunking sémantique via Gemini (ou fallback simple)
  3. Embedding via Ollama nomic-embed-text:v1.5
  4. Upsert dans Qdrant collection "devsecops_knowledge"

Usage :
    # Ingestion complète
    python rag/scripts/ingest_qdrant.py

    # Recréer la collection (reset)
    python rag/scripts/ingest_qdrant.py --reset

    # Ingérer uniquement un type de document
    python rag/scripts/ingest_qdrant.py --doc-type docker

    # Mode verbose
    python rag/scripts/ingest_qdrant.py --verbose

    # Sans Gemini (fallback uniquement)
    python rag/scripts/ingest_qdrant.py --no-gemini
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Ajouter la racine du projet au path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.rag_config import rag_config
from backend.app.services.rag.gemini_chunking_service import GeminiChunkingService
from backend.app.services.rag.embedding_service import EmbeddingService
from backend.app.services.rag.qdrant_service import QdrantService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingest_qdrant")


# ── Chargement des documents ─────────────────────────────────────────────────

def load_corpus(corpus_root: Path, doc_type_filter: str | None = None) -> list[dict]:
    """Charge tous les fichiers Markdown du corpus avec métadonnées."""
    import yaml

    # Résoudre le chemin absolu (ROOT est la base si le chemin est relatif)
    corpus_root = (ROOT / corpus_root).resolve() if not corpus_root.is_absolute() else corpus_root.resolve()

    if not corpus_root.exists():
        logger.error("Corpus introuvable : %s", corpus_root)
        return []

    documents: list[dict] = []

    for md_file in sorted(corpus_root.rglob("*.md")):
        # Filtrer par type si demandé
        if doc_type_filter:
            relative = md_file.relative_to(corpus_root)
            folder = relative.parts[0] if len(relative.parts) > 1 else ""
            if doc_type_filter.lower() not in folder.lower():
                continue

        try:
            raw = md_file.read_text(encoding="utf-8").strip()
            if not raw:
                continue

            metadata: dict = {}
            content = raw

            # Extraire le front matter YAML
            if raw.startswith("---"):
                parts = raw.split("---", 2)
                if len(parts) >= 3:
                    metadata = yaml.safe_load(parts[1]) or {}
                    content = parts[2].strip()

            # Déterminer le doc_type depuis la structure du dossier
            relative = md_file.relative_to(corpus_root)
            inferred_type = relative.parts[0] if len(relative.parts) > 1 else "general"

            documents.append({
                "id": metadata.get("id") or md_file.stem,
                "path": str(md_file.relative_to(ROOT)).replace("\\", "/"),
                "doc_type": metadata.get("doc_type") or inferred_type,
                "artifact_type": metadata.get("artifact_type") or inferred_type,
                "content": content,
                "metadata": metadata,
            })
        except Exception as exc:
            logger.warning("Erreur lecture %s : %s", md_file, exc)

    # Charger aussi les fichiers YAML/YML et exemples de code
    for ext in ("*.yml", "*.yaml"):
        for yaml_file in sorted(corpus_root.rglob(ext)):
            try:
                relative = yaml_file.relative_to(corpus_root)
                folder = relative.parts[0] if len(relative.parts) > 1 else "general"

                if doc_type_filter and doc_type_filter.lower() not in folder.lower():
                    continue

                content = yaml_file.read_text(encoding="utf-8").strip()
                if not content or len(content) < 50:
                    continue

                documents.append({
                    "id": f"yaml_{yaml_file.stem}",
                    "path": str(yaml_file.relative_to(ROOT)).replace("\\", "/"),
                    "doc_type": folder,
                    "artifact_type": folder,
                    "content": content,
                    "metadata": {},
                })
            except Exception as exc:
                logger.warning("Erreur lecture YAML %s : %s", yaml_file, exc)

    logger.info("Documents chargés : %d fichiers", len(documents))
    return documents


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingestion du corpus DevSecOps dans Qdrant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--reset", action="store_true",
                        help="Supprimer et recréer la collection Qdrant")
    parser.add_argument("--doc-type", metavar="TYPE",
                        help="Ingérer uniquement ce type (docker, k8s, terraform, cicd, cloud…)")
    parser.add_argument("--no-gemini", action="store_true",
                        help="Désactiver le chunking Gemini (fallback simple)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Logs détaillés")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    print("\n" + "=" * 60)
    print("  INGEST QDRANT — DevSecOps Knowledge Base")
    print("=" * 60)

    # ── 1. Vérifier Qdrant ──────────────────────────────────────────────────
    print("\n[1/5] Connexion à Qdrant…")
    qdrant = QdrantService(
        url=rag_config.qdrant_url,
        collection_name=rag_config.qdrant_collection,
        vector_size=rag_config.qdrant_vector_size,
    )
    health = qdrant.health_check()
    if health.get("status") != "ok":
        print(f"  ERREUR — Qdrant inaccessible : {health}")
        print("  Vérifiez que Qdrant tourne : docker ps | grep qdrant")
        return 1
    print(f"  OK — Qdrant {rag_config.qdrant_url}")

    # ── 2. Créer/recréer la collection ──────────────────────────────────────
    print(f"\n[2/5] Collection '{rag_config.qdrant_collection}' …")
    if not qdrant.create_collection(recreate=args.reset):
        print("  ERREUR — Impossible de créer la collection")
        return 1
    info = qdrant.collection_info()
    existing_points = info.get("points_count", 0)
    print(f"  OK — {existing_points} points existants")

    # ── 3. Vérifier Ollama ───────────────────────────────────────────────────
    print("\n[3/5] Vérification Ollama…")
    embedder = EmbeddingService(
        ollama_base_url=rag_config.ollama_base_url,
        model=rag_config.ollama_embed_model,
    )
    embed_health = embedder.health_check()
    if embed_health.get("status") == "error":
        print(f"  ERREUR — Ollama inaccessible : {embed_health.get('error')}")
        print(f"  URL configurée : {rag_config.ollama_base_url}")
        print("  Lancez Ollama : ollama serve")
        return 1
    if embed_health.get("status") == "model_missing":
        print(f"  AVERTISSEMENT — Modèle '{rag_config.ollama_embed_model}' non trouvé.")
        print(f"  Installez-le : ollama pull {rag_config.ollama_embed_model}")
        print(f"  Modèles disponibles : {embed_health.get('available_models')}")
    else:
        print(f"  OK — {rag_config.ollama_embed_model} disponible")

    # ── 4. Charger le corpus ─────────────────────────────────────────────────
    print(f"\n[4/5] Chargement du corpus depuis '{rag_config.corpus_path}'…")
    corpus_path = Path(rag_config.corpus_path)
    documents = load_corpus(corpus_path, doc_type_filter=args.doc_type)

    if not documents:
        print(f"  Aucun document trouvé dans {corpus_path}")
        print("  Vérifiez RAG_CORPUS_PATH dans .env")
        return 1
    print(f"  {len(documents)} documents trouvés")

    # ── 5. Chunking ──────────────────────────────────────────────────────────
    print("\n[5/5] Chunking sémantique…")
    gemini_available = bool(rag_config.gemini_api_key) and not args.no_gemini

    if gemini_available:
        print(f"  Mode : Gemini ({rag_config.gemini_model})")
        chunker = GeminiChunkingService(
            api_key=rag_config.gemini_api_key,
            model=rag_config.gemini_model,
        )
    else:
        print("  Mode : Fallback simple (Gemini non configuré ou désactivé)")
        chunker = GeminiChunkingService(api_key="", model="")

    all_chunks: list[dict] = []
    for idx, doc in enumerate(documents):
        if args.verbose:
            logger.debug("  Chunking [%d/%d] : %s", idx + 1, len(documents), doc["path"])
        chunks = chunker.chunk_document(
            content=doc["content"],
            source=doc["path"],
            doc_type=doc["doc_type"],
        )
        all_chunks.extend(chunks)

        # Pas de pause supplémentaire ici — le service gère lui-même le rate limiting

    print(f"  {len(all_chunks)} chunks produits (moy. {len(all_chunks) / max(len(documents), 1):.1f} / doc)")

    # ── 6. Embedding ─────────────────────────────────────────────────────────
    print("\n  Génération des embeddings (Ollama)…")
    t0 = time.time()
    chunks_with_embeddings = embedder.embed_chunks(all_chunks)
    elapsed = time.time() - t0

    valid = [c for c in chunks_with_embeddings if c.get("embedding") and any(c["embedding"])]
    print(f"  {len(valid)} embeddings générés en {elapsed:.1f}s")

    if not valid:
        print("  ERREUR — Aucun embedding valide généré")
        return 1

    # ── 7. Upsert dans Qdrant ────────────────────────────────────────────────
    print("\n  Upsert dans Qdrant…")
    inserted = qdrant.upsert_documents(valid)

    # ── Résumé ───────────────────────────────────────────────────────────────
    info = qdrant.collection_info()
    print("\n" + "=" * 60)
    print("  INGESTION TERMINÉE")
    print(f"  Documents  : {len(documents)}")
    print(f"  Chunks     : {len(all_chunks)}")
    print(f"  Insérés    : {inserted}")
    print(f"  Total coll.: {info.get('points_count', '?')} points")
    print(f"  Collection : {rag_config.qdrant_collection}")
    print(f"  Qdrant     : {rag_config.qdrant_url}")
    print("=" * 60 + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
