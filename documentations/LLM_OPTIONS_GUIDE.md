# Modèles LLM Gratuits - Options pour CodebaseAnalysisAgent

## TL;DR - Les 3 Meilleures Options

| Option | Modèle | Vitesse | Qualité | Setup |
|--------|--------|---------|---------|-------|
| **1. Ollama (Local)** 🔥 | Mistral 7B | ⚡⚡⚡ Fast | ⭐⭐⭐⭐ Very Good | Simple |
| **2. Groq API (Already using!)** | Mixtral 8x7B | ⚡⚡⚡⚡ Fastest | ⭐⭐⭐⭐⭐ Best | 1 line code |
| **3. Hugging Face (Cloud Free)** | Zephyr 7B | ⚡⚡ Medium | ⭐⭐⭐⭐ Good | API key |
| **4. Llama 2 (Meta)** | 7B or 13B | ⚡⚡ Medium | ⭐⭐⭐⭐ Good | Ollama/HF |

---

## Option 1: Ollama (Recommended pour YOU) 🏆

### Pourquoi?
- ✅ **Déjà utilisé** dans votre codebase (embeddings)
- ✅ **Gratuit** (open-source)
- ✅ **Local** (aucune coûte API, données privées)
- ✅ **Rapide** (GPU/CPU support)
- ✅ **Modèles variés** (7B à 70B)
- ✅ **Compatible** avec votre `LLMService`

### Installation

**Windows/Mac/Linux:**
```bash
# Installer Ollama
# https://ollama.ai

# Télécharger modèle (premier run = ~10 min)
ollama pull mistral:7b          # 4.7 GB, excellent qualité/vitesse
# ou
ollama pull neural-chat:7b      # 4.7 GB, optimisé pour chat
# ou
ollama pull llama2:7b           # 3.8 GB, bon pour raison

# Lancer serveur
ollama serve
# → API sur http://localhost:11434
```

### Modèles Disponibles (Taille + Temps Réponse)

```
Model              | Size   | Speed    | Quality | Use Case
─────────────────────────────────────────────────────────────
mistral:7b        | 4.7GB  | 50ms     | ⭐⭐⭐⭐⭐ | Best balance
neural-chat:7b    | 4.7GB  | 60ms     | ⭐⭐⭐⭐⭐ | Chat optimized
llama2:7b         | 3.8GB  | 80ms     | ⭐⭐⭐⭐  | General
dolphin-mixtral   | 26GB   | 200ms    | ⭐⭐⭐⭐⭐ | Strongest (need GPU)
```

### Intégration avec votre Code

**Actuellement (Groq):**
```python
# backend/app/services/core/llm_service.py
class LLMService:
    def __init__(self):
        self.client = Groq(api_key=settings.GROQ_API_KEY)
        self.model = "llama-3.3-70b-versatile"

    def chat_json(self, system_prompt, user_prompt, ...):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[...],
            ...
        )
```

**Option A: Utiliser Ollama avec même LLMService (switch)**
```python
class LLMService:
    def __init__(self):
        # Switch facile:
        use_ollama = settings.LLM_PROVIDER == "ollama"

        if use_ollama:
            import requests
            self.base_url = "http://localhost:11434"
            self.model = "mistral:7b"  # Fast + good
        else:
            self.client = Groq(api_key=settings.GROQ_API_KEY)
            self.model = "llama-3.3-70b-versatile"

    def chat_json(self, system_prompt, user_prompt, ...):
        if use_ollama:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": f"{system_prompt}\n\n{user_prompt}",
                    "stream": False
                }
            ).json()
            return {"content": response["response"]}
        else:
            # Existing Groq code
```

**Option B: Use Ollama via LangChain (1 import change)**
```python
from langchain.llms import Ollama

llm = Ollama(
    model="mistral:7b",
    base_url="http://localhost:11434"
)

response = llm.invoke("Your prompt here")
```

### Configuration Minimale (.env)

```env
# Switch LLM provider
LLM_PROVIDER=ollama          # or "groq"
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=mistral:7b

# Keep Groq as fallback
GROQ_API_KEY=...            # For production
```

### Test Rapide

```bash
# Terminal 1: Start Ollama
ollama serve

# Terminal 2: Test
curl http://localhost:11434/api/generate -d '{
  "model": "mistral:7b",
  "prompt": "List 5 important files in a React+Node.js monorepo"
}'

# Response in ~5 seconds
```

---

## Option 2: Groq API (Vous l'utilisez déjà!) ⚡

### Avantages
- ✅ **Déjà configured** dans votre `.env`
- ✅ **GRATUIT** (tier 5000 req/jour)
- ✅ **Très rapide** (spécialisé pour inference)
- ✅ **API cloud** (pas de setup local)
- ✅ **Meilleur qualité** (mixtral 8x7b VS mistral 7b)

### Déjà Utilisé Dans Votre Code

```python
# backend/app/services/core/llm_service.py
from groq import Groq

class LLMService:
    def __init__(self):
        self.client = Groq(api_key=settings.GROQ_API_KEY)
        self.model = "llama-3.3-70b-versatile"  # ou mixtral-8x7b
```

### Modèles Groq Gratuits

```
Model                    | Size      | Speed  | Quota Free
──────────────────────────────────────────────────────
mixtral-8x7b-32768      | 56 tokens | FAST   | 5000 req/day ✅
llama2-70b-4096         | 70B       | Very fast | 5000 req/day ✅
llama-3.3-70b-versatile | Modern    | Super fast | 5000 req/day ✅
gemma-7b-it             | 7B GPT-like| Med   | 5000 req/day ✅
```

### Cost Estimate for Your Use Case

```
CodebaseAnalysisAgent workflow:

1. LLMPriorityEngine
   Input: ~2KB (quick scan)
   Output: ~500B (priority list)
   Cost: ~0.01¢ (free tier)

2. Analysis per repo: 1-2 LLM calls
   100 repos/day = 100-200 free api calls (vs 5000 quota)

→ COMPLETELY FREE (unless >5000 req/day)
```

### No Setup Required

```python
# Already in your codebase - just use it!
from backend.app.services.core.llm_service import LLMService

llm = LLMService()
response = llm.chat_json(
    system_prompt="You are a DevSecOps engineer...",
    user_prompt="Analyze this repo structure..."
)
```

---

## Option 3: Hugging Face Inference API (Cloud Free)

### Setup

```bash
# 1. Create account: https://huggingface.co
# 2. Get free API key
# 3. Install client
pip install huggingface-hub

# 4. Test model
from huggingface_hub import InferenceClient

client = InferenceClient(
    model="HuggingFaceH4/zephyr-7b-beta",  # Free tier model
    token="hf_YOUR_TOKEN"
)

response = client.text_generation(
    "List important files in React monorepo",
    max_new_tokens=500
)
```

### Limitation
- ❌ **Rate limited** (10 req/min free)
- ❌ **Slower** (shared cloud)
- ❌ **Cold starts** (first request = 10sec)
- ✅ **Zero setup**

---

## Option 4: LLaMA.cpp (CPU-Only Local)

### Quand UTILISER?
- Pas de GPU
- Besoin d'offline
- Pas de quota Groq

### Installation

```bash
# Clone llama.cpp
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
make

# Download quantized model (GGUF format)
# Mistral 7B Q4 = 4.5GB (fast + low memory)
wget https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.1-GGUF/...

# Run
./main -m mistral-7b-instruct-v0.1.Q4_K_M.gguf \
  -p "List important files in a monorepo" \
  -n 256
```

### Limitations
- ⚠️ **Very slow** (5-10 tokens/sec sur CPU)
- ⚠️ **CPU intensive**
- ✅ Zero API cost

---

## Recommendation for YOUR Project

### Stack Actuel
```
✅ Groq API (FREE)
✅ Ollama local (Embeddings + petit chat LLM)
```

### Proposé: Hybrid Approach

```python
# backend/app/core/config.py

# Production: Use Groq (free tier, very fast)
LLM_PROVIDER = "groq"  # 5000 req/day free

# Development: Use Ollama local (instant, no quota)
LLM_PROVIDER = "ollama"
OLLAMA_MODEL = "mistral:7b"

# Fallback: Chain them
try:
    response = groq_llm.invoke(prompt)  # Try fast cloud first
except RateLimitError:
    response = ollama_llm.invoke(prompt)  # Fall back to local
```

### Implementation Plan

```python
# 1. Create abstract LLMProvider

class LLMProvider(ABC):
    @abstractmethod
    def chat_json(self, system, user, temp=0.3, max_tokens=1500) -> dict:
        pass

# 2. Implement both

class GroqProvider(LLMProvider):
    def __init__(self):
        self.client = Groq(api_key=settings.GROQ_API_KEY)

    def chat_json(self, ...):
        response = self.client.chat.completions.create(
            model="mixtral-8x7b-32768",  # Fast + free quota
            messages=[...],
            temperature=0.3,
            max_tokens=1500
        )
        return json.loads(response.choices[0].message.content)

class OllamaProvider(LLMProvider):
    def __init__(self):
        self.url = "http://localhost:11434"

    def chat_json(self, system, user, ...):
        response = requests.post(
            f"{self.url}/api/chat",
            json={
                "model": "mistral:7b",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ]
            }
        ).json()
        return json.loads(response["message"]["content"])

# 3. Factory

class LLMService:
    def __init__(self):
        provider = settings.LLM_PROVIDER  # "groq" or "ollama"

        if provider == "groq":
            self._provider = GroqProvider()
        elif provider == "ollama":
            self._provider = OllamaProvider()

    def chat_json(self, system, user, **kwargs):
        return self._provider.chat_json(system, user, **kwargs)
```

### Cost Analysis for 100 repos/day

```
Scenario 1: Groq only (Current)
├─ 5000 req/day free
├─ CodebaseAnalysisAgent: 100-200 req/day
└─ Cost: $0 ✅

Scenario 2: Ollama only (Local)
├─ 1 server (8GB RAM min)
├─ Electric bill: ~$50/month
└─ Cost: ~$50/month for 100 repos/day (cheap!)

Scenario 3: Hybrid (Recommended)
├─ Groq quota: 100-200/day (free)
├─ Ollama fallback: Free (local)
└─ Cost: $0 initially ✅
```

---

## Quick Comparison Table

```
┌─────────────────────────────────────────────────────────────────┐
│ FEATURE                 │ OLLAMA     │ GROQ   │ HF       │ LLAMA.CPP
├─────────────────────────────────────────────────────────────────┤
│ Setup Time              │ 10 min     │ 1 min  │ 5 min   │ 30 min
│ Model Quality (7B)      │ ⭐⭐⭐⭐  │ ⭐⭐⭐⭐⭐│ ⭐⭐⭐⭐ │ ⭐⭐⭐⭐
│ Speed (Latency)         │ 50-100ms   │ 10ms   │ 500ms   │ 5-10s
│ Cost                    │ $0 (local) │ $0 (*) │ $0 (*)  │ $0 (CPU)
│ Privacy                 │ ✅ Full    │ ❌ Cloud│ ❌ Cloud│ ✅ Full
│ Internet Required       │ ❌ No      │ ✅ Yes │ ✅ Yes │ ❌ No
│ GPU Support             │ ✅ Yes     │ ✅ Yes │ ✅ Yes │ ⚠️ Optional
│ For Production          │ ⭐⭐⭐⭐  │ ⭐⭐⭐⭐⭐│ ✅ OK  │ ⚠️ Slow
│ For Development         │ ⭐⭐⭐⭐⭐ │ ✅ OK  │ ✅ OK  │ ⭐⭐⭐
│ Already Using?          │ ✅ YES     │ ✅ YES │ ❌ No  │ ❌ No

(*) Free tier with limits (5000 req/day = plenty for you)
```

---

## My Recommendation for You 👇

### Short Term (Next Week)
```
Use Groq (already configured)
├─ Zero setup
├─ Free tier enough for 100 repos/day
├─ 10ms latency (fast!)
└─ No local setup needed

Just implement:
  class LLMPriorityEngine:
      def rank_importance(self, quick_scan, user_prompt):
          response = self.llm.chat_json(
              system_prompt="You are a DevSecOps architect...",
              user_prompt=f"This repo has: {quick_scan}. Rank top 10 files"
          )
          return response["critical_files"]
```

### Medium Term (Next Month)
```
Add Ollama for development
├─ Pull mistral:7b locally
├─ Use for testing (instant, no quota)
├─ Switch via .env (LLM_PROVIDER)
└─ Fallback chain: Groq → Ollama

Example .env:
  # Dev
  LLM_PROVIDER=ollama
  OLLAMA_BASE_URL=http://localhost:11434

  # Prod
  LLM_PROVIDER=groq
  GROQ_API_KEY=...
```

### Long Term (Production)
```
Ollama on dedicated server
├─ GPU instance (cheaper than cloud LLM APIs)
├─ 100% cost control
├─ Privacy guaranteed
└─ Unlimited requests

Or: Keep Groq (simplest, they handle scaling)
```

