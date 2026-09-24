# Partner Tool

Narzędzie AI dla działu relacji partnerskich: **research firmy po URL → szukaj podobnych →
draft maila → eksport CSV pod Pipedrive.** Narzędzie dostarcza dane — ocenę robi user.

## Architektura

```
Frontend (HTML/CSS/JS)          Backend (Python)
  karta firmy, lista       →  API  →  scraper + LLM (OpenAI) + Tavily
  podobnych, eksport       ←        ←  deterministyczne funkcje (filtr, CSV)
```

## Struktura

```
backend/     Python — scraper, agent LLM, API
frontend/    aplikacja webowa
docs/        dokumentacja produktu (źródło prawdy)
```

## Dokumentacja

- [PRD.md](docs/PRD.md) — co budujemy i po co (v1.0)
- [ROADMAP.md](docs/ROADMAP.md) — fazy i status
- [DECISIONS.md](docs/DECISIONS.md) — log decyzji + otwarte pytania
- [DATA-MODEL.md](docs/DATA-MODEL.md) — schemat rekordu firmy ⚠️ do domknięcia
- [maile-do-partnerow.md](docs/maile-do-partnerow.md) — wzorce maili do partnerów (zależność F3)

## Szybki start (backend)

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env      # i wpisz klucze
uvicorn app:app --reload
```
→ http://localhost:8000
