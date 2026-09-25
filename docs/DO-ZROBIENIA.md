# Do zrobienia

Zadania ustalone, ale jeszcze niezaczęte. Każde z powodem, pomiarem i tym, co
konkretnie zmienia — żeby dało się je podjąć bez odtwarzania rozmowy.

---

## 1. Rozróżnienie botów treningowych i użytkowych w obu audytach — ZROBIONE 24.09.2026

**Stan:** wdrożone w `backend/geo.py`, działa na oba audyty (oba wołają
`geo.audyt_geo`). Dołożone 9 botów użytkowych (razem 17 na liście), czytany
`Content-Signal`, przepisany język raportu. Test regresyjny: `sprawdz_boty_ai()`
w `backend/test_filtr.py`. Sprawdzone na sortlist.pl: było jedno fałszywe
ustalenie o wadze blokada, jest zero — zamiast tego dwa ustalenia poprawne.

Opis poniżej zostaje jako uzasadnienie zmiany.

**Skąd to się wzięło.** Przy analizie sortlist.pl okazało się, że ich `robots.txt`
jest skonfigurowany wzorowo pod GEO — a nasz audyt zgłosiłby to jako błąd.

**Na czym polega pomyłka.** Sprawdzamy dziś dziesięć botów (`geo.BOTY`) i traktujemy
każde `Disallow` jako blokadę. Tymczasem firmy coraz częściej rozróżniają dwie
zupełnie różne rzeczy:

| bot | rola | Sortlist |
|---|---|---|
| `GPTBot` | zbiera dane do TRENOWANIA modelu | Disallow |
| `ChatGPT-User` | pobiera stronę, GDY UŻYTKOWNIK PYTA | **Allow** |
| `ClaudeBot` | trenowanie | Disallow |
| `Claude-User`, `Claude-SearchBot` | odpowiadanie na żywo | **Allow** |

Nasz raport na takiej konfiguracji mówi: *„GPTBot (ChatGPT) — ChatGPT nie pobiera
treści strony"*. **To jest nieprawda.** ChatGPT pobiera ją przez `ChatGPT-User`.
Klient dostałby zalecenie naprawy czegoś, co działa poprawnie — i to w dokumencie,
który ma budować nasz autorytet.

**Czego brakuje w `geo.BOTY`.** Mamy boty treningowe i crawlery, nie mamy tych,
które decydują o widoczności w odpowiedziach: `ChatGPT-User`, `Claude-User`,
`Claude-SearchBot`, `Perplexity-User`, `DuckAssistBot`, `MistralAI-User`,
`meta-externalfetcher`.

**Drugi brak: `Content-Signal`.** Nowszy standard, którego nie czytamy wcale:

```
Content-Signal: search=yes,ai-input=yes,ai-train=no
```

Mówi wprost: wyszukiwarki tak, użycie jako dane wejściowe tak, trenowanie nie.
To osobna deklaracja od `Allow`/`Disallow` i niesie intencję, której z samego
`Disallow` nie da się odczytać.

**Co zrobić:**

1. Dołożyć boty użytkowe do `geo.BOTY` i podzielić ustalenia na dwie grupy:
   *„czy AI może Cię pokazać"* (boty użytkowe — to jest istotne dla GEO) oraz
   *„czy AI może się na Tobie uczyć"* (boty treningowe — to decyzja biznesowa,
   nie błąd).
2. Czytać `Content-Signal` i pokazywać go jako osobne ustalenie.
3. Zmienić język raportu: zablokowanie bota treningowego przestaje być „blokadą",
   a staje się informacją. Blokadą jest wyłącznie zamknięcie botów użytkowych.
4. Dopisać wyjaśnienie DLACZEGO to ma znaczenie — bo dziś raport podaje fakt bez
   konsekwencji. Zdanie typu: *„ChatGPT nie wejdzie na Waszą stronę, gdy klient
   zapyta o firmę z Waszej branży — odpowie z tego, co znalazł u konkurencji"*.

**Gdzie:** w audycie nr 1 i nr 2. Sekcja techniczna (`geo.py`) jest wspólna dla obu,
więc poprawka wchodzi w jednym miejscu i działa na oba raporty.

---

## 2. Sortlist jako źródło firm — jednorazowy import

**Co to daje.** 182 polskie agencje z adresami stron, miastem i rokiem założenia,
w jednym przebiegu, za zero. Inna pula niż wyszukiwarka i niż Mapy: to firmy, które
SAME zgłosiły się do katalogu, czyli aktywnie szukają zleceń.

**Jak to technicznie wygląda** (sprawdzone 24.09.2026):

```
https://www.sortlist.pl/sitemaps/agency-profile.xml   ->  182 profile
każdy profil                                          ->  adres www firmy
```

Zwykłe HTTP, bez headless browsera, bez proxy — cała treść jest w HTML-u. To
zasadnicza różnica wobec Google, którego scrapowanie odradziłem: tam strona bez
JavaScriptu jest pusta i trzeba obchodzić blokady.

**Weryfikacja na próbce: 10 na 10 profili miało adres firmy.**

**Czy wolno.** Tak, i to jest jawnie zadeklarowane w ich `robots.txt`:
`User-agent: *` → `Allow: /`, a `Content-Signal` mówi `ai-input=yes, ai-train=no`.
Blokują trenowanie modeli, nie czytanie. Nasz przypadek to czytanie listy firm.

**Pułapka do obsłużenia.** Pierwszy link zewnętrzny na profilu nie zawsze jest stroną
firmy. W próbce: `adnet-polska` → `about.me` (wizytówka w serwisie trzecim),
`a2-marketing` → `en.a2studio.pro` (wersja językowa). Filtr musi odsiewać katalogi
i serwisy społecznościowe, a przy wersjach językowych sprowadzać do domeny głównej.

**Kształt funkcji:** to NIE jest kolejny przycisk w wyszukiwaniu. To jednorazowy
import, który wrzuca 182 firmy do kolejki „Do zbadania" — stamtąd idą normalną
ścieżką researchu. Uruchamiany świadomie, nie przy każdym szukaniu.

**Czego NIE robić.** Nie wyciągać listingu ze stron kategorii (`/agencje-e-commerce`).
Tam też są dane, ale bez adresów i z kruchym parsowaniem — wyciągnięte nazwy wychodzą
ucięte („All 4", „SaM", „Brand"). Sitemapa profili jest źródłem stabilnym.

---

## 3. Raport z audytu GEO na tym samym wzorze co dokument dla klienta — ZROBIONE 25.09.2026

**Skąd to się wzięło.** 25.09.2026 powstał generator dokumentu dla klienta partnera
(`backend/dokument.py` + `szablon_dokumentu.html`): wzór ICEA, logo, case study
Botland, nominacja do European Search Awards, sekcja o podziale ról. Raport z audytu
GEO ma dziś zupełnie inny wygląd — to `raportHTML()` w `frontend/app.js`, czyli
widok wewnątrz narzędzia, nie dokument do wysłania.

**Co zrobić.** Raport z audytu ma wychodzić jako plik na TYM SAMYM wzorze:
identyfikacja ICEA, case Botland, argumentacja i sekcja synergii — a w środku
dane z audytu zamiast mikroaudytu z trzech pytań.

**Co już jest gotowe do użycia:**

| element | gdzie leży |
|---|---|
| wzór HTML z całą identyfikacją | `backend/szablon_dokumentu.html` |
| podmiana sekcji przez regex | `dokument.WZORY` |
| przewijana ramka z odpowiedziami | `dokument.STYLE_SLAJDOW`, `SKRYPT_SLAJDOW` |
| czyszczenie markdownu z odpowiedzi | `dokument._odpowiedz_html()` |
| nazwa pliku do pobrania | `dokument.nazwa_pliku()` |

**Czego raport ma więcej niż dokument.** Audyt zwraca dane, których w dokumencie
nie ma: wykres widoczności, tabela konkurentów, analiza źródeł, obecność
w rankingach, AI Overviews (w audycie nr 1). Dla każdego z nich trzeba ustalić,
w które miejsce wzoru wchodzi — albo świadomie zdecydować, że nie wchodzi.

**Pytanie do rozstrzygnięcia przed kodowaniem:** czy to jeden generator z dwoma
trybami, czy dwa osobne. Dokument dla klienta jest krótki i sprzedażowy, raport
z audytu jest długi i dowodowy. Wspólny jest wzór, nie treść — więc najpewniej
wspólna zostaje warstwa składania (podmiana sekcji, style, skrypt), a każdy
produkt ma własny zestaw sekcji.

**Jak wyszło.** `backend/raport_geo.py` bierze gotowy raport z zakładki i wstawia
przed case study cztery sekcje: pomiar z rozbiciem na silniki, konkurentów,
źródła wraz z tabelą obecności marki, ustalenia techniczne. Wykresy to słupki
z szerokością w procentach — zero bibliotek, bo plik bywa otwierany bez internetu.
Pomiar się nie powtarza: dokument powstaje z danych, które już są, więc kosztuje
tylko jedno napisanie tekstu.

**Rozstrzygnięcie pytania z góry:** dwa produkty, jedna warstwa składania.
`dokument.py` trzyma szablon, podmianę sekcji, style i skrypt; `raport_geo.py`
dokłada własne sekcje. Wspólna okazała się też ramka z odpowiedziami — i to ona
wymusiła poprawkę: odpowiedzi modeli były ucinane na 850 znakach. Teraz idą
w całości i zwijają się do 260 px z przyciskiem „Pokaż całą odpowiedź".
