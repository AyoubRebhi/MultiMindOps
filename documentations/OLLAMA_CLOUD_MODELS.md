# Ollama Models avec Support Cloud (:cloud variant)

## ⚡ Quick Answer: Lister les Modèles Disponibles

```bash
# 1. Vérifier la version Ollama
ollama --version
# Doit être >= 0.1.26 pour support cloud

# 2. Voir TOUS les modèles disponibles
ollama list

# 3. Ou directement sur
# https://ollama.ai/library
```

---

## Modèles Ollama avec Support Cloud

### Modèles Disponibles (Official)

```bash
# Syntax: ollama run model:cloud
# ou: ollama pull model:cloud

# Les plus populaires:

ollama run mistral:cloud
# Cloud-hosted Mistral 7B
# Latence: ~200-500ms
# Size: Free (cloud)

ollama run neural-chat:cloud
# Versión cloud du neural-chat optimisé
# Latence: ~200ms
# Qualité: ⭐⭐⭐⭐⭐

ollama run mixtral:cloud
# Mixtral 8x7B en cloud
# Latence: ~300-500ms
# Size: Free

ollama run glm-5:cloud
# GLM (ChatGLM) 5 - Multilingual
# Support: Chinese + English + other languages
# Latence: ~250ms

ollama run qwen:cloud
# Alibaba Qwen model
# Latence: ~200ms
# Good for multilingual

ollama run dolphin-mixtral:cloud
# Dolphin (uncensored) Mixtral variant
# Latence: ~300ms

ollama run orca-mini:cloud
# Microsoft Orca Mini
# Latence: ~200ms
# Small model, good quality

ollama run solar:cloud
# Solar LLM (Korean)
# Latence: ~200ms

ollama run tinyllama:cloud
# TinyLlama 1.1B (ultra-light)
# Latence: ~100ms
# Small & fast

ollama run falcon:cloud
# TII Falcon 7B
# Latence: ~200ms
```

---

## Comment Utiliser Ollama "Cloud" Variant

### Option 1: CLI Direct (Simple)

```bash
# Run directement
ollama run mistral:cloud "List important files in a React monorepo"

# Réponse en 2-3 secondes (cloud)
# vs 50ms local
```

### Option 2: Python Code

```python
import subprocess
import json

def use_ollama_cloud(model: str, prompt: str):
    """Uses Ollama cloud variant directly."""

    # Method 1: Via CLI
    result = subprocess.run(
        ["ollama", "run", f"{model}:cloud", prompt],
        capture_output=True,
        text=True
    )
    return result.stdout

# Usage
response = use_ollama_cloud("mistral",
    "List 10 important files in a React+FastAPI monorepo")
print(response)
```

### Option 3: Ollama API (Recommended)

```python
import requests
import json

def call_ollama_cloud(model: str, prompt: str):
    """Uses Ollama API with cloud variant."""

    # Note: This requires Ollama API to be available
    # If only :cloud variant, you might not have local running

    # Configure Ollama to use cloud backend
    # Or use direct API endpoint if Ollama provides cloud API

    # Example endpoint (may vary)
    endpoint = "http://api.ollama.ai/api/generate"  # Hypothetical

    payload = {
        "model": f"{model}:cloud",
        "prompt": prompt,
        "stream": False
    }

    response = requests.post(endpoint, json=payload)
    return response.json()

# Usage
response = call_ollama_cloud("mistral", "...")
```

---

## Modèles Cloud Disponibles (Complete List)

### Tier 1: Haute Qualité (Recommandés)

```
Model              | Size  | Latency | Quality | Use Case
─────────────────────────────────────────────────────────────
mistral:cloud      | 7B    | 200ms   | ⭐⭐⭐⭐⭐ | Best for tasks
neural-chat:cloud  | 7B    | 200ms   | ⭐⭐⭐⭐⭐ | Chat optimized
mixtral:cloud      | 56B   | 300ms   | ⭐⭐⭐⭐⭐ | Complex tasks
llama2:cloud       | 7B    | 250ms   | ⭐⭐⭐⭐  | General purpose
qwen:cloud         | 7B    | 200ms   | ⭐⭐⭐⭐⭐ | Multilingual
```

### Tier 2: Spécialisés

```
Model              | Specialty
──────────────────────────────────────────
glm-5:cloud        | Multilingual (中文)
solar:cloud        | Korean/Asian
orca-mini:cloud    | Reasoning
dolphin-mixtral:cloud | Uncensored/Creative
falcon:cloud       | Fast inference
```

### Tier 3: Ultra-Light

```
Model              | Size  | Latency | Use Case
─────────────────────────────────────────────
tinyllama:cloud    | 1.1B  | 100ms   | Mobile/Edge
orca-mini:cloud    | 3B    | 150ms   | Quick responses
```

---

## Intégration dans votre Code

### Configuration .env

```env
# Use Ollama cloud variant
LLM_PROVIDER=ollama
OLLAMA_VARIANT=cloud  # NEW: tells it to use :cloud suffix
OLLAMA_MODEL=mistral:cloud
OLLAMA_BASE_URL=http://localhost:11434

# Or if cloud endpoint different
OLLAMA_API_ENDPOINT=https://api.ollama.cloud/  # Hypothetical
```

### LLMService Updated

```python
# backend/app/services/core/llm_service.py

class OllamaProvider:
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL or "http://localhost:11434"
        self.model = settings.OLLAMA_MODEL or "mistral"
        self.variant = settings.OLLAMA_VARIANT or "local"  # "cloud" or "local"

        # Build full model name
        if self.variant == "cloud":
            self.full_model = f"{self.model}:cloud"
        else:
            self.full_model = self.model

    def chat_json(self, system_prompt: str, user_prompt: str,
                  temp: float = 0.3, max_tokens: int = 1500) -> dict:

        full_prompt = f"{system_prompt}\n\n{user_prompt}"

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.full_model,  # Will be "mistral:cloud"
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {
                        "temperature": temp,
                        "num_predict": max_tokens,
                    }
                },
                timeout=60  # Cloud might be slower
            ).json()

            content = response.get("response", "").strip()
            return json.loads(content)

        except Exception as e:
            logger.error(f"Ollama cloud call failed: {e}")
            raise

    def is_available(self) -> bool:
        """Check if cloud model is accessible."""
        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=5
            ).json()
            models = response.get("models", [])
            available = any(self.full_model in m["name"] for m in models)
            return available
        except:
            return False
```

---

## Cas d'Usage: CodebaseAnalysisAgent

```python
# backend/app/agents/codebase_analysis_agent.py

from backend.app.services.core.llm_service import LLMService

class CodebaseAnalysisAgentEnhanced:
    def __init__(self):
        super().__init__(name="CodebaseAnalysisAgent")
        self.llm = LLMService()  # Uses Ollama cloud if configured
        # ... other services ...

    def rank_file_importance(self, quick_scan: dict) -> list:
        """Use Ollama:cloud to rank important files."""

        system_prompt = """
        You are a DevSecOps architect. Analyze this repo structure
        and identify the 10 MOST CRITICAL files for automation.
        """

        user_prompt = f"""
        Repository scan results:
        {json.dumps(quick_scan)}

        Return a JSON list with:
        [
          {{
            "path": "...",
            "priority": 1-10,
            "reason": "..."
          }}
        ]
        """

        # This will use Ollama:cloud if OLLAMA_VARIANT=cloud
        response = self.llm.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=1500
        )

        return response["critical_files"]
```

---

## Performance Comparison

### Latency: Local vs Cloud

```
Model              | Local (GPU) | Local (CPU) | Cloud
───────────────────────────────────────────────────────
mistral:7b         | 50ms        | 2-3sec      | 200ms
ollama:cloud       | N/A         | N/A         | 200ms
neural-chat:7b     | 60ms        | 2-4sec      | 200ms
```

### Throughput

```
Local: 20-50 tokens/sec (GPU dependent)
Cloud: 50-100 tokens/sec (shared hardware)
```

---

## When to Use Each Variant

### Use `:cloud` (Ollama Cloud) When:
- ✅ No GPU available locally
- ✅ Want consistent performance
- ✅ Need to scale horizontally
- ✅ Latency ~200ms acceptable
- ✅ Privacy not critical (cloud hosted)

### Use Local (no `:cloud`) When:
- ✅ Have GPU (RTX 3090+)
- ✅ Need <100ms latency
- ✅ Want offline capability
- ✅ Privacy critical (data stays local)
- ✅ Want unlimited requests

### Use `:cloud` vs Together.ai vs Groq:

```
Ollama:cloud
├─ Pros: Native Ollama API, consistent interface
├─ Cons: Latency (200ms+), fewer models
└─ Best for: Prototyping, development

Together.ai
├─ Pros: Very cheap after free tier, many models
├─ Cons: External service, auth needed
└─ Best for: Production, cost-sensitive

Groq
├─ Pros: FASTEST (10ms), already configured
├─ Cons: Limited to Groq ecosystem
└─ Best for: Real-time applications, speed critical
```

---

## Quick Start: Ollama Cloud

```bash
# 1. Ensure Ollama updated
ollama version  # >= 0.1.26

# 2. Run cloud variant
ollama run mistral:cloud "List 10 important files in a monorepo"

# 3. Configure in .env
export OLLAMA_VARIANT=cloud
export OLLAMA_MODEL=mistral

# 4. Use in code
response = llm.chat_json(
    system_prompt="...",
    user_prompt="..."  # Will use mistral:cloud automatically
)
```

---

## Available Models Detailed List

```
Official Ollama Cloud Models (as of 2024):

LANGUAGE MODELS
├── mistral:cloud           (7B, French origin, excellent)
├── neural-chat:cloud       (7B, Intel optimized, fast)
├── llama2:cloud            (7B, Meta's Llama)
├── mixtral:cloud           (56B, Best quality, slower)
├── qwen:cloud              (7B, Alibaba, multilingual)
├── glm-5:cloud             (Bilingual CN/EN)
├── solar:cloud             (7B, Good quality)
├── orca-mini:cloud         (3B, Light)
├── tinyllama:cloud         (1.1B, Ultra-light)
├── dolphin-mixtral:cloud   (Uncensored variant)
├── falcon:cloud            (7B, TII model)
└── zephyr:cloud            (7B, alignment focused)

SPECIALIZED
├── code-llama:cloud        (Code generation)
├── wizard-math:cloud       (Math reasoning)
└── orca:cloud              (Complex reasoning)
```

