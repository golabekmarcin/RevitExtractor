# Extractor.extension `lib/`

[English](README.md)

Wspólne moduły dla wszystkich przycisków tego rozszerzenia. pyRevit dodaje ten folder do `sys.path` każdego z nich. Folder samego przycisku jest pierwszy, więc przycisk nadal używa własnej kopii pliku o tej samej nazwie.

| Plik | Moduł (`specs/`) | Zadanie |
| --- | --- | --- |
| `rx_i18n.py` | shared-ui | `tr(english, polish)`, według ustawienia języka pyRevit |
| `rx_theme.xaml` | shared-ui | motyw okien (klucze `Rx*`) |
| `rx_search_bar.py`, `rx_search_bar.xaml`, `rx_search_placeholder.py` | shared-ui | pole wyszukiwania z ✕, regex i „Wyczyść wszystkie filtry” |
| `rx_column_filter_model.py`, `rx_column_filter_ui.py` | shared-ui | filtry w nagłówkach kolumn, jak w Excelu |
| `rx_capabilities.py` | capabilities | co obsługuje uruchomiony Revit, oraz `element_id_value` |
| `rx_index.py` | index-builder | jedno `build_index` dla każdej wersji Revita, z takim samym wynikiem jak stare przyciski |
| `rx_catalog.py` | model-catalog | lista plików `.rvt` w zapamiętanych folderach, z regułami pomijania, wersjami nowsza/starsza/nieznana i pamięcią podręczną w `%APPDATA%\RevitExtractor\catalog-cache.json`. Ta pamięć zawiera ścieżki modeli: nigdy jej nie commituj ani nie udostępniaj |
| `rx_reader.py` | model-reader | otwarcie w tle (odłączone, workset-y zamknięte), lista widoków, dokładnie jedno `Close(False)`; nigdy nie zapisuje. `links=True` wypisuje też linki Revit modelu z chmury (`collect_cloud_links`) |
| `rx_status.py`, `rx_status_ui.py`, `rx_status.xaml` | status-window | niemodalne okno statusu kolejki eksportów: postęp z `console.log`, Otwórz folder wyników, Otwórz w Analyzerze, Anuluj eksport. Kolejka jest publikowana w danych AppDomain, a między silnikami skryptów przechodzi tylko tekst JSON |
| `rx_runner.py` | export-runner | folder eksportu, proces Extractora przez `cmd.exe`, kolejka (po jednym), anulowanie przez `taskkill /T /F`, sprawdzenie wyniku. Zadanie z chmury ma też stan `staging` (kopiowanie w kawałkach), który kopiuje pliki z pamięci podręcznej do `<eksport>\model` przed startem Extractora i usuwa kopie po zakończeniu drzewa procesów (`model\stage.json` zostaje) |
| `rx_cloud.py` | cloud-catalog | czysta logika źródła Chmura: czyta dzienniki Revita (UTF-16, UTF-8, ANSI) po nazwy projektów i plików, skanuje `%LOCALAPPDATA%\Autodesk\Revit\Autodesk Revit <rok>\CollaborationCache`, łączy je po GUID projektu + GUID modelu, trzyma wybór, nazwy i listy linków w `%APPDATA%\RevitExtractor\cloud-catalog.json` i planuje, które pliki z pamięci podręcznej skopiować. Bez importu Revit, .NET i `clr` (pilnuje tego test). **Plik pamięci zawiera nazwy projektów i plików klienta: nigdy go nie commituj ani nie udostępniaj** |
| `rx_cloud_stage.py` | cloud-catalog | jedyne operacje na plikach źródła Chmura: sprawdzenie wolnego miejsca i kopiowanie w kawałkach. Źródła są otwierane tylko do odczytu (`rb`), cel nigdy nie jest nadpisywany, a plik z pamięci podręcznej, który zmienił się w trakcie kopiowania, kończy zadanie błędem. Do pamięci podręcznej nic nie jest zapisywane |

Zasady:
- Każdy plik zaczyna się od `rx_`, żeby nie kolidował z modułem innego rozszerzenia we wspólnym silniku IronPython.
- Tylko IronPython 2.7 (zob. `CLAUDE.md`).
- `rx_capabilities.py` nie importuje niczego z Revit, pyRevit ani .NET; pilnuje tego test.
- **Tymczasowe duplikaty:** `ExportSetupLegacy.pushbutton` ma nadal własne kopie plików shared-ui. `tests/test_shared_ui.py` wymaga, żeby obie kopie były identyczne, poza linią importu `tr`. Kopie i ten test usuwamy razem ze starymi przyciskami (Q12).

## Weryfikacja

2026-11-10, główny komputer (Revit 2023, bez pyRevit):
- testy jednostkowe: 153 OK. Testy paska wyszukiwania, filtrów kolumn i motywu z etapu 1 działają na kopii w przycisku i w `lib/`;
- `tests/validate_xaml.ps1`: `rx_theme.xaml` i `rx_search_bar.xaml` ładują się w prawdziwym WPF (.NET Framework, Windows PowerShell 5.1). Uszkodzony XAML daje FAIL i kod wyjścia 1.

Również 2026-11-10, ten sam komputer:
- **testy jednostkowe: 340 OK** ze wszystkimi modułami;
- **`validate_native_legacy.ps1`:** pliki index z `rx_index` są takie same jak ze starych przycisków dla 9 profili starszych i 3 profili najnowszego wiersza. Natywny parser je przyjął (Extractor 2024.0.2022.0415): 35 PASS i 2 SKIP, bo `view_unique_ids` wymaga nowszego Extractora;
- **`run_extractor_integration.ps1`**, prawdziwe uruchomienie Extractora według specyfikacji uruchomienia z `rx_runner`, na przykładowym modelu Dynamo:
  - zwykły eksport **PASS**: `Success Jobs: 13, Failed Jobs: 0`, 64 pliki wynikowe, SHA-256 przykładowego modelu bez zmian;
  - `-Cancel` **PASS**: zakończono całe drzewo procesów, a folder eksportu pozostał;
  - `-Parallel 2` **FAIL**: drugie uruchomienie zatrzymało się z błędem `All pipe instances are busy` (stała nazwa potoku `Main_Process_to_Client_0_Pipe`). Z tą wersją eksporty muszą iść po jednym, więc `PARALLEL_VERIFIED` pozostaje False.
- `rx_reader`: testy na ścisłych atrapach (stubach), a 13 z 13 celowo zepsutych kopii zostało wykrytych (bez zapisu, dokładnie jedno `Close(False)`).

**Niezweryfikowane:** IronPython 2.7 i nic wewnątrz Revit. Dotyczy to `BasicFileInfo.Extract`, prawdziwego otwarcia w tle, `DotNetStarter` (`ProcessStartInfo` w IronPythonie), okna statusu i jego przekazania między silnikami skryptów, zamknięcia Revita w trakcie eksportu i parsera w wersji 2025.3. Wszystko to jest w `specs/v1-revit-test.md`, na test właściciela po zakończeniu v1.

2026-11-11, ten sam komputer: wszystkie testy jednostkowe 554 OK; `validate_xaml.ps1` ładuje każdy XAML z `lib/` i `Export.pushbutton/`. `Export.pushbutton` to pierwszy przycisk używający tych modułów (`../RVTExtractor.tab/Setup.panel/Export.pushbutton/README.pl.md`).

2026-11-16, ten sam komputer (cloud-catalog, `rx_cloud`, `rx_cloud_stage`):
- **testy jednostkowe: 924 OK**; `validate_xaml.ps1`: 6 PASS;
- `run_extractor_integration.ps1 -Cloud` **PASS**: fałszywe drzewo pamięci podręcznej w `%TEMP%` (przykład Dynamo zapisany pod nazwami GUID, syntetyczny dziennik), skopiowane przez `rx_runner.Queue` i wyeksportowane prawdziwym Extractorem (`staging` -> `running` -> `ok`, `Success Jobs: 13, Failed Jobs: 0`); obie kopie w pamięci podręcznej zachowały SHA-256 i czasy, a po eksporcie został tylko `model\stage.json`. Zwykły eksport nadal daje PASS;
- czas skanowania (100 syntetycznych dzienników po 1 MB + 1000 plików pamięci podręcznej): 2,9 s łącznie, najdłuższy krok 0,04 s.

**Niezweryfikowane dla kodu chmury:** IronPython 2.7 i wszystko wewnątrz Revita. Dotyczy to wierszy dzienników z innych lat Revita niż 2022, otwarcia w tle pliku z pamięci podręcznej, listy linków prawdziwego modelu z chmury, szybkości kopiowania obok działającego Revita, geometrii linków w widoku federacyjnym i przycisku Zapamiętaj model z chmury. Wszystko to jest w części H pliku `specs/v1-revit-test.md`.
