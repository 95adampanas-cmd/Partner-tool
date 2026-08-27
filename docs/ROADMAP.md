# ROADMAP — Partner Tool

> Status: ⬜ do zrobienia · 🟡 w toku · ✅ zrobione
> Terminy z PRD: **Faza 1 → 30.09.2026** · Faza 2 → 10.10.2026 · walidacja → 15.10.2026

## Faza 0 — Setup 🟡
- ✅ PRD v1.0 (przeniesione do `docs/PRD.md`)
- ✅ Struktura repo + dokumenty
- ⬜ Repo na GitHub + pierwszy push
- ⬜ **Domknięcie luk z recenzji PRD** (model danych, persona, definicja konkurenta)
- ⬜ `.env` z kluczami (OPENAI_API_KEY, TAVILY/TVLY_API_KEY)

## Faza 1 — Rdzeń MVP (termin: 30.09.2026) ⬜

### F1 — Research firmy po URL
- ⬜ Scraper **wielostronicowy** (nie tylko homepage — patrz DECISIONS)
- ⬜ Ekstrakcja danych przez LLM → structured output wg `DATA-MODEL.md`
- ⬜ Flaga konkurenta (SEO/GEO) wg definicji „oferta rdzeniowa vs wzmianka poboczna"
- ⬜ Obsługa braków: „nie do ustalenia" zamiast halucynacji
- ⬜ Karta firmy w UI

### F2 — Szukaj podobnych
- ⬜ Tavily + **deterministyczny filtr** (blocklist katalogów/rankingów, dedup domen)
- ⬜ Lista klikalna → otwiera firmę w nowej zakładce (bez pola URL)

### F3 — Generowanie draftu maila
- ⬜ **Baza wiedzy mailingu** (`docs/email-examples.md`) — zależność, do zebrania przez PM
- ⬜ 3 propozycje maila + „generuj nowe"

### F4 — Eksport CSV
- ⬜ Zaznaczanie firm do eksportu
- ⬜ Mapowanie pól na kolumny Pipedrive
- ⬜ **Download w przeglądarce** (nie zapis serwerowy — dysk Render jest efemeryczny)

### Wdrożenie
- ⬜ Render + zmienne środowiskowe
- ⬜ Walidacja na próbce z zespołem

## Faza 2 — Mikroaudyt SEO/GEO (termin: 10.10.2026) ⬜
- ⬜ DataForSEO: Labs (pozycje/ruch) + SERP z AI Overview + AI Search
- ⬜ Raport PDF gotowy do przekazania partnerowi

## Faza 3+ — odłożone
Patrz PRD sekcja 6.

---

**Aktualnie pracujemy nad:** Faza 0 — domknięcie luk z recenzji PRD
