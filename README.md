# NightyNight

> *"We are such stuff as dreams are made on."* — Shakespeare

AI-generated bedtime stories, narrated and ready to listen to. Pick any topic — the origin of the universe, ancient civilizations, deep-sea biology — and NightyNight turns it into a calm audio story made for the moment your body is ready to rest, but your mind still wants one more thing.

---

## Why this exists

My girlfriend sometimes struggles with insomnia. Most nights she asks me to tell her stories before she falls asleep — about cosmology, evolution, ancient cities, the history of Earth. I love telling them, but I usually fall asleep mid-sentence before she does.

That's the problem NightyNight solves.

---

## How it works

1. **Choose a topic**
2. **Set the mood** — length, narrator voice, and who you're listening for
3. **A story is written and narrated for you** — in real time
4. **Listen with your eyes closed**

---

## Stack

React · Three.js · FastAPI · LangGraph · Google Gemini · ElevenLabs · Cloudflare R2 · Neon Postgres

---

## Local setup

```bash
# Milvus (vector store for RAG)
docker-compose up -d

# Backend
cd langgraph && pip install -r requirements.txt
cp .env.example .env   # fill in API keys
uvicorn src.api.server:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev
```

---

*Built for my fiance who wanted someone to finish the story.*
