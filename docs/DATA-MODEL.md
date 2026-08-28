# DATA MODEL — rekord firmy

> ⚠️ **DO UZUPEŁNIENIA — to najważniejsza luka w PRD v1.0.**
> W PRD Funkcja 1 (research) i Funkcja 4 (eksport) wymieniają **różne listy pól**.
> Bez jednego kanonicznego schematu ekstrakcja, widok i eksport się rozjadą.
>
> Ten plik = jedno źródło prawdy dla: promptu ekstrakcji, karty firmy w UI i kolumn CSV.

## Rozjazd do rozstrzygnięcia

| Pole | Funkcja 1 (research) | Funkcja 4 (eksport CSV) |
|------|:--------------------:|:-----------------------:|
| nazwa firmy | (nie wymieniona) | ✅ |
| URL | wejście | ? |
| wielkość zespołu | ✅ | ❌ |
| portfolio usług | ✅ | ✅ (usługi) |
| branża | ✅ | ❌ |
| case studies | ✅ | ❌ |
| liczba projektów | ✅ | ❌ |
| dane kontaktowe | ✅ | ✅ |
| persona | ✅ | ✅ |
| konkurent SEO/GEO | ✅ | ✅ |

➡️ **Decyzja do podjęcia:** czy eksport ma węższy zakres niż research (świadomie), czy to przeoczenie?

## Schemat (szkic do zatwierdzenia)

| Pole | Typ | Źródło | Wymagane | Kolumna CSV (Pipedrive) |
|------|-----|--------|:--------:|-------------------------|
| `nazwa` | str | scrape/LLM | tak | Organization |
| `url` | str | input usera | tak | Website |
| `branza` | str | LLM | tak | ? |
| `uslugi` | list[str] | LLM | tak | ? |
| `wielkosc_zespolu` | str \| "nie do ustalenia" | LLM | nie | ? |
| `liczba_projektow` | str \| "nie do ustalenia" | LLM | nie | ? |
| `case_studies` | list[str] | LLM | nie | ? |
| `telefon` | str \| "nie do ustalenia" | LLM (tylko ze strony) | nie | Phone |
| `email` | str \| "nie do ustalenia" | LLM (tylko ze strony) | nie | Email |
| `persona` | ? **(definicja niejasna)** | LLM | ? | ? |
| `konkurent` | bool + uzasadnienie | LLM | tak | ? |
| `zrodlo_danych` | str (które podstrony) | scraper | tak | — |

## ✅ Rozstrzygnięte

**Persona = dane OSOBY DECYZYJNEJ** (decyzja Adama, 2026-08-28). Nie profil klienta firmy.
Rozbita na 4 pola, bo do Pipedrive trafia jako osobny rekord osoby:

| Pole | Opis |
|------|------|
| `persona_imie` | imię i nazwisko |
| `persona_stanowisko` | rola (CEO, właściciel, founder, dyrektor) |
| `persona_email` | JEJ bezpośredni mail (nie ogólnofirmowy) |
| `persona_telefon` | JEJ bezpośredni telefon |

Zasada wyboru: osoba **najwyżej w hierarchii** (właściciel/CEO przed managerem).
Szukamy w sekcjach „o nas", „zespół", „kontakt". Brak nazwiska → wszystkie pola `nie do ustalenia`.

**Braki danych** = literalny string `"nie do ustalenia"` (spójny, filtrowalny w arkuszu), nie puste pole.

**Konkurent** = flaga `true/false` + `konkurent_uzasadnienie` (na jakiej podstawie).

## Otwarte pytania

1. **Nazwy kolumn Pipedrive** — jakie dokładnie pola ma import? Bez tego mapowanie w `KOLUMNY`
   (`app.py`) jest zgadywaniem. Obecny szkic: `Organization / Website / Phone / Email /
   Person name / Person position / Person email / Person phone / ...`
