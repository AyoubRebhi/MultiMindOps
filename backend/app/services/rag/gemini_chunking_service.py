"""
Chunking sémantique avec l'API Gemini.

Au lieu d'un découpage fixe (ex: 1200 chars), Gemini analyse le document et
produit des chunks cohérents qui préservent les blocs de code, YAML et configs.

Chaque chunk est enrichi avec :
  - title       : titre court décrivant le contenu
  - content     : texte du chunk
  - chunk_type  : code | config | prose | yaml | security_rule
  - keywords    : mots-clés extraits
  - context_tag : tag haut-niveau (docker | k8s | terraform | cicd | security | cloud)
"""

from __future__ import annotations

import json
import logging
import re
import textwrap
import time
from typing import Any

logger = logging.getLogger(__name__)

# Délai minimum entre deux appels Gemini (free tier : 15 req/min max)
_INTER_CALL_DELAY = 5.0   # secondes
_MAX_RETRY_WAIT   = 90.0  # secondes max en cas de 429

# ── Prompt envoyé à Gemini ───────────────────────────────────────────────────
_CHUNK_SYSTEM_PROMPT = textwrap.dedent("""\
    Tu es un expert en DevSecOps. Ton rôle est de découper un document technique en
    chunks sémantiques cohérents pour un système RAG (Retrieval-Augmented Generation).

    RÈGLES IMPÉRATIVES :
    1. Chaque chunk doit être autonome et compréhensible sans contexte extérieur.
    2. Ne jamais couper un bloc de code, une section YAML ou une configuration au milieu.
    3. Regrouper les règles de sécurité liées dans un même chunk.
    4. Taille recommandée : 200–600 tokens par chunk. Maximum absolu : 900 tokens.
    5. Si une section est trop longue, la diviser logiquement (ex : par sous-thème).

    TYPES DE CHUNKS :
    - "code"          : extrait de code (Dockerfile, script shell, Python…)
    - "config"        : configuration (docker-compose, Helm, .env…)
    - "yaml"          : manifeste Kubernetes, GitHub Actions workflow
    - "security_rule" : règle ou recommandation de sécurité (CIS, OWASP…)
    - "prose"         : texte explicatif, best practice, documentation

    FORMAT DE RÉPONSE — JSON uniquement, tableau d'objets :
    [
      {
        "title": "Titre court du chunk",
        "content": "Contenu complet du chunk",
        "chunk_type": "code|config|yaml|security_rule|prose",
        "keywords": ["mot1", "mot2", "mot3"],
        "context_tag": "docker|k8s|terraform|cicd|security|cloud|general"
      },
      ...
    ]

    Réponds UNIQUEMENT avec le JSON. Pas de texte avant ni après.
""")


class GeminiChunkingService:
    """Service de chunking sémantique utilisant l'API Gemini avec support dual-key."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-1.5-flash",
        api_key_2: str | None = None,
        requests_per_key: int = 20,
    ):
        """
        Initialise le service Gemini avec support dual API key.

        Args:
            api_key:           Première clé API Gemini.
            model:             Modèle Gemini à utiliser.
            api_key_2:         Deuxième clé API (optionnelle) pour continuous chunking.
            requests_per_key:  Nombre de requêtes max par clé (généralement 20).
        """
        self._api_key_1 = api_key
        self._api_key_2 = api_key_2
        self._current_api_key = api_key
        self._requests_per_key = requests_per_key
        self._request_count = 0
        self._model = model
        self._available = False

        try:
            from google import genai  # type: ignore
            self._genai_module = genai
            self._client = genai.Client(api_key=self._current_api_key)
            self._available = bool(api_key and api_key.strip())
        except Exception as exc:
            logger.warning("Gemini SDK non disponible : %s — fallback activé", exc)
            self._client = None
            self._available = False

    # ── Gestion des clés API multiples ────────────────────────────────────────

    def _switch_api_key(self) -> bool:
        """
        Bascule vers la deuxième clé API si disponible et quota atteint.

        Returns:
            True si basculement effectué, False sinon.
        """
        if self._request_count >= self._requests_per_key and self._api_key_2:
            if self._current_api_key == self._api_key_1:
                self._current_api_key = self._api_key_2
                self._request_count = 0
                try:
                    self._client = self._genai_module.Client(api_key=self._current_api_key)
                    logger.info(
                        "Basculement vers clé API 2 | Quota clé 1 épuisé (%d requêtes)",
                        self._requests_per_key,
                    )
                    return True
                except Exception as exc:
                    logger.error("Impossible de basculer vers clé 2 : %s", exc)
                    return False
        return False

    def _increment_request_count(self) -> None:
        """Incrémente le compteur de requêtes et bascule si nécessaire."""
        self._request_count += 1
        if self._request_count >= self._requests_per_key:
            self._switch_api_key()

    # ── API publique ─────────────────────────────────────────────────────────

    def chunk_document(
        self,
        content: str,
        source: str,
        doc_type: str,
    ) -> list[dict[str, Any]]:
        """Découpe un document en chunks sémantiques.

        Args:
            content:  Texte brut du document.
            source:   Chemin ou identifiant du fichier source.
            doc_type: Type de document (docker, k8s, terraform, cicd, security, cloud…).

        Returns:
            Liste de chunks enrichis avec métadonnées.
        """
        if not content.strip():
            return []

        if self._available and self._client is not None:
            chunks = self._gemini_chunk(content, source, doc_type)
        else:
            chunks = self._fallback_chunk(content, source, doc_type)

        # Injecter les métadonnées communes
        for idx, chunk in enumerate(chunks):
            chunk["source"] = source
            chunk["doc_type"] = doc_type
            chunk["chunk_index"] = idx
            chunk.setdefault("chunk_type", "prose")
            chunk.setdefault("context_tag", doc_type)
            chunk.setdefault("keywords", [])
            chunk.setdefault("title", f"{source} — chunk {idx + 1}")

        return chunks

    def chunk_documents(
        self,
        documents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Découpe une liste de documents.

        Args:
            documents: Liste de dicts avec au minimum les clés
                       ``content``, ``path`` / ``source``, ``doc_type``.

        Returns:
            Liste aplatie de tous les chunks.
        """
        all_chunks: list[dict[str, Any]] = []
        for doc in documents:
            source = doc.get("path") or doc.get("source") or "unknown"
            doc_type = doc.get("doc_type") or doc.get("artifact_type") or "general"
            content = doc.get("content") or ""
            try:
                chunks = self.chunk_document(content, source, doc_type)
                all_chunks.extend(chunks)
            except Exception as exc:
                logger.error("Erreur chunking document %s : %s", source, exc)
        return all_chunks

    # ── Chunking Gemini ──────────────────────────────────────────────────────

    def _gemini_chunk(
        self,
        content: str,
        source: str,
        doc_type: str,
        retries: int = 2,
    ) -> list[dict[str, Any]]:
        user_prompt = (
            f"Document source : {source}\n"
            f"Type de document : {doc_type}\n\n"
            f"--- DOCUMENT ---\n{content}\n--- FIN DOCUMENT ---\n\n"
            "Découpe ce document selon les règles définies."
        )

        for attempt in range(retries + 1):
            try:
                from google.genai import types as genai_types  # type: ignore

                response = self._client.models.generate_content(
                    model=self._model,
                    contents=user_prompt,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=_CHUNK_SYSTEM_PROMPT,
                        temperature=0.1,
                        max_output_tokens=8192,
                    ),
                )
                # Délai poli après chaque appel réussi
                time.sleep(_INTER_CALL_DELAY)
                raw_text = response.text.strip()
                self._increment_request_count()  # Incrémenter après succès
                return self._parse_gemini_response(raw_text, source, doc_type)

            except Exception as exc:
                exc_str = str(exc)
                # Extraire le retryDelay suggéré par l'API (en secondes)
                retry_delay = self._parse_retry_delay(exc_str)

                if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str:
                    if "PerDay" in exc_str or "limit: 0" in exc_str:
                        # Quota journalier épuisé — essayer la clé 2
                        logger.warning(
                            "Quota journalier Gemini épuisé pour %s (clé actuelle)", source
                        )
                        if self._switch_api_key():
                            # Réessayer avec la nouvelle clé
                            if attempt < retries:
                                logger.info("Retry avec clé API 2 pour %s", source)
                                continue
                        break
                    if attempt < retries:
                        wait = min(retry_delay or (15 * (attempt + 1)), _MAX_RETRY_WAIT)
                        logger.info(
                            "Gemini rate-limit 429 pour %s — attente %.0fs (essai %d/%d)",
                            source, wait, attempt + 1, retries,
                        )
                        time.sleep(wait)
                        continue

                logger.warning(
                    "Gemini chunking échoué pour %s (%s) — fallback activé", source, exc
                )
                break

        return self._fallback_chunk(content, source, doc_type)

    @staticmethod
    def _parse_retry_delay(exc_str: str) -> float | None:
        """Extrait le retryDelay (en secondes) depuis le message d'erreur Gemini."""
        # Format: "retryDelay': '13s'" ou "retryDelay: 13.5s"
        match = re.search(r"retryDelay['\"]?\s*:\s*['\"]?\s*(\d+(?:\.\d+)?)\s*s", exc_str)
        if match:
            return float(match.group(1))
        return None

    def _parse_gemini_response(
        self,
        raw_text: str,
        source: str,
        doc_type: str,
    ) -> list[dict[str, Any]]:
        """Extrait le JSON de la réponse Gemini (tolère les blocs markdown)."""
        # Enlever les balises markdown si présentes
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()

        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                valid = []
                for item in data:
                    if isinstance(item, dict) and item.get("content"):
                        valid.append(item)
                return valid
        except json.JSONDecodeError as exc:
            logger.warning("JSON invalide pour %s : %s", source, exc)

        return self._fallback_chunk(
            raw_text, source, doc_type  # utilise le texte brut comme fallback
        )

    # ── Fallback (découpage simple) ──────────────────────────────────────────

    def _fallback_chunk(
        self,
        content: str,
        source: str,
        doc_type: str,
        max_chars: int = 800,
    ) -> list[dict[str, Any]]:
        """Découpage par blocs (sections markdown ou taille fixe)."""
        sections = self._split_by_markdown_sections(content)
        chunks: list[dict[str, Any]] = []

        for section_title, section_body in sections:
            if not section_body.strip():
                continue
            # Si la section est trop grande, on la redécoupe
            sub_blocks = self._split_by_size(section_body, max_chars)
            for block in sub_blocks:
                if not block.strip():
                    continue
                chunks.append(
                    {
                        "title": section_title or f"{source} — extrait",
                        "content": block.strip(),
                        "chunk_type": self._detect_chunk_type(block),
                        "keywords": self._extract_keywords(block),
                        "context_tag": doc_type,
                    }
                )
        return chunks

    # ── Utilitaires ──────────────────────────────────────────────────────────

    @staticmethod
    def _split_by_markdown_sections(
        content: str,
    ) -> list[tuple[str, str]]:
        """Découpe par sections markdown (## Titre)."""
        lines = content.splitlines(keepends=True)
        sections: list[tuple[str, str]] = []
        current_title = ""
        current_body: list[str] = []

        for line in lines:
            if re.match(r"^#{1,3}\s+", line):
                if current_body:
                    sections.append((current_title, "".join(current_body)))
                current_title = line.strip("# \n")
                current_body = []
            else:
                current_body.append(line)

        if current_body:
            sections.append((current_title, "".join(current_body)))

        # Si aucune section trouvée, retourner le tout
        if not sections:
            sections = [("", content)]
        return sections

    @staticmethod
    def _split_by_size(text: str, max_chars: int) -> list[str]:
        if len(text) <= max_chars:
            return [text]
        blocks: list[str] = []
        start = 0
        while start < len(text):
            end = start + max_chars
            # Essayer de couper sur un saut de ligne
            if end < len(text):
                newline = text.rfind("\n", start, end)
                if newline > start:
                    end = newline + 1
            blocks.append(text[start:end])
            start = end
        return blocks

    @staticmethod
    def _detect_chunk_type(text: str) -> str:
        stripped = text.strip()
        if re.search(r"^(FROM|RUN|CMD|ENTRYPOINT|COPY|ADD|ENV|EXPOSE)\s", stripped, re.M):
            return "code"
        if re.search(r"^(apiVersion|kind|metadata|spec):", stripped, re.M):
            return "yaml"
        if re.search(r"^(services|version|volumes|networks):", stripped, re.M):
            return "config"
        if re.search(r"```", stripped):
            return "code"
        if re.search(r"\b(CIS|OWASP|CVE|vulnerability|secret|password|encrypt)\b", stripped, re.I):
            return "security_rule"
        return "prose"

    @staticmethod
    def _extract_keywords(text: str, max_keywords: int = 8) -> list[str]:
        words = re.findall(r"[a-zA-Z]{4,}", text.lower())
        stopwords = {
            "that", "this", "with", "from", "have", "will", "your",
            "should", "must", "when", "then", "each", "into", "also",
        }
        seen: dict[str, int] = {}
        for word in words:
            if word not in stopwords:
                seen[word] = seen.get(word, 0) + 1
        return sorted(seen, key=lambda w: -seen[w])[:max_keywords]
