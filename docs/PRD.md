# PRD — Partner Tool

**Wersja:** 1.0 · **Autor:** Adam Panas · **Data:** 2026-08-27
**Dokumenty powiązane:** Discovery v1.0, Charter v1.0

> Źródło prawdy dla zakresu produktu. Zmiana zakresu → aktualizuj ten plik + wpis w [DECISIONS.md](DECISIONS.md).

## 1. Co to jest

Partner Tool to narzędzie AI dla działu relacji partnerskich, które znajduje i opisuje nowe,
wartościowe firmy partnerskie — w tym te o niewielkich nakładach na marketing, niewidoczne
na topowych pozycjach w Google. Rozwiązuje główny ból zespołu: **dopływ nowych, wartościowych
prospektów do lejka partnerskiego.**

## 2. Problem

Dotarcie do nowych organizacji, które nie pozycjonują się na topowych pozycjach w Google.
Brak prospektów w lejku wstrzymuje realizację celu działu — przychód generowany przez leady
zdobyte od partnerów.

## 3. Użytkownik

**Partnership Manager** — manager średniego szczebla. Odpowiada za pozyskiwanie, utrzymanie
i obsługę partnerów (referral, white-label) oraz research i pracę z portfelem partnerów.

Rozumie technologię, używa Trello/Pipedrive i podstawowo AI — **nie programuje.**

**Implikacja produktowa:** interfejs prosty (wklej URL → dostań wynik), bez konfiguracji technicznej.

## 4. Cel produktu

Dostarczyć narzędzie, które rozwiązuje dopływ nowych, wartościowych prospektów; skraca proces
researchu, oceny i weryfikacji portfolio oraz konkurencyjności; przygotowuje CSV powiększony
o dane kontaktowe i dane spółki.

## 5. Funkcje

### Funkcja 1 — Research firmy po URL (MVP)
**Co robi:**
- user wkleja URL → scraper pobiera stronę → LLM wyciąga: wielkość zespołu, portfolio usług,
  branża, case studies, liczba projektów, dane kontaktowe + persona
- oznacza konkurenta (SEO/GEO tak/nie)
- **NIE ocenia wartości** (user ocenia sam)

**Ból:** ryzyko zaangażowania w konkurenta · ręczne szukanie kontaktów · rozproszone dane o firmie.

### Funkcja 2 — Szukaj podobnych (MVP)
**Co robi:**
- po wklejeniu URL i kliknięciu przycisku → LLM (via Tavily lub podobne API) analizuje usługi/opis
  firmy i szuka firm podobnych
- znalezione firmy trafiają do widoku, z którego można je od razu zresearchować (Funkcja 1)

**Ból (centralny):** brak pomysłów, gdzie szukać nowych firm. Zasila pipeline bez wymyślania fraz.

### Funkcja 3 — Generowanie draftu maila (MVP)
**Co robi:**
- po researchu → przycisk generuje **3 propozycje maila** do skopiowania
- generowane na podstawie **pliku z przykładowymi mailami** (baza wiedzy mailingu) → spójny styl

**Ból:** ręczne pisanie każdego maila od zera pod branżę.

### Funkcja 4 — Eksport do CSV / Sheets (MVP)
**Co robi:**
- po akceptacji usera (przycisk) dodaje firmę ze wszystkimi danymi (nazwa, usługi, kontakt,
  persona, konkurent tak/nie) jako rekord do CSV/Sheets — gotowy pod import do Pipedrive

**Ból:** ręczne przepisywanie prospektów do Pipedrive.

### Funkcja 5 — Mikroaudyt SEO/GEO na żądanie (MVP Faza 2)
**Co robi:** na żądanie generuje raport o widoczności firmy (wzór: audyty ICEA), w 3 warstwach:
- **widoczność SEO** — pozycje TOP3, ruch organiczny, konkurenci (DataForSEO Labs API)
- **widoczność w AI Overviews** — obecność w odpowiedziach AI Google (DataForSEO SERP API)
- **wzmianki w chatbotach** — ChatGPT/Perplexity (DataForSEO AI Search API)

**Ból (poboczny):** wartość dodana dla partnera zamiast samej oferty. Dziś ręcznie ~0,5h/audyt,
~10h/mies. przy 20 audytach — wąskie gardło.

*Faza 2 — po ukończeniu rdzenia (Faza 1: research + podobne + mail + eksport).*

## 6. Poza zakresem

**Faza 3+ (odłożone, wrócą):**
- Szukaj po Google Maps / Google (branża + miasto) — Tryb B
- Szukanie nowych po KRS (+ rozstrzygnięcie KRS vs CEIDG)
- Dane z KRS API · dane finansowe z BizRaport API · baza Clutch
- Maile — pełna wersja (warianty, czat do poprawy, biblioteka)
- Czat do pogłębienia researchu
- Pętla nauki / rozwoju LLM
- Logowanie, pamięć sesji, przechowywanie wyników i baz

**Odrzucone (sprawdzone, wykluczone):**
- **Scoring / ocena wartości firmy** — świadomie usunięty; ocenę robi user
- **Zarządzanie relacją / CRM** — zostaje w Pipedrive
- **LinkedIn API** — zakaz prospectingu, ban za obejścia
- **Instagram API** — brak API do odkrywania firm
- **Clay** — API od ~$495/mies., za drogo

## 7. Jak działa — flow MVP

1. User wchodzi do aplikacji webowej i wkleja URL organizacji.
2. Narzędzie researchuje firmę: scraper pobiera treść strony, agent LLM wyciąga dane —
   portfolio usług, realizacje, case studies, branża, kontakt, persona. Dodatkowo oznacza,
   czy firma jest konkurentem (SEO/GEO) — **samo oznaczenie, nie wpływa na zakres danych.**
3. User sam ocenia, czy organizacja nadaje się na partnera (referral / white-label).
4. User klika **„szukaj podobnych"** (Tavily) → lista ok. 10 firm zbliżonych produktowo.
   Lista klikalna: kliknięcie otwiera firmę **w nowej zakładce**, z tym samym widokiem i funkcjami,
   ale bez pola URL. Każda firma dostaje pełną kartę analizy.
5. Dla wybranej firmy user klika **„generuj mail"** → propozycje dopasowane do branży,
   na bazie pliku z przykładowymi mailami. Można wygenerować nowe.
6. User zaznacza, którą organizację dodać do eksportu. Dokument ma **predefiniowane, nazwane pola**
   (mapowanie na kolumny) gotowe pod import do Pipedrive.
7. Koniec ścieżki — user importuje plik do Pipedrive, gdzie prowadzi dalszą relację.

## 8. Wymagania techniczne

**Formaty wyjściowe:** CSV / Google Sheets (pod import do Pipedrive) · mikroaudyt: PDF (Faza 2)

**Stack:** Backend Python · Frontend JS/HTML/CSS · Hosting Render · LLM OpenAI (+ SDK/framework agenta)

**Integracje:**
- Faza 1: własny scraper + Tavily
- Faza 2: DataForSEO API (Labs + SERP z AI Overview + AI Search)
- Faza 3+: Google Places API, KRS API, BizRaport API, Clutch, Supabase (SQL + auth)

**Zasady/ograniczenia:**
- budżet API + tokeny: **do ~500 zł/mies.**
- **deterministyczne zadania jako zwykłe funkcje, nie tool calle LLM** (tokeny, niezawodność)
- baza wiedzy mailingu (plik z przykładami) jako input do generowania maili
- brak logowania / bazy danych w MVP

## 9. Metryki sukcesu (KPI)

**Mierzone przez zespół (walidacja na próbce):**
- min. **40 nowych wartościowych firm/mies.** (zaakceptowanych jako sensowni prospekci)
- „szukaj podobnych": trafność **min. 60%** (6/10 firm zasadnych)
- wykrywanie konkurenta: **min. 80%** poprawnych identyfikacji
- mikroaudyt (Faza 2): gotowy bez istotnych poprawek w **min. 70%** przypadków

**Mierzone w użyciu:**
- min. **60%** wygenerowanych maili użytych do kontaktu (bez istotnych przeróbek)
- skrócenie czasu procesu o **min. 50%** (z ~14-17h do ~7-8h/mies.)
- odciążenie analityka przy mikroaudytach (z ~10h/mies.)

**Techniczne/kosztowe:** koszt API + tokeny **poniżej ~500 zł/mies.**

**Terminy:** MVP Faza 1 — **30.09.2026** · MVP Faza 2 — **10.10.2026** · walidacja — **15.10.2026**

## 10. Ryzyka produktowe

- **Halucynacje danych** — LLM może zmyślić kontakt/portfolio/personę.
  *Mitygacja:* „nie do ustalenia" zamiast zgadywania; weryfikacja krytycznych pól.
- **Blokada scrapera** — JS/Cloudflare.
  *Mitygacja:* alternatywne źródła (Faza 3+); docelowo scraper renderujący JS; oznaczanie firmy jako niedostępnej.
- **Trafność „szukaj podobnych"** — nietrafione firmy lub konkurenci.
  *Mitygacja:* walidacja na próbce, dostrajanie promptów i zapytań.
- **Jakość danych DataForSEO** (Faza 2) — niepełne dla małych/lokalnych firm.
  *Mitygacja:* oznaczać braki, nie zgadywać.
- **Koszt API/tokenów** — wzrost powyżej progu.
  *Mitygacja:* tańsze modele do prostych zadań, funkcje deterministyczne, monitoring vs ~500 zł/mies.

## 11. Historia zmian

**Wersja 1.0 — 2026-08-27**
Pierwsze PRD Partner Tool. Zakres MVP: research po URL, szukaj podobnych, generowanie maila,
eksport CSV (Faza 1) + mikroaudyt SEO/GEO na DataForSEO (Faza 2). Scoring wartości usunięty —
ocenę robi user; wykrywanie konkurenta zostaje. Źródła KRS/Google Maps/BizRaport → Faza 3+.
