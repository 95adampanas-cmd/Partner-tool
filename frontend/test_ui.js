/**
 * Test interfejsu — przełączanie ścieżek Partnerzy/Klienci.
 *
 *   cd frontend
 *   npm install jsdom@22     (raz; nowszy jsdom wymaga Node 20+)
 *   node test_ui.js
 *
 * PO CO TO ISTNIEJE. Zakładki Partnerzy/Klienci nie działały od momentu, w którym
 * powstały: handler siedział w nasłuchu "change", a <button> nigdy nie wywołuje
 * tego zdarzenia. Ścieżkę dało się zmienić wyłącznie z menu bocznego, więc błąd
 * przez cały czas wyglądał jak "klienci gdzieś nie działają".
 *
 * Czytanie kodu tego nie wykryło — sprawdzałem markup, kolejność handlerów i CSS,
 * wszystko wyglądało poprawnie. Dopiero kliknięcie w prawdziwym DOM pokazało, że
 * zdarzenie nie dochodzi. Dlatego ten test klika, zamiast analizować.
 *
 * Backend NIE jest potrzebny — fetch jest podstawiony, dane są sztuczne.
 */

const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");

const KAT = __dirname;
const html = fs.readFileSync(path.join(KAT, "index.html"), "utf8")
  .replace(/<script src="app.js"><\/script>/, "");

// Dwie ścieżki, żeby dało się sprawdzić, czy się nie mieszają.
const FIRMY = [
  { url: "https://tebim.pro", nazwa: "Tebim", branza: "agencja e-commerce", tryb: "partner",
    kategoria: "Sklepy internetowe", ma_seo: true, uslugi: ["a"], case_studies: [], zrodlo_danych: [] },
  { url: "https://widoczni.com", nazwa: "widoczni", branza: "agencja digital", tryb: "partner",
    kategoria: "Performance", ma_seo: true, uslugi: ["b"], case_studies: [], zrodlo_danych: [] },
  { url: "https://ellaboutique.pl", nazwa: "Ella Boutique", branza: "butik", tryb: "klient",
    kategoria: "Marketplace", ma_seo: false, uslugi: ["c"], case_studies: [], zrodlo_danych: [] },
];

const dom = new JSDOM(html, { runScripts: "outside-only", url: "http://localhost:8000/" });
const { window } = dom;
// Zapis zadan do backendu. Bez tego nie da sie sprawdzic, czy klikniecie
// W OGOLE dotarlo do /api/kolejka — a wlasnie to bylo zepsute: przycisk
// "Dodaj wszystkie do kolejki" przechwytywal inny warunek w obsludze klikniec
// i zamiast dodawac firmy przestawial zrodlo wyszukiwania.
const zadania = [];
const ZNALEZIONE = [
  { url: "https://sklep-alfa.pl", nazwa: "Alfa", opis: "wdrozenia Shopify", ma_seo: false },
  { url: "https://sklep-beta.pl", nazwa: "Beta", opis: "sklepy PrestaShop", ma_seo: true },
];
window.fetch = (u, opcje) => {
  zadania.push({ url: u, metoda: (opcje && opcje.method) || "GET",
                 body: opcje && opcje.body ? JSON.parse(opcje.body) : null });
  return Promise.resolve({
    json: () => Promise.resolve(
      u.includes("/api/firmy") ? { ok: true, firmy: FIRMY } :
      u.includes("/api/szukaj") ? { ok: true, firmy: ZNALEZIONE, zapytanie: "tworzenie sklepów internetowych", zrodlo: "wyszukiwarka" } :
      u.includes("/api/kolejka") && (!opcje || !opcje.method || opcje.method === "GET")
        ? { ok: true, kolejka: [] } :
      u.includes("/api/kolejka") ? { ok: true, doszlo: ZNALEZIONE.length } :
      // Dwa zrodla podlaczone, zeby przelacznik sie pokazal — inaczej caly test
      // presetow dla Map leci pusta galezia i niczego nie sprawdza.
      u.includes("/api/zrodla") ? { ok: true, zrodla: { wyszukiwarka: true, mapy: true, google: false } } :
      { ok: true, kolumny: [], kategorie: [], kolejka: [], maile: [] }),
  });
};
window.scrollTo = () => {};

const bledyJS = [];
window.addEventListener("error", (e) => bledyJS.push(e.message));

try {
  window.eval(fs.readFileSync(path.join(KAT, "app.js"), "utf8"));
} catch (e) {
  console.log("BŁĄD PRZY ŁADOWANIU app.js: " + e.message);
  process.exit(1);
}

const wyniki = [];
const sprawdz = (opis, warunek, dodatek) =>
  wyniki.push({ opis, ok: !!warunek, dodatek: dodatek || "" });

setTimeout(() => {
  const d = window.document;
  const klik = (el) => el && el.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  const nav = (sek, tryb) => klik([...d.querySelectorAll(".nav-item")]
    .find((b) => b.dataset.sekcja === sek && (!tryb || b.dataset.tryb === tryb)));
  // Zakładka i nazwy TYLKO z widocznej sekcji — przełączniki są w trzech sekcjach
  // naraz i globalne querySelector trafiałoby w ukryty, nieodświeżony.
  const zakladka = (t) => klik(d.querySelector(`.sekcja.aktywna [data-ustaw-tryb="${t}"]`));
  const aktywna = () => (d.querySelector(".sekcja.aktywna .tryb-btn.aktywny") || {}).textContent || "";
  const nazwy = (sel) => [...d.querySelectorAll(sel)].map((x) => x.textContent.trim());

  // Ścieżka klientów bywa wyłączona (POKAZUJ_KLIENTOW w app.js). Testy jej nie
  // kasujemy — sprawdzamy to, co w danej konfiguracji ma być prawdą. Dzięki temu
  // po ponownym włączeniu ścieżki komplet asercji wraca sam.
  // Stan czytamy z DOM, a NIE ze zmiennej w app.js. window.eval tworzy `const`
  // we własnym zakresie, więc drugi eval jej nie widzi i odczyt zawsze dawał
  // undefined — testy leciały złą gałęzią i przy wyłączonej ścieżce przechodziły
  // przypadkiem. Poza tym test powinien sprawdzać to, co widzi użytkownik.
  const zKlientami = [...d.querySelectorAll(".nav-grupa")]
    .some((g) => g.textContent.trim() === "Klienci");

  nav("firmy");
  sprawdz("Firmy: pokazuje partnerów", nazwy(".firma-row-nazwa").length === 2,
    nazwy(".firma-row-nazwa").join(", "));

  if (zKlientami) {
    zakladka("klient");
    sprawdz("Firmy: zakładka przełącza na Klientów", aktywna().includes("Klienci"));
    sprawdz("Firmy: widać klienta, nie partnerów",
      nazwy(".firma-row-nazwa").join().startsWith("Ella"), nazwy(".firma-row-nazwa").join(", "));
    zakladka("partner");
    sprawdz("Firmy: powrót na Partnerów", nazwy(".firma-row-nazwa").length === 2);
  } else {
    sprawdz("Firmy: brak przełącznika ścieżki",
      !d.querySelector(".sekcja.aktywna .przelacznik-tryb"));
    sprawdz("Menu: brak grupy Klienci",
      ![...d.querySelectorAll(".nav-grupa")].some((g) => g.textContent.trim() === "Klienci"));
    sprawdz("Menu: brak pozycji ze ścieżką klienta",
      d.querySelectorAll('.nav-item[data-tryb="klient"]').length === 0);
    sprawdz("Firmy: klient NIE miesza się z partnerami",
      !nazwy(".firma-row-nazwa").join().includes("Ella"), nazwy(".firma-row-nazwa").join(", "));
  }

  nav("audyt");
  sprawdz("Audyt: partnerzy do wyboru", nazwy("#audyt-wybor .sim-name").length === 2);
  if (zKlientami) {
    zakladka("klient");
    sprawdz("Audyt: zakładka przełącza na Klientów", aktywna().includes("Klienci"));
    sprawdz("Audyt: klient dostępny do audytu",
      nazwy("#audyt-wybor .sim-name").join().startsWith("Ella"), nazwy("#audyt-wybor .sim-name").join(", "));
  } else {
    sprawdz("Audyt: klient nie trafia na listę",
      !nazwy("#audyt-wybor .sim-name").join().includes("Ella"), nazwy("#audyt-wybor .sim-name").join(", "));
  }

  // Formularz audytu pojawia się DOPIERO po wybraniu firmy, a to on niesie całą
  // konfigurację: modele, platformy wzmianek, zakres, koszt. Wcześniej test kończył
  // się na liście firm, więc największy szablon w aplikacji nie był sprawdzany wcale
  // — a usunięcie SE Ranking ruszyło w nim siedem miejsc.
  if (zKlientami) zakladka("partner");
  klik(d.querySelector("#audyt-wybor .sim-row button"));
  const formularz = d.getElementById("audyt-wybor").innerHTML;
  sprawdz("Audyt: formularz renderuje się po wyborze firmy",
    formularz.includes("Które modele AI pytamy"));
  sprawdz("Audyt: jest wybór modeli", d.querySelectorAll('input[name="silnik"]').length > 0,
    `${d.querySelectorAll('input[name="silnik"]').length} modeli`);
  sprawdz("Audyt: jest szacowany koszt w dolarach", /Szacowany koszt: .*\$/.test(formularz));
  // Po usunięciu drugiego dostawcy nie ma już czego wybierać — gdyby przełącznik
  // wrócił, wracałby też cały martwy kod obsługi, którego nikt by nie zauważył.
  sprawdz("Audyt: brak wyboru dostawcy (został jeden)",
    d.querySelectorAll('input[name="dostawca"]').length === 0);
  sprawdz("Audyt: brak pozostałości po SE Ranking",
    !/seranking|SE Ranking|kredyt/i.test(formularz));

  nav("podobne", zKlientami ? "klient" : null);
  sprawdz("Podobne: lista firm wzorcowych niepusta",
    nazwy("#podobne-wybor .sim-name").length > 0, nazwy("#podobne-wybor .sim-name").join(", "));

  // Przelacznik zrodel: pokazuje sie dopiero przy DWOCH podlaczonych. Test stubuje
  // /api/zrodla bez pola `zrodla`, wiec sprawdzamy przede wszystkim, ze brak tego
  // pola NIE wywala renderowania — kiedys wywalal, a wyjatek polykal .catch.
  nav("szukaj");
  sprawdz("Zrodla: brak pola w odpowiedzi nie wywala sekcji",
    !!d.querySelector('.sekcja[data-sekcja="szukaj"]'));

  // Presety zaleza od zrodla: Mapy maja wlasny, krotszy zestaw, bo szukaja po
  // nazwach wizytowek, a nie po tresci stron. Po przelaczeniu zrodla lista kategorii
  // musi sie PRZERYSOWAC — inaczej klikasz w kategorie z poprzedniego zestawu.
  nav("szukaj");
  const ileKategorii = () => d.querySelectorAll("#presety-branz [data-grupa]").length;
  const przedZmiana = ileKategorii();
  sprawdz("Presety: kategorie sie renderuja", przedZmiana > 0, `${przedZmiana} kategorii`);
  const btnMapy = d.querySelector('[data-zrodlo="mapy"]');
  if (btnMapy) {
    klik(btnMapy);
    sprawdz("Presety: Mapy maja INNY zestaw niz wyszukiwarka",
      ileKategorii() !== przedZmiana, `${przedZmiana} -> ${ileKategorii()}`);
    sprawdz("Presety: Mapy oznaczaja slabe kategorie",
      d.querySelectorAll("#presety-branz .tag-slaby").length > 0,
      `${d.querySelectorAll("#presety-branz .tag-slaby").length} slabych`);
    // Sekcje przy Mapach maja INNY podzial niz przy wyszukiwarce: nie uslugi/SaaS,
    // tylko "dziala / nie dziala w Mapach". To najcenniejsza informacja przy
    // wyborze, wiec musi byc widoczna w naglowku, a nie tylko w stylu chipa.
    const naglowkiMap = [...d.querySelectorAll("#presety-branz .preset-sekcja-tytul")]
      .map((x) => x.textContent);
    sprawdz("Presety: Mapy maja wlasne nazwy sekcji",
      naglowkiMap.some((x) => x.includes("Mapach")), naglowkiMap.join(" | "));
    // Slabe kategorie maja byc RAZEM w jednej sekcji, a nie rozsiane po liscie —
    // inaczej podzial nie oszczedza klikania, tylko dokłada ozdobnik.
    const slabaSekcja = [...d.querySelectorAll("#presety-branz .preset-sekcja")]
      .find((s) => s.querySelector(".preset-sekcja-tytul").textContent.includes("Słabe"));
    sprawdz("Presety: slabe kategorie zebrane w jednej sekcji",
      !!slabaSekcja && slabaSekcja.querySelectorAll(".tag-slaby").length ===
        d.querySelectorAll("#presety-branz .tag-slaby").length);
  } else {
    sprawdz("Presety: brak przelacznika zrodel (jedno podlaczone)", true);
  }

  // Kategorie maja byc w dwoch nazwanych sekcjach — przy 29 pozycjach jeden rzad
  // chipow to sciana. Wracamy na Wyszukiwarke, bo poprzedni przypadek zostawil Mapy.
  // Kafelki "Cale ujecie firmy" w Szukaj podobnych. Dwie rzeczy, ktore byly zle:
  // wchodzila tam NASZA kategoria (etykieta chipu, nie fraza — nikt tak o sobie
  // nie pisze), a dluga branza szla jednym kafelkiem
  // i zapytanie bylo za waskie.
  nav("podobne", zKlientami ? "klient" : null);

  // Tag zbadanej firmy musi byc TA SAMA nazwa co kategoria wyszukiwania. Bez tego
  // szukasz w "Sklepy internetowe", a znaleziona firma dostaje chip, ktorego nie ma
  // na zadnej liscie — i filtr na liscie Firm przestaje cokolwiek znaczyc.
  // Czytamy PRZED wyborem firmy: po kliknieciu lista chipow ustepuje miejsca karcie
  // firmy wzorcowej.
  const tagiFirm = [...d.querySelectorAll("[data-kat-podobne]")]
    .map((x) => x.dataset.katPodobne).filter(Boolean);

  klik(d.querySelector("#podobne-wybor .sim-row button"));
  const szerokieTagi = [...d.querySelectorAll(".tag-szeroki")].map((x) => x.textContent.trim());
  sprawdz("Podobne: kafelki szerokie sie pojawily", szerokieTagi.length > 0,
    szerokieTagi.join(" | "));
  // Mapy sa DOMYSLNE w Szukaj podobnych, inaczej niz w Szukaj po branzy.
  // Zmierzone na Sellision: wyszukiwarka 9 firm, Mapy 30, wspolnych 2 — Mapy
  // rankinguja po wizytowce, wiec pokazuja firmy, ktore nie inwestuja w SEO.
  const zaznaczoneZrodlo = [...d.querySelectorAll("[data-zrodlo-podobne]")]
    .find((b) => b.classList.contains("zaznaczony"));
  sprawdz("Podobne: Mapy sa domyslnym zrodlem",
    !zaznaczoneZrodlo || zaznaczoneZrodlo.dataset.zrodloPodobne === "mapy",
    zaznaczoneZrodlo ? zaznaczoneZrodlo.dataset.zrodloPodobne : "brak przelacznika");

  // Kategoria jest dzis TA SAMA nazwa co kategoria wyszukiwania w PRESETY,
  // ale to wciaz ETYKIETA CHIPU, a nie zapytanie: nikt nie wpisuje w Google
  // "Sklepy internetowe", zeby znalezc agencje. Na zapytanie nadaje sie fraza
  // glowna tej kategorii ("tworzenie sklepów internetowych"), nie sam tag.
  sprawdz("Podobne: NASZA kategoria nie jest fraza wyszukiwania",
    !szerokieTagi.includes("Sklepy internetowe")
      && !szerokieTagi.includes("Budowa stron i sklepów"),
    szerokieTagi.join(" | "));

  nav("szukaj");
  klik(d.querySelector('[data-zrodlo="wyszukiwarka"]'));
  sprawdz("Presety: kategorie w dwoch nazwanych sekcjach",
    d.querySelectorAll("#presety-branz .preset-sekcja").length === 2,
    `${d.querySelectorAll("#presety-branz .preset-sekcja").length} sekcji`);

  const kategoriePresetow = [...d.querySelectorAll("#presety-branz [data-grupa]")]
    .map((x) => x.firstChild ? x.textContent.replace(/\s*\d+\s*$/, "").trim() : "");
  const osierocone = tagiFirm.filter((t) => !kategoriePresetow.includes(t));
  sprawdz("Tagi firm sa tymi samymi nazwami co kategorie wyszukiwania",
    osierocone.length === 0,
    osierocone.length ? `poza lista: ${osierocone.join(", ")}` : `${tagiFirm.length} tagow`);

  nav("rozmowa");
  sprawdz("Rozmowa: sekcja pokazuje wybór firmy",
    d.getElementById("rozmowa-box").innerHTML.includes("O której firmie rozmawiamy"));
  klik(d.querySelector("#rozmowa-box .sim-row button"));
  sprawdz("Rozmowa: po wyborze firmy jest pole pytania",
    !!d.querySelector("#rozmowa-box .czat-pytanie"));
  sprawdz("Rozmowa: jest przycisk Zapytaj",
    !!d.querySelector("#rozmowa-box .czat-wyslij"));
  // Czat ma zyc w JEDNYM miejscu. Gdyby zostal tez w karcie firmy, dwa watki
  // o tej samej firmie rozjechalyby sie bez sladu.
  nav("firmy");
  sprawdz("Rozmowa: czatu NIE ma juz w karcie firmy",
    !d.querySelector(".panel .czat-karta"));

  // Audyt GEO — OSOBNA zakladka, nie wariant mikroaudytu. Pierwsza zakladka ma
  // zostac nietknieta, wiec sprawdzamy jedno i drugie osobno.
  nav("audytgeo");
  sprawdz("Audyt GEO: sekcja pokazuje wybor firmy",
    d.getElementById("audytgeo-wybor").innerHTML.includes("Kogo audytujemy"));
  klik(d.querySelector("#audytgeo-wybor .sim-row button"));
  const geoForm = d.getElementById("audytgeo-wybor").innerHTML;
  // Pole na wlasne prompty zostalo usuniete na zyczenie — pilnujemy, zeby nie
  // wrocilo przypadkiem razem ze stanem, ktory nikogo juz nie obsluguje.
  sprawdz("Audyt GEO: nie ma pola na wlasne prompty",
    !d.getElementById("geo-wlasne"));
  sprawdz("Audyt GEO: jest suwak powtorzen", !!d.getElementById("geo-powtorzenia"));
  sprawdz("Audyt GEO: jest przelacznik podpowiedzi Google", !!d.getElementById("geo-podpowiedzi"));
  sprawdz("Audyt GEO: sa DWA silniki na wlasnych kluczach",
    d.querySelectorAll('input[name="geo-silnik"]').length === 2);
  // Ten audyt nie moze dotykac DataForSEO — gdyby ktos dolozyl tu silnik przez
  // dostawce, cala jego przewaga (dziala przy pustym saldzie) by zniknela.
  // Szukamy ETYKIETY uzycia ("przez DataForSEO"), a nie samego slowa: w opisie
  // formularza pada zdanie "ten audyt nie dotyka DataForSEO" i to jest obietnica,
  // nie uzycie. Pierwsza wersja tego testu wywalala sie wlasnie na niej.
  sprawdz("Audyt GEO: zaden silnik nie idzie przez DataForSEO",
    !/przez DataForSEO/i.test(geoForm));
  sprawdz("Audyt GEO: pokazuje koszt przed uruchomieniem", /Szacowany koszt/.test(geoForm));

  // Pierwsza zakladka ma zostac JAK BYLA — bez suwaka powtorzen, ktory nalezy do GEO.
  nav("audyt");
  klik(d.querySelector("#audyt-wybor .sim-row button"));
  sprawdz("Mikroaudyt: bez suwaka powtorzen (zostal jak byl)",
    !d.getElementById("audyt-powtorzenia"));

  nav("maile");
  sprawdz("Maile: sekcja pokazuje wybór firmy",
    d.getElementById("maile-box").innerHTML.includes("Do kogo piszemy"));

  nav("kolejka");
  sprawdz("Kolejka: sekcja renderuje pusty stan bez błędu",
    d.getElementById("kolejka-box").innerHTML.includes("Kolejka jest pusta"));

  nav("eksport");
  sprawdz("Eksport: sekcja renderuje się bez błędu",
    d.getElementById("eksport-box").innerHTML.length > 0);

  // ── Kolejka: czy przycisk w ogole cokolwiek wysyla ─────────────────
  // To jest regresja z 24.09.2026. Przycisk miał atrybut `data-zrodlo`, ten sam,
  // ktorym oznaczone sa przelaczniki zrodel — a warunek dla przelacznika stoi
  // wyzej w obsludze klikniec. Kazde klikniecie "Dodaj wszystkie do kolejki"
  // przestawialo wiec zrodlo wyszukiwania i przerysowywalo presety. Kolejka
  // zostawala pusta i nic nie mowilo, ze cos poszlo nie tak.
  nav("szukaj", "partner");
  d.getElementById("branza").value = "tworzenie sklepów internetowych";
  d.getElementById("form-kryteria").dispatchEvent(
    new window.Event("submit", { bubbles: true, cancelable: true }));

  setTimeout(() => {
    const przycisk = d.querySelector(".do-kolejki-wszystkie");
    sprawdz("Kolejka: wyniki maja przycisk dodania do kolejki", !!przycisk);

    const zrodloPrzed = (d.querySelector("#zrodla-wyboru .tag.zaznaczony") || {}).textContent;
    klik(przycisk);

    setTimeout(() => {
      const dodania = zadania.filter((z) => z.url.includes("/api/kolejka") && z.metoda === "POST");
      sprawdz("Kolejka: klikniecie wysyla firmy do /api/kolejka",
        dodania.length === 1 && (dodania[0].body.firmy || []).length === ZNALEZIONE.length,
        dodania.length ? `${(dodania[0].body.firmy || []).length} firm` : "zadnego zadania");

      sprawdz("Kolejka: dodanie NIE przestawia zrodla wyszukiwania",
        (d.querySelector("#zrodla-wyboru .tag.zaznaczony") || {}).textContent === zrodloPrzed,
        `${zrodloPrzed} -> ${(d.querySelector("#zrodla-wyboru .tag.zaznaczony") || {}).textContent}`);

      // Tag kategorii dla firm, ktore dopiero czekaja na research. Fraza pochodzi
      // z presetu "Sklepy internetowe", wiec kolejka ma to zapamietac — inaczej
      // po dodaniu 200 firm z pieciu branz nie da sie ich rozdzielic.
      sprawdz("Kolejka: firmy dostaja kategorie z presetu",
        dodania.length === 1 && dodania[0].body.kategoria === "Sklepy internetowe",
        dodania.length ? JSON.stringify(dodania[0].body.kategoria) : "brak");

      podsumuj();
    }, 60);
  }, 60);
}, 400);

function podsumuj() {
  let zle = 0;
  console.log("");
  wyniki.forEach((w) => {
    if (!w.ok) zle++;
    console.log(`  ${w.ok ? "OK  " : "BŁĄD"} | ${w.opis}${w.dodatek ? "   [" + w.dodatek + "]" : ""}`);
  });
  console.log("");
  console.log(`  błędy JS: ${bledyJS.length ? bledyJS.join(" | ") : "brak"}`);
  console.log(`  WYNIK: ${wyniki.length - zle}/${wyniki.length}`);
  process.exit(zle || bledyJS.length ? 1 : 0);
}
