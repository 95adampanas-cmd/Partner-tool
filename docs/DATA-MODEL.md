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

## Otwarte pytania

1. **Czym jest „persona"?** Osoba decyzyjna (imię + stanowisko ze strony)? Czy typ profilu
   klienta firmy? To zmienia i prompt, i wartość dla maila. → **wymaga decyzji**
2. **Nazwy kolumn Pipedrive** — jakie dokładnie pola ma import? Bez tego mapowanie jest zgadywaniem.
3. **Braki danych** — PRD mówi „nie do ustalenia" zamiast zgadywania. Potwierdzić, że to literalna
   wartość w CSV (spójna, filtrowalna), nie puste pole.
4. **Konkurent** — sama flaga `true/false`, czy flaga + uzasadnienie? (patrz definicja w DECISIONS)
