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
| `rx_reader.py` | model-reader | otwarcie w tle (odłączone, workset-y zamknięte), lista widoków, dokładnie jedno `Close(False)`; nigdy nie zapisuje |
| `rx_runner.py` | export-runner | folder eksportu, proces Extractora przez `cmd.exe`, kolejka (po jednym), anulowanie przez `taskkill /T /F`, sprawdzenie wyniku |

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

**Niezweryfikowane:** IronPython 2.7 i nic wewnątrz Revit. Dotyczy to `BasicFileInfo.Extract`, prawdziwego otwarcia w tle, `DotNetStarter` (`ProcessStartInfo` w IronPythonie), zamknięcia Revita w trakcie eksportu i parsera w wersji 2025.3. Wszystko to jest w `specs/v1-revit-test.md`, na test właściciela po zakończeniu v1. Żaden przycisk nie używa jeszcze tych modułów.
