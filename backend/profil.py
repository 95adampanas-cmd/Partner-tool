"""
Profil Last Agency — stały kontekst, ten sam przy każdej firmie.

TREŚĆ SIEDZI W MARKDOWNIE, NIE TUTAJ. `profil_last_agency.md` to dokument
biznesowy, nie kod: pisze go i poprawia człowiek, który zna agencję, a nie ten,
kto akurat edytuje Pythona. Zmiana oferty czy prowizji nie ma wymagać dotykania
modułu — stąd rozdział. Ten plik tylko go wczytuje i pilnuje, żeby dało się go
sensownie cache'ować.

DLACZEGO JEDEN BLOK. Wcześniej kontekst „kim jesteśmy" był rozsypany po dwóch
promptach w app.py: kawałek w ekstrakcji, kawałek w mailu. Dopóki tak było, nie
dało się go ani cache'ować (cache obejmuje PREFIKS — musi być jednym blokiem na
początku), ani poprawić w jednym miejscu, ani sprawdzić, co model właściwie o nas wie.

OSTRZEŻENIE Z DOŚWIADCZENIA. Pierwsza wersja tego pliku miała treść napisaną przeze
mnie „na podstawie tego, co dało się wyczytać z kodu". Wyszło materialnie fałszywie:
stało tam, że model współpracy to NIE jest white label, podczas gdy jest to dokładnie
program white-label z rabatem partnerskim 15%. Taki tekst szedłby wprost do maila do
realnej firmy. Wniosek: profil wypełnia właściciel, a nie narzędzie — a gdy danych
brak, zostaje luka, nie domysł.

CACHE WŁĄCZA SIĘ SAM. `claude._system()` dokłada `cache_control` tylko wtedy, gdy blok
przekracza próg modelu (Sonnet 1024 tokeny). Sprawdzasz stan poleceniem:

    python -c "import app; print(app.stan_cache())"
"""

from pathlib import Path

PLIK = Path(__file__).resolve().parent / "profil_last_agency.md"

# Doklejane do profilu przy zadaniach, które piszą tekst wychodzący na zewnątrz.
# Sam profil jest opisem firmy; to są zasady, jak o niej mówić.
ZASADY_PISANIA = """ZASADY PISANIA DO PARTNERÓW:
- Konkretnie i krótko. Pierwszy kontakt ma doprowadzić do rozmowy, nie sprzedać usługę.
- Piszemy jak człowiek do człowieka, nie jak dział marketingu do rynku.
- Zero korpomowy: żadnych „rozwiązań szytych na miarę" ani „dynamicznie rozwijającej
  się firmy". Słowo „synergia" w mailu do partnera brzmi jak szablon — pokaż rzecz,
  nie nazwij jej.
- Pokazujemy, że weszliśmy na ich stronę i wiemy, co robią — jednym konkretem,
  nie listą komplementów.
- Nie przypisujemy firmie usług ani klientów, których nie ma na jej stronie.
- Nie podajemy liczb o Last Agency, których nie ma w profilu powyżej.
- Nie udajemy, że znamy kogoś z zespołu odbiorcy."""


def pelny() -> str:
    """Cały profil jako jeden blok — w tej kolejności trafia do modelu.

    Kolejność ma znaczenie przy cache: ten tekst musi być PREFIKSEM promptu i nie może
    zawierać niczego zmiennego między firmami. Gdyby wpadła tu choć nazwa badanej
    firmy, cache unieważniałby się przy każdym wywołaniu i płacilibyśmy za zapis
    zamiast czytać z pamięci.
    """
    return PLIK.read_text(encoding="utf-8").strip() + "\n\n" + ZASADY_PISANIA


def istnieje() -> bool:
    """Czy plik profilu jest na miejscu. Brak profilu to nie awaria — narzędzie ma
    wtedy działać dalej, tylko bez wiedzy o nas. Cicha pustka byłaby gorsza."""
    return PLIK.exists() and len(PLIK.read_text(encoding="utf-8").strip()) > 200
