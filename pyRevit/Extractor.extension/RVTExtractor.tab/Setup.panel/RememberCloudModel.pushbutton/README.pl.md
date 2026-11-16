# Zapamiętaj model z chmury (Revit 2022 i nowsze)

[English](README.md) · Polski

Przycisk pyRevit na wypadek, gdy dzienniki Revita nie nazywają modelu na liście chmurowej przycisku Eksport: przy otwartym modelu z chmury (ACC) zapamiętuje nazwę projektu, nazwę pliku i łącza Revit tego modelu w pamięci użytkownika (`%APPDATA%\RevitExtractor\cloud-catalog.json`). Przycisk Eksport czyta tę pamięć.

**Stan: zbudowany i przetestowany jednostkowo poza Revitem. Jeszcze nie uruchomiony w Revicie.** Zob. Weryfikacja.

## Użycie

1. Otwórz w Revicie model z chmury (Autodesk Docs / ACC). Bez otwartego projektu przycisk jest wyszarzony.
2. Kliknij **Zapamiętaj model z chmury**.
3. Krótki komunikat potwierdza zapamiętanie tego modelu i podaje liczbę zapamiętanych łączy. Nazwy i identyfikatory nie są pokazywane.

Jeśli otwarty model nie jest modelem z chmury, pojawia się komunikat i nic nie jest zapisywane.

## Co robi

- Czyta `Document.IsModelInCloud`, ścieżkę modelu w chmurze (identyfikatory projektu i modelu, potem zwalnia obiekt), ścieżkę widoczną dla użytkownika (`Autodesk Docs://<projekt>/<plik>.rvt`, analizowaną ostrożnie) i listę łączy.
- Zapisuje nazwy w pamięci. Łącza są zapisywane razem z datą kopii tego modelu w `%LOCALAPPDATA%\Autodesk\Revit\Autodesk Revit <rok>\CollaborationCache`; gdy takiej kopii nie ma, zapisywane są tylko nazwy, a komunikat o tym informuje.
- **Tylko odczyt modelu:** bez transakcji, zapisu i synchronizacji. Kopia w pamięci podręcznej jest tylko wypisywana (nazwy i czasy), nigdy otwierana ani zmieniana.
- Pamięć zawiera nazwy projektów i plików klienta. Zostaje w Twoim profilu; nie udostępniaj jej i nie commituj.

Cały tekst jest po angielsku i po polsku, według ustawienia języka pyRevit (domyślnie angielski).

## Weryfikacja

Testy jednostkowe z atrapą dokumentu i pyRevit (`tests/test_remember_cloud.py`, CPython 3): dokument spoza chmury nic nie zapisuje, dokument z chmury zapisuje pamięć, brak transakcji, zwolniona ścieżka modelu, tekst po angielsku i polsku, reguły składni IronPython.

**Niezweryfikowane:** IronPython 2.7, pyRevit (wyszarzanie przycisku, `doc-project` dla modelu z chmury) i wszystko w Revicie: rzeczywisty kształt ścieżki widocznej dla użytkownika, `GetCloudModelPath` na prawdziwym modelu z chmury, lista łączy i folder pamięci podręcznej prawdziwej sesji. Lista dla właściciela: `specs/v1-revit-test.md` (część H).
