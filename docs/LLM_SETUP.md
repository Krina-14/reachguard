# ReachGuard — LLM Setup & Provider Configuration

ReachGuard follows the architectural principle:
> **The graph decides, the model explains.**
> All reachability paths, verdicts, and risk scores are computed deterministically. The LLM is used strictly to choose query tools and explain graph findings. If the LLM is slow, down, or offline, the product continues to function normally in deterministic mode.

---

## 1. Local Ollama (Recommended / Default)

Best for private, offline, zero-cost, hardware-accelerated local execution.

### Prerequisites
- Install Ollama:
  - macOS: `curl -fsSL https://ollama.com/install.sh | sh` or download from [ollama.com/download](https://ollama.com/download)
  - Linux: `curl -fsSL https://ollama.com/install.sh | sh`
  - Windows: `irm https://ollama.com/install.ps1 | iex`

### Pulling Models
For machines with 8 GB – 16 GB RAM / Apple Silicon (e.g. M1/M2/M3/M4):
```bash
# Ultra-fast lightweight model:
ollama pull llama3.2:3b

# Standard ReachGuard model (or alias):
ollama cp llama3.2:3b qwen2.5:7b-instruct
```

### Environment Configuration (`backend/.env`)
```env
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:7b-instruct
LLM_API_KEY=
LLM_TIMEOUT_S=60
```

---

## 2. Free Hosted Alternatives (For Teammates Without GPU / Low RAM)

Any OpenAI-compatible completions API can be used by updating environment variables. **Never commit API keys to Git.**

### Option A: Groq (Ultra-Fast Free Tier)
- **Sign up**: [console.groq.com](https://console.groq.com)
- **Get API Key**: Create a free API key under API Keys.
- **Configure `backend/.env`**:
  ```env
  LLM_PROVIDER=openai_compat
  LLM_BASE_URL=https://api.groq.com/openai/v1
  LLM_MODEL=llama-3.3-70b-versatile
  LLM_API_KEY=gsk_your_groq_api_key_here
  LLM_TIMEOUT_S=30
  ```

### Option B: OpenRouter (Free Models Tier)
- **Sign up**: [openrouter.ai](https://openrouter.ai)
- **Get API Key**: Create a key under Keys.
- **Configure `backend/.env`**:
  ```env
  LLM_PROVIDER=openai_compat
  LLM_BASE_URL=https://openrouter.ai/api/v1
  LLM_MODEL=meta-llama/llama-3.2-3b-instruct:free
  LLM_API_KEY=sk-or-v1-your_openrouter_key
  LLM_TIMEOUT_S=60
  ```

### Option C: Ollama Cloud (`gemma4:cloud` Free Plan)
- **Sign in**: Run `ollama signin` or visit [ollama.com/settings/keys](https://ollama.com/settings/keys).
- **Configure `backend/.env`**:
  ```env
  LLM_PROVIDER=openai_compat
  LLM_BASE_URL=https://ollama.com/v1
  LLM_MODEL=gemma4:cloud
  LLM_API_KEY=your_ollama_cloud_key
  LLM_TIMEOUT_S=60
  ```

---

## 3. Deterministic Mode (No LLM Required)

If you do not want to run an LLM at all, ReachGuard will execute all graph traversals, reachability calculations, and scoring purely deterministically without making any network calls:

```env
LLM_PROVIDER=none
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=none
LLM_API_KEY=
LLM_TIMEOUT_S=60
```

---

## 4. Verification

Test the LLM connection and health status from the backend directory:
```bash
./.venv/bin/python -c "
from app.agent.llm import get_client
print(get_client().health())
"
```

Expected output when live:
```python
{'provider': 'ollama', 'model': 'qwen2.5:7b-instruct', 'reachable': True, 'mode': 'llm'}
```
