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

Zasady:
- Każdy plik zaczyna się od `rx_`, żeby nie kolidował z modułem innego rozszerzenia we wspólnym silniku IronPython.
- Tylko IronPython 2.7 (zob. `CLAUDE.md`).
- `rx_capabilities.py` nie importuje niczego z Revit, pyRevit ani .NET; pilnuje tego test.
- **Tymczasowe duplikaty:** `ExportSetupLegacy.pushbutton` ma nadal własne kopie plików shared-ui. `tests/test_shared_ui.py` wymaga, żeby obie kopie były identyczne, poza linią importu `tr`. Kopie i ten test usuwamy razem ze starymi przyciskami (Q12).

## Weryfikacja

2026-11-10, główny komputer (Revit 2023, bez pyRevit):
- testy jednostkowe: 153 OK. Testy paska wyszukiwania, filtrów kolumn i motywu z etapu 1 działają na kopii w przycisku i w `lib/`;
- `tests/validate_xaml.ps1`: `rx_theme.xaml` i `rx_search_bar.xaml` ładują się w prawdziwym WPF (.NET Framework, Windows PowerShell 5.1). Uszkodzony XAML daje FAIL i kod wyjścia 1.

**Niezweryfikowane:** IronPython 2.7 i nic wewnątrz Revit.
- Nadal otwarte: sprawdzenie przez właściciela w Revit 2022, czy stary przycisk „Export setup” nadal się otwiera i wyszukuje przy obecnym `lib/`.
- Żaden przycisk nie używa jeszcze `rx_capabilities`.
