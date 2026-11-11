# Eksport: eksport jednym przyciskiem (Revit 2022 i nowsze)

[English](README.md) · Polski

Przycisk pyRevit, który eksportuje modele Revita natywnym Autodesk Revit Extractorem, **bez otwartego modelu** w Revicie. Wybierasz modele z folderów, opcjonalnie widoki jednego modelu, i uruchamiasz eksport. Polecenie wraca od razu, a okno statusu pokazuje postęp i wynik.

**Stan: zbudowany i przetestowany jednostkowo poza Revitem. Jeszcze nie uruchomiony w Revicie.** Zob. Weryfikacja.

## Instalacja

Sklonuj repozytorium i dodaj `<klon>\pyRevit` jako własny folder rozszerzeń w ustawieniach pyRevit, potem **Reload pyRevit**. Przycisk nazywa się `Eksport` (zakładka RevitExtractor, panel Setup). Przycisk potrzebuje `lib\` tego rozszerzenia, więc nie da się go skopiować osobno. Stare przyciski `ExportSetup` i `ExportSetupLegacy` nie są zmienione i nadal działają.

Do „Otwórz w Analyzerze” z lokalnym Analyzerem: Node.js 24 lub nowszy oraz jednorazowo `npm ci --ignore-scripts --omit=optional` w `Analyzer\`. Bez nich przycisk otwiera folder wyników i stronę internetową.

## Użycie

1. Przy **zamkniętych modelach** kliknij **Eksport**. Przy otwartym modelu przycisk jest wyszarzony; jeśli mimo to zostanie kliknięty, pojawi się komunikat i nic nie jest czytane.
2. **Dodaj folder…** (jeden lub więcej folderów głównych, przeszukiwanych rekurencyjnie; dyski lokalne lub serwer plików). Lista wypełnia się w trakcie skanowania. Pomijane są pliki kopii zapasowych (`*.0001.rvt`), foldery `Backup` i lokalne kopie centrali. Modele zapisane w nowszym Revicie są wyszarzone; starsze można eksportować z ostrzeżeniem (eksport aktualizuje kopię). Pliki, których wersji nie da się odczytać, są wyszarzone z podpowiedzią.
3. Zaznacz modele. Pole wyszukiwania przyjmuje słowa w dowolnej kolejności lub regex; ▾ w nagłówkach Katalog i Wersja Revita filtruje. **Zaznacz wszystkie widoczne** dotyczy tylko widocznych, dostępnych wierszy.
4. Wybierz **folder wyników** (domyślnie `Documents\RevitExtractor`; każdy eksport dostaje własny folder `export-<data>-<id>`) i zakres: **Domyślny zakres Extractora** albo **Wspólny index.json** (odrzucany przy kilku modelach, jeśli zawiera identyfikatory widoków).
5. **Eksportuj** dodaje do kolejki jeden eksport na każdy zaznaczony model. **Wybierz widoki…** (zaznaczony dokładnie jeden model) czyta ten model w tle (odłączony, tylko do odczytu, worksety zamknięte, nigdy niezapisywany) i otwiera okno widoków: zaznacz widoki 2D, arkusze i widoki 3D, przełącz bazę SQLite i opcje, **Zapisz index.json…**, **Wstecz** lub **Eksportuj**.
6. **Okno statusu** pokazuje eksporty po kolei: stan, postęp i czas. Otwórz folder wyników, Otwórz w Analyzerze i Anuluj eksport działają na podświetlonym wierszu. Zamknięcie krzyżykiem minimalizuje okno, dopóki eksporty czekają lub trwają. Eksporty działają dalej po zamknięciu okna i Revita; niezaczęte są odrzucane, gdy Revit się zamknie.

Eksporty idą **po jednym**: w przetestowanej wersji Extractora drugi Extractor kończy się błędem na stałym potoku. Jeśli na komputerze działa już inny Extractor, kolejka czeka.

Ustawienia (foldery, folder wyników) są w pliku konfiguracji pyRevit, który wtedy zawiera ścieżki: nie udostępniaj go. Pamięć podręczna listy modeli to `%APPDATA%\RevitExtractor\catalog-cache.json`, także ze ścieżkami modeli.

Cały tekst jest po angielsku i po polsku, według ustawienia języka pyRevit (domyślnie angielski).

## Weryfikacja

2026-11-11, główny komputer (Revit 2023, bez pyRevit, CPython 3):
- wszystkie testy jednostkowe: 554 OK. Oba okna działają na atrapach WPF; `validate_xaml.ps1` ładuje oba pliki XAML w prawdziwym WPF;
- `run_extractor_integration.ps1`: prawdziwy Extractor uruchomiony z tej samej specyfikacji co kolejka: PASS (także `-Cancel`); `-Parallel 2` FAIL (stały potok);
- `v1_test_kit.ps1 -Setup` i `-Check` uruchomiono na takim eksporcie.

**Niezweryfikowane:** IronPython 2.7 (testy działają na CPython 3), pyRevit i wszystko wewnątrz Revita: wyszarzanie przycisku, okna wyboru, `BasicFileInfo.Extract` z timera skanu, prawdziwe otwarcie w tle, okno statusu i przekazanie między silnikami skryptów, zamknięcie Revita w trakcie eksportu, wiersze Revit 2025 i 2026 oraz polski tekst w prawdziwych oknach. Lista kontrolna do tego wszystkiego to `specs/v1-revit-test.md`; wyniki zostaną zapisane tutaj.
