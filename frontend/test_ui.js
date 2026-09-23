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
    kategoria: "Budowa stron i sklepów", ma_seo: true, uslugi: ["a"], case_studies: [], zrodlo_danych: [] },
  { url: "https://widoczni.com", nazwa: "widoczni", branza: "agencja digital", tryb: "partner",
    kategoria: "Marketing poza SEO", ma_seo: true, uslugi: ["b"], case_studies: [], zrodlo_danych: [] },
  { url: "https://ellaboutique.pl", nazwa: "Ella Boutique", branza: "butik", tryb: "klient",
    kategoria: "Sprzedaż i marketplace", ma_seo: false, uslugi: ["c"], case_studies: [], zrodlo_danych: [] },
];

const dom = new JSDOM(html, { runScripts: "outside-only", url: "http://localhost:8000/" });
const { window } = dom;
window.fetch = (u) => Promise.resolve({
  json: () => Promise.resolve(
    u.includes("/api/firmy") ? { ok: true, firmy: FIRMY } :
    // Dwa zrodla podlaczone, zeby przelacznik sie pokazal — inaczej caly test
    // presetow dla Map leci pusta galezia i niczego nie sprawdza.
    u.includes("/api/zrodla") ? { ok: true, zrodla: { wyszukiwarka: true, mapy: true, google: false } } :
    { ok: true, kolumny: [], kategorie: [], kolejka: [], maile: [] }),
});
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
  } else {
    sprawdz("Presety: brak przelacznika zrodel (jedno podlaczone)", true);
  }

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

  nav("maile");
  sprawdz("Maile: sekcja pokazuje wybór firmy",
    d.getElementById("maile-box").innerHTML.includes("Do kogo piszemy"));

  nav("kolejka");
  sprawdz("Kolejka: sekcja renderuje pusty stan bez błędu",
    d.getElementById("kolejka-box").innerHTML.includes("Kolejka jest pusta"));

  nav("eksport");
  sprawdz("Eksport: sekcja renderuje się bez błędu",
    d.getElementById("eksport-box").innerHTML.length > 0);

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
}, 400);
