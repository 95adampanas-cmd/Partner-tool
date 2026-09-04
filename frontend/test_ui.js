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
  json: () => Promise.resolve(u.includes("/api/firmy")
    ? { ok: true, firmy: FIRMY }
    : { ok: true, kolumny: [], kategorie: [] }),
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

  nav("firmy");
  sprawdz("Firmy: start pokazuje partnerów", nazwy(".firma-row-nazwa").length === 2,
    nazwy(".firma-row-nazwa").join(", "));
  zakladka("klient");
  sprawdz("Firmy: zakładka przełącza na Klientów", aktywna().includes("Klienci"));
  sprawdz("Firmy: widać klienta, nie partnerów",
    nazwy(".firma-row-nazwa").join().startsWith("Ella"), nazwy(".firma-row-nazwa").join(", "));
  zakladka("partner");
  sprawdz("Firmy: powrót na Partnerów", nazwy(".firma-row-nazwa").length === 2);

  nav("audyt");
  sprawdz("Audyt: partnerzy do wyboru", nazwy("#audyt-wybor .sim-name").length === 2);
  zakladka("klient");
  sprawdz("Audyt: zakładka przełącza na Klientów", aktywna().includes("Klienci"));
  sprawdz("Audyt: klient dostępny do audytu",
    nazwy("#audyt-wybor .sim-name").join().startsWith("Ella"), nazwy("#audyt-wybor .sim-name").join(", "));

  nav("podobne", "klient");
  sprawdz("Podobne: w ścieżce Klienci tylko klient",
    nazwy("#podobne-wybor .sim-name").join().startsWith("Ella"), nazwy("#podobne-wybor .sim-name").join(", "));

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
