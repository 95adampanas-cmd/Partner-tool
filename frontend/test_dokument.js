// Test przewijanej ramki w dokumencie dla klienta partnera.
//
// DLACZEGO OSOBNY PLIK. test_ui.js sprawdza narzędzie, którego używa zespół. To
// sprawdza ARTEFAKT, który zespół wysyła dalej — plik HTML lądujący w skrzynce
// klienta partnera. Tam nikt nie poprawi zepsutego skryptu i nikt nie zgłosi, że
// strzałka nie działa: klient po prostu zobaczy jedną odpowiedź zamiast trzech.
//
// DOKUMENT SKŁADA PYTHON, więc test go najpierw generuje, a potem klika w nim
// jak przeglądarka. Struktura (ile slajdów, czy jest skrypt) jest sprawdzana
// po stronie Pythona w sprawdz_dokument(); tutaj sprawdzamy ZACHOWANIE.
//
//     node test_dokument.js

const { execFileSync } = require("child_process");
const path = require("path");
const { JSDOM } = require("jsdom");

const BACKEND = path.join(__dirname, "..", "backend");

const GENERUJ = `
import io, sys, dokument
tresc = {"wstep_tytul":"A","wstep_tresc":"B","audyt_wstep":"C","audyt_wniosek":"D",
         "dostep_tytul":"E","dostep_tresc":"F","role_tytul":"G","role_wstep":"H",
         "braki":[{"tytul":"x","opis":"y"}]*3,"rola_partner_tytul":"Z",
         "rola_partner":["a"],"rola_my":["b"],"role_puenta":"P"}
dluga = lambda i: f"Odpowiedz numer {i}." + ("\\n- punkt listy o dlugosci paru slow" * 12)
badanie = {"pytania":["pyt 1","pyt 2","pyt 3"],"data":"25.09.2026",
           "odpowiedzi":[{"pytanie":f"pytanie {i}","odpowiedz":dluga(i)}
                         for i in (1,2,3)]}
sys.stdout.reconfigure(encoding="utf-8")
print(dokument.zbuduj(tresc, badanie, "Tebim"))
`;

const wyniki = [];
const sprawdz = (opis, warunek, dodatek) =>
  wyniki.push({ opis, ok: !!warunek, dodatek: dodatek || "" });

let html;
try {
  html = execFileSync("python", ["-c", GENERUJ], {
    cwd: BACKEND,
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
    env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" },
  });
} catch (e) {
  console.log("BŁĄD generowania dokumentu: " + (e.stderr || e.message));
  process.exit(1);
}

// runScripts: "dangerously" — bo o to chodzi: uruchamiamy skrypt z dokumentu.
const dom = new JSDOM(html, { runScripts: "dangerously" });
const d = dom.window.document;
const klik = (el) => el && el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
const widoczny = () => [...d.querySelectorAll("#ekran-odpowiedzi .slajd")].findIndex((s) => !s.hidden);
const licznik = () => (d.querySelector(".slajd-licznik b") || {}).textContent;

sprawdz("Na starcie widać pierwszą odpowiedź", widoczny() === 0, `slajd ${widoczny()}`);
sprawdz("Widać dokładnie jedną naraz",
  [...d.querySelectorAll("#ekran-odpowiedzi .slajd")].filter((s) => !s.hidden).length === 1);

klik(d.querySelector('.slajd-strzalka[data-krok="1"]'));
sprawdz("Strzałka w prawo przewija na drugą", widoczny() === 1, `slajd ${widoczny()}`);
sprawdz("Licznik pokazuje, która to odpowiedź", licznik() === "2", `licznik: ${licznik()}`);

klik(d.querySelectorAll(".kropka")[2]);
sprawdz("Kropka skacze na wskazaną odpowiedź", widoczny() === 2, `slajd ${widoczny()}`);

// Lista pytań po lewej i ramka po prawej to jedna rzecz, nie dwie obok siebie.
klik(d.querySelectorAll(".pytanie-link")[0]);
sprawdz("Kliknięcie pytania pokazuje jego odpowiedź", widoczny() === 0, `slajd ${widoczny()}`);
sprawdz("Wybrane pytanie jest podświetlone",
  d.querySelectorAll(".pytanie-link")[0].classList.contains("jest"));

// Rozwijanie odpowiedzi. Ramka zwija długi tekst, żeby nie rozpychać sekcji,
// ale CAŁA odpowiedź jest w pliku — przycisk tylko ją odsłania.
const odp = () => d.querySelectorAll("#ekran-odpowiedzi .slajd")[widoczny()].querySelector(".odp");
const przyciskRozwin = () =>
  d.querySelectorAll("#ekran-odpowiedzi .slajd")[widoczny()].querySelector(".rozwin");

sprawdz("Długa odpowiedź startuje zwinięta", odp().classList.contains("zwiniete"));
klik(przyciskRozwin());
sprawdz("Kliknięcie rozwija odpowiedź", !odp().classList.contains("zwiniete"));
sprawdz("Przycisk zmienia się na zwijanie",
  przyciskRozwin().textContent === "Zwiń odpowiedź", przyciskRozwin().textContent);
klik(przyciskRozwin());
sprawdz("Drugie kliknięcie zwija z powrotem", odp().classList.contains("zwiniete"));

// Rozwinięta odpowiedź nie może zostać rozwinięta po przejściu na inne pytanie —
// ramka wróciłaby do rozmiaru pół strony przy każdym następnym slajdzie.
klik(przyciskRozwin());
klik(d.querySelector('.slajd-strzalka[data-krok="1"]'));
klik(d.querySelector('.slajd-strzalka[data-krok="-1"]'));
sprawdz("Po przewinięciu odpowiedź wraca zwinięta", odp().classList.contains("zwiniete"));

// Zawijanie: z pierwszej w lewo ma być ostatnia, a nie pusto.
klik(d.querySelector('.slajd-strzalka[data-krok="-1"]'));
sprawdz("Z pierwszej w lewo wraca na ostatnią", widoczny() === 2, `slajd ${widoczny()}`);

let zle = 0;
console.log("");
wyniki.forEach((w) => {
  if (!w.ok) zle++;
  console.log(`  ${w.ok ? "OK  " : "BŁĄD"} | ${w.opis}${w.dodatek ? "   [" + w.dodatek + "]" : ""}`);
});
console.log("");
console.log(`  WYNIK: ${wyniki.length - zle}/${wyniki.length}`);
process.exit(zle ? 1 : 0);
