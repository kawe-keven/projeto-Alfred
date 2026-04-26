<div align="center">

# Alfred AI
### Integrated Multi-Agent OS Assistant

*An intelligent, developer-focused productivity assistant that sees your screen, hears your voice, remembers your context, and monitors your environment — all running natively on your machine.*

---

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev)
[![Gemini](https://img.shields.io/badge/Gemini_2.5_Flash-Free_Tier-4285F4?style=flat-square&logo=google&logoColor=white)](https://aistudio.google.com)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Local_RAG-FF6B35?style=flat-square)](https://www.trychroma.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

</div>

---

## Overview

Alfred is a modular, multi-agent AI system built for developers who want a personal assistant that operates at the OS level — not just in a chat window. It integrates **language understanding**, **long-term memory**, **screen vision**, **voice interaction**, and **proactive environmental monitoring** into a single cohesive platform, served through a neumorphic React dashboard.

The architecture is designed around a **zero-cost stack**: Google Gemini 2.5 Flash (free tier) handles LLM inference, ChromaDB with local Sentence-Transformers handles vector memory, and all other components run fully offline.

---

## Tech Stack

### Backend
| Layer | Technology | Role |
|---|---|---|
| Runtime | **Python 3.10+** | Application language |
| API Framework | **FastAPI 0.110+** | REST endpoints + WebSocket server |
| LLM | **Google Gemini 2.5 Flash** | Primary inference engine (free, 1 500 req/day) |
| LLM Fallback | **Ollama (llama3.2)** | 100% offline local inference |
| Agent Orchestration | **LangChain** | Message pipelines, prompt templating |
| Long-term Memory | **ChromaDB** | Local persistent vector database |
| Embeddings | **Sentence-Transformers** (`all-MiniLM-L6-v2`) | Local embeddings, no API cost |
| System Metrics | **psutil** | CPU, RAM, disk, network monitoring |
| Screen Vision | **PyAutoGUI + PIL** | Screenshot capture and analysis |
| Voice — TTS | **pyttsx3** (offline primary) + **gTTS** (fallback) | Text-to-speech synthesis |
| Voice — STT | **SpeechRecognition** (Google Web Speech) | Speech-to-text transcription |

### Frontend
| Layer | Technology | Role |
|---|---|---|
| Framework | **React 18 + TypeScript** | UI component architecture |
| Build Tool | **Vite** | Fast HMR development server |
| Styling | **Tailwind CSS 3** + custom neumorphism tokens | Design system |
| HTTP Client | **Axios** | REST API communication |
| Icons | **lucide-react** | Consistent iconography |
| Real-time | **Native WebSocket** | Live notifications and alerts |

### External Integrations
| Service | Provider | Usage |
|---|---|---|
| Weather | **OpenWeatherMap** (free tier) | Current conditions + climate alerts |
| News | **RSS / feedparser** | Technology headline briefings |
| Calendar | **iCal / local** | Daily schedule for morning briefing |
| Git | **subprocess + gitpython** | Repository status and commit assistance |

---

## Agent Architecture

Alfred operates through a **central orchestrator** that classifies incoming intents and routes them to specialized agents. Each agent is independently stateless, extending a common `BaseAgent` interface.

```
User Input (Voice / Chat)
        │
        ▼
┌─────────────────────┐
│   AlfredOrchestrator │  ← Intent classification + session memory
│   (core/orchestrator)│
└──────────┬──────────┘
           │
    ┌──────┴──────────────────────────────────────┐
    │              Agent Router                    │
    └──┬──────┬──────┬──────┬──────┬──────────────┘
       │      │      │      │      │
       ▼      ▼      ▼      ▼      ▼
  General  System  Vision   Dev  Integration
   Agent   Agent   Agent  Agent    Agent
```

### `GeneralAgent`
The conversational core. Handles open-ended questions, explanations, and reasoning tasks. Connects directly to the configurable LLM provider (Gemini / Ollama / OpenAI legacy) via LangChain, injecting relevant RAG context from ChromaDB into every response.

### `SystemAgent`
OS-level awareness. Reports CPU, RAM, disk usage, and running processes using **psutil**. Can trigger system-level warnings and feeds data into the proactive monitoring pipeline.

### `VisionAgent`
Grants Alfred sight. Captures the current screen state via **PyAutoGUI**, encodes the image, and sends it to the multimodal LLM for analysis. Enables commands like *"what's on my screen?"* or *"summarize this document"*.

### `DevAgent`
Developer workflow assistant. Manages Git repositories — reporting uncommitted changes, generating **Conventional Commits** message suggestions from `git diff`, and summarizing `.py` / `.tsx` source files for documentation. Stores detected tech stack fingerprints in ChromaDB for cross-session context.

### `IntegrationAgent`
External world bridge. Aggregates weather (multi-city), RSS news, and calendar events into a structured **morning briefing**. Detects climate anomalies (temperature > 32 °C or storm conditions) and dispatches real-time alerts via WebSocket. Includes a **"Status do Lab"** section powered by DevAgent for the daily development standup.

### `MonitorService`
Always-on background daemon. Runs independently of user interaction, sampling system metrics and environmental conditions on a configurable interval. Pushes proactive `GlassNotification` events through the WebSocket channel (`/ws/notifications`) directly to the frontend — no polling required.

---

## Engineering Highlights

### Vector Memory & RAG
Alfred maintains persistent long-term memory using a fully local RAG pipeline. Every conversation turn is embedded with `all-MiniLM-L6-v2` (~22 MB model, no API cost) and stored in ChromaDB's SQLite-backed persistent store. On each new query, the top-K semantically similar memories are retrieved and injected into the system prompt, giving Alfred genuine context continuity across sessions, reboots, and days.

The database is **loaded, not rebuilt**, on startup — the boot script verifies the existence of `memory/vector_db/chroma.sqlite3` before launching the backend, eliminating unnecessary re-indexing overhead and reducing boot-time RAM pressure.

### Multimodal Capability
Alfred operates across three input modalities simultaneously:
- **Text** — standard chat via the React dashboard
- **Voice** — continuous STT via `SpeechRecognition` with pyttsx3 TTS response (fully offline)
- **Vision** — on-demand screen capture analyzed by the multimodal LLM

### Proactive Monitoring via WebSockets
Rather than relying on client-side polling, Alfred's `MonitorService` maintains a persistent WebSocket connection to the frontend. System alerts, climate warnings, and calendar reminders are **pushed in real-time** as structured `GlassNotification` objects, keeping the UI reactive with zero latency overhead.

### Zero-Cost Architecture
The default configuration runs entirely on free-tier or local services:
- **Gemini 2.5 Flash**: 15 RPM, 1 500 requests/day — sufficient for personal use
- **ChromaDB + Sentence-Transformers**: 100% local, no API calls
- **Ollama**: fully offline LLM fallback, zero external dependencies
- **pyttsx3**: offline TTS, no cloud synthesis

---

## Installation

### Prerequisites
- Python 3.10+
- Node.js 18+
- Git

### 1. Clone and configure environment

```bash
git clone <your-repo-url> alfred
cd alfred

# Copy and edit the environment file
cp .env.example .env
```

Open `.env` and fill in your keys:

```dotenv
# Required: get your free key at https://aistudio.google.com
GEMINI_API_KEY=your_gemini_api_key_here

# Required for weather: https://openweathermap.org/api
OPENWEATHERMAP_API_KEY=your_openweathermap_key_here

# Optional: run `ollama pull llama3.2` for offline fallback
OLLAMA_BASE_URL=http://localhost:11434
```

### 2. Create Python virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

> **Note:** On first run, Sentence-Transformers will download the `all-MiniLM-L6-v2` model (~22 MB). This is a one-time operation.

### 3. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### 4. Launch Alfred

```bash
# Option A: Single-command launcher (Windows — recommended)
run_alfred.bat

# Option B: Manual
# Terminal 1 — Backend
uvicorn main:app --host 0.0.0.0 --port 8000

# Terminal 2 — Frontend
cd frontend && npm run dev
```

Open **http://localhost:5173** in your browser.

---

## Auto-Start on Windows Boot

To have Alfred greet you every morning automatically:

1. Press `Win + R`, type `shell:startup`, press Enter
2. Right-click inside the folder → **New → Shortcut**
3. Set the target to the full path of `run_alfred.bat`:
   ```
   "C:\path\to\alfred\run_alfred.bat"
   ```
4. Right-click the shortcut → **Properties** → set *Run* to `Minimized`

Alfred will initialize silently in the background on login, open the dashboard in your browser, and deliver your morning briefing within seconds.

---

## Project Structure

```
alfred/
├── main.py                    # FastAPI entrypoint, WebSocket hub
│
├── core/
│   ├── config.py              # Pydantic settings (env-driven)
│   ├── orchestrator.py        # Intent routing and session management
│   ├── intent_classifier.py   # Keyword + ML intent classification
│   ├── monitor_service.py     # Background daemon — proactive alerts
│   └── voice_engine.py        # TTS/STT abstraction layer
│
├── agents/
│   ├── base_agent.py          # Abstract BaseAgent interface
│   ├── general_agent.py       # Conversational LLM agent
│   ├── system_agent.py        # OS metrics via psutil
│   ├── vision_agent.py        # Screen capture + multimodal analysis
│   ├── dev_agent.py           # Git + code workflow assistant
│   └── integration_agent.py   # Weather, news, calendar, briefing
│
├── memory/
│   ├── memory_manager.py      # Short-term SQLite session memory
│   └── vector_store.py        # Long-term ChromaDB RAG memory
│
├── frontend/
│   └── src/
│       ├── App.tsx             # Root layout and WebSocket listener
│       └── components/         # Neumorphic UI components
│
├── logs/                      # Runtime logs (auto-generated)
│   ├── backend.log
│   ├── frontend.log
│   └── boot.log
│
├── run_alfred.bat              # One-click Windows launcher
├── requirements.txt
└── .env.example
```

---

## API Reference

A complete interactive API reference is available at **http://localhost:8000/docs** (Swagger UI) when the backend is running.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Service health check |
| `POST` | `/chat` | Send a message to Alfred |
| `GET` | `/session/{id}` | Retrieve conversation history |
| `DELETE` | `/session/{id}` | Clear a session |
| `WebSocket` | `/ws/notifications` | Real-time push notification stream |

---

## Configuration Reference

Key variables in `.env`:

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | LLM backend: `gemini` \| `ollama` \| `openai` |
| `MODEL_NAME` | `gemini-2.5-flash-preview-04-17` | Model identifier |
| `GEMINI_API_KEY` | — | Google AI Studio API key (free) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Local Ollama server |
| `TEMPERATURE` | `0.7` | LLM response creativity (0.0–1.0) |
| `WEATHER_CITIES` | `["Aracaju","Laranjeiras"]` | Cities for weather widget |
| `VECTOR_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Local embedding model |
| `VECTOR_TOP_K` | `3` | Memory fragments retrieved per query |

---

<div align="center">

*Built with precision. Ready at boot. Always in context.*

</div>
