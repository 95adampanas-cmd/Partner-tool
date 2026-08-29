# Mikroaudyt SEO/GEO — struktura raportu (Faza 2)

> Wzorzec: audyt ICEA „Analiza GEO (SEO & AI Search)" + rekomendacje specjalisty z zespołu.
> Ten plik jest **specyfikacją** dla generatora raportu i mapą: która sekcja z jakiego źródła.
> KPI z PRD: raport gotowy do wysłania **bez istotnych poprawek w min. 70% przypadków**.

## Zasada nadrzędna

Sekcje dzielą się na **stałe** (treść edukacyjna, ta sama dla każdego klienta — zero kosztu API)
i **dynamiczne** (dane o konkretnej domenie — płatne wywołania). Stałe piszemy raz w szablonie,
dynamiczne pobieramy per audyt. To najtańszy możliwy model.

---

## 1. RAPORT ZERO — widoczność w Google

| Element | Treść | Źródło | Koszt |
|---|---|---|---|
| Widoczność w TOP3 | liczba fraz w TOP3 + trend | Labs: Ranked Keywords (filtr pozycja ≤ 3) | dynam. |
| Estymowany ruch organiczny | liczba sesji/mies. + wykres trendu | Labs: Domain Rank Overview (`etv`) | dynam. |
| Konkurenci — tabela | domena, wspólne frazy, overlap, ruch, zmiana | Labs: Competitors Domain | dynam. |
| Strony z potencjałem | ile podstron widocznych na ≥1 frazę + trend | Labs: Relevant Pages | dynam. |

**Komentarze analityka do odtworzenia w szablonie:**
- przy trendzie spadkowym: *„Przy dobrze prowadzonych działaniach SEO liczba podstron generujących
  ruch powinna wzrastać w czasie"* — generujemy warunkowo, zależnie od kierunku trendu
- pod tabelą konkurencji: *„Jeśli na liście nie ma Państwa najbliższego konkurenta, oznacza to,
  że strona nie jest zaindeksowana na właściwe wyrażenia kluczowe"*

---

## 2. RAPORT WIDOCZNOŚCI AI OVERVIEW

| Element | Treść | Źródło | Koszt |
|---|---|---|---|
| Wstęp edukacyjny | AIO obejmuje **24,17%** zapytań w PL; polskie serwisy straciły **23,7 mln** kliknięć (V–VI 2025); **65,9%** cytowań pochodzi z TOP3 | **STAŁE** | 0 |
| Przykład AI Overview | zrzut/rendering przykładowego AIO | STAŁE (grafika) | 0 |
| Czy domena ma AIO | obecność AI Overview dla fraz marki | SERP Advanced (`item_types: ai_overview`) | dynam. |
| Liczba wzmianek AIO | ile fraz z AIO, gdzie domena jest cytowana; śr. pozycja w AIO; zysk/strata | SERP z AI Overview | dynam. |
| Wzmianki AIO konkurencji | tabela: domena, śr. pozycja w AIO, wspólne/unikalne frazy | Labs: Competitors + SERP AIO | dynam. |

*(Rekomendacja specjalisty: „opis, czy jest AI Overview oraz liczba wzmianek AIO Klienta / jego konkurencji")*

---

## 3. RUCH Z CHATGPT I INNYCH CHATBOTÓW

| Element | Treść | Źródło | Koszt |
|---|---|---|---|
| Rynek chatbotów w PL | ChatGPT **86,4%**, Perplexity 6,18%, Copilot 3,43%, Gemini 3,22%, Claude 0,71%; użytkownicy ChatGPT w PL: 3,6 mln → 9,3 mln (I poł. 2025) | **STAŁE** | 0 |
| Case wzrostu ruchu z AI | **Botland: 4 500 → 165 000 sesji z ChatGPT w rok** — dowód skali zjawiska | **STAŁE** | 0 |
| Widoczność marki w AI | wzmianki, cytaty, cytowane strony + trend | AI Optimization: LLM Mentions | dynam. |
| ⭐ **Przykładowe prompty** | tabela: prompt · odpowiedź AI · czy marka wspomniana/cytowana · liczba marek · liczba źródeł | AI Optimization: **LLM Responses** | dynam. |

### ⭐ Sekcja kluczowa — przykładowe prompty

> Cytat specjalisty: *„Dodałbym jeszcze — i mocno podkreśliłbym ten element — przykładowe wzmianki
> z chatbotów. Na rynku nie ma zbyt wielu narzędzi, które pokazują konkretne prompty. A jeśli już są,
> to zazwyczaj są dość drogie. To może być coś, co będzie szczególnie interesujące dla Klientów."*

**To jest wyróżnik całego raportu.** Klient widzi konkretne pytanie, realną odpowiedź AI i to,
czy jego marka w niej wystąpiła. Format wzorowany na module Semrush / widocznosc.ai:

```
Prompt                          | Odpowiedź AI            | Twoja marka | Marki | Źródła
Gdzie w Zielonej Górze można    | Naprawę i wymianę szyb  | Wspomniana  |   6   |  19
naprawić szyby samochodowe      | w Zielonej Górze...     |             |       |
```

Dodatkowo (rekomendacja): **analiza promptów, na jakie marka jest widoczna** — jakie typy pytań
generują wzmianki (lokalne? cenowe? porównawcze?), a gdzie marki brakuje.

---

## Czego NIE odtworzymy 1:1 (uczciwie)

ICEA korzysta z **Senuto + Ahrefs**, my z **DataForSEO**:
- **Liczby będą się różnić** — każde narzędzie ma własny model estymacji ruchu. To normalne,
  ale trzeba to wiedzieć, żeby nie tłumaczyć się przed klientem.
- **Nie skopiujemy zrzutów UI** Senuto/Ahrefs — generujemy **własne wykresy i tabele**
  w identyfikacji Last Agency (co jest zresztą lepsze: raport wygląda na nasz, nie na cudzy).
- **Trendy historyczne** (wykresy „od 2022") zależą od tego, jak głęboko sięga historia w DataForSEO
  — do sprawdzenia przy pierwszym realnym wywołaniu.

---

## Rozpoznanie API — wyniki (2026-08-29, wydane $0.23 z $1)

Wszystkie odpowiedzi zapisane w `backend/fixtures/` — dalsze prace idą **offline, bez kosztu**.

### Co działa i ile kosztuje

| Endpoint | Koszt | Werdykt |
|---|---|---|
| `appendix/user_data` | **$0** | saldo i limity — używać do kontroli budżetu |
| `*/llm_responses/models` | **$0** | lista modeli per dostawca |
| `llm_mentions/search/live` (platform: google) | **$0.11** / 10 wierszy | ✅ AI Overview po polsku — sekcja 2 |
| `perplexity/llm_responses/live` (sonar) | **$0.006** | ✅✅ **najlepszy stosunek jakości do ceny** |
| `chat_gpt/llm_responses/live` (gpt-5.6-sol) | **$0.109** | ✅ działa, ale **18× drożej** niż Perplexity |

### 🔴 Ograniczenie: `chat_gpt` w llm_mentions tylko dla USA/angielskiego
Endpoint `llm_mentions` z `platform: chat_gpt` **nie obsługuje polskiego rynku**.
Dlatego sekcję „wzmianki w chatbotach" budujemy inaczej: **wysyłamy własne prompty**
przez `llm_responses/live` i sprawdzamy, czy marka pada w odpowiedzi. To zresztą dokładnie
mechanizm, którego używa narzędzie ze screena od specjalisty.

### Dlaczego Perplexity `sonar` jako silnik domyślny
Test na tym samym polskim promptcie (sklepy z Raspberry Pi/Arduino):
- **Perplexity**: 9 marek konkurencyjnych, precyzyjne URL-e, cytowania numerowane — **$0.006**
- **ChatGPT (gpt-5.6-sol)**: 3 marki, ładniejszy opis — **$0.109** (12 941 tokenów wejścia przez web search)

Perplexity daje **bogatszą listę marek** (czyli lepszą kolumnę „Marki") za ułamek ceny.

### Model kosztowy audytu (szacunek)

| Element | Wywołania | Koszt |
|---|---|---|
| Prompty — Perplexity | 5 × $0.006 | $0.03 |
| Prompt — ChatGPT (bo 86,4% rynku PL, wypada pokazać) | 1 × $0.11 | $0.11 |
| AI Overview | 1 × $0.11 | $0.11 |
| SEO (Labs) — do zmierzenia | ~2 wywołania | ~$0.20 |
| **Razem** | | **~$0.45/audyt** |

Przy 20 audytach/mies. ≈ **$9 ≈ 35 zł** — mieści się w progu 500 zł z dużym zapasem.
**Optymalizacja:** rezygnacja z ChatGPT na rzecz samego Perplexity zbija koszt do ~$0.34.

### Kształt danych (potwierdzony na żywo)

`llm_responses` → `result[0].items[].sections[]`:
- `text` — treść odpowiedzi AI
- `annotations[].url` — cytowane źródła
- `model_name`, `input_tokens`, `output_tokens`, `money_spent`

`llm_mentions` → `result[0].items[]`:
- `question` (prompt) · `answer` · `sources[]` · `brand_entities[]` · `ai_search_volume` · `monthly_searches`

## Kolejność budowy

1. **Rozpoznanie API** (~$0.23) — po jednym wywołaniu na endpoint, odpowiedzi zapisujemy
   do `backend/fixtures/*.json`
2. **Parsowanie + szablon raportu** — rozwijane offline na fixture'ach, **zero kosztu**
3. **Sekcje stałe** — treść edukacyjna, wykres rynku chatbotów, case Botland
4. **PDF** w identyfikacji Last Agency
5. **Test end-to-end** na 1-2 realnych domenach

## Priorytet, gdyby zabrakło budżetu

Gdyby $1 nie starczył na wszystko, budujemy w tej kolejności wartości dla klienta:
1. ⭐ **Przykładowe prompty z chatbotów** (wyróżnik rynkowy)
2. Widoczność marki w AI (wzmianki/cytaty)
3. AI Overview
4. Raport Zero (SEO) — najłatwiejszy do pokazania z innych narzędzi, więc najmniej unikalny
