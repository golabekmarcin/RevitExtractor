# Eksport setup — wariant dla starszych wersji (Revit 2022–2025)

[English](README.md) · Polski

Przycisk pyRevit dla **Revita 2022–2025**. Czyta widoki aktywnego projektu i zapisuje
`index.json` dla Extractora: widoki i arkusze 2D, widoki 3D oraz bazę SQLite.
Nie zmienia modelu, nie zapisuje RVT i nie uruchamia eksportu.
W Revicie nazywa się **Eksport setup**, tak jak wariant dla Revita 2026+. Dla Revita 2026 i nowszego użyj
[`ExportSetup.pushbutton`](../README.md).

Skopiuj cały folder `ExportSetupLegacy.pushbutton` do panelu pyRevit albo użyj go
w tej lokalizacji, jeśli rozszerzenie jest już podłączone. Wykonaj **Reload pyRevit**
i otwórz **Eksport setup** w projekcie Revita 2022–2025. Jeśli w panelu jest jeszcze starsza
kopia `ExportSetup22.pushbutton`, najpierw ją usuń; inaczej Revit 2022 pokaże dwa przyciski
eksportu. Przycisk i okno korzystają z ustawienia języka pyRevit, według tej samej reguły,
której pyRevit używa dla tytułu z `bundle.yaml`: polski pokazuje polski, każdy inny (lub brak
ustawienia) — angielski. Cały tekst okna jest w obu językach (`extractor_text.py`).
Wyszukiwanie typu widoku działa po nazwie angielskiej i polskiej, np. „sheets” lub „arkusze”.

- **Tylko zaznaczone** zapisuje liczbowe `view_ids`. ID pochodzi z `ElementId.Value`, gdy
  istnieje (2024+), a w innym przypadku z `ElementId.IntegerValue` (2022–2023). Parser
  Extractora czyta ID jako Int32. Pusty wybór blokuje zapis. Filtry nie usuwają wcześniejszych zaznaczeń.
- **Domyślny zakres Extractora** pomija listę ID; zakres wynika z zapisanego
  modelu i ustawień publikacji. Nie oznacza wszystkich widoków.
- Wyłączenie 2D/3D usuwa daną gałąź; SQLite jest jawne jako `properties_data.pdb`.
  Gdy baza jest wyłączona, a 3D włączone, indeks zawiera też `3dviewing.db_export: false`,
  bo Extractor w kompilacjach 2024.0.x czyta wyłącznie ten klucz.
- **Znane ograniczenie:** przy wyłączonym 3D Extractor 2024.0.x (np. Revit 2023 bez
  aktualizacji) i tak tworzy bazę, ponieważ czyta tylko `3dviewing.db_export`, a zapis tej
  gałęzi włączyłby 3D. Kompilacje 2025.3+ respektują `properties_data.pdb`. Okno pokazuje
  uwagę w wierszu stanu zawsze, gdy wybrana jest ta kombinacja.
- Zachowane opcje zaawansowane: dane AEC, opis dokumentu, master views i F2D.
  Pominięto rozszerzone właściwości i topologię: w instalacji 2022 parser zawsze wyłączał
  rozszerzone właściwości, a klient nie rejestrował zadania topologii.
  W 2023 zadanie rozszerzonych właściwości istnieje, ale nie sprawdzono go prawdziwym eksportem.
- Bez IFC/DWG i bez edycji setupów IFC: sprawdzone klienty Extractora dla 2022 (2025.3.0.12)
  i 2023 (2024.0.2022.0415) nie mają zadań IFC ani DWG w `TaskManager.BuildTasks`.
  Pliki IFC/DWG wyeksportuj poleceniem **Eksportuj** w Revicie.

Przed eksportem zapisz RVT. Używaj indeksu z tego samego modelu i Extractora z tej samej wersji
Revita (`Revit 20xx\RevitExtractor\RevitExtractor.exe`). Launcher `Start-RevitExport.ps1`
zaczyna od wyboru wersji; wybierz rok albo podaj parametr `-RevitVersion 2023`.

`bundle.yaml` ogranicza przycisk do 2022–2025 i zawiera angielski i polski tytuł oraz podpowiedź,
zgodnie z [metadanymi pakietów pyRevit](https://github.com/pyrevitlabs/pyRevit/blob/develop/docs/extensions.md).
Kod ma dodatkową kontrolę wersji przy uruchomieniu i działa w IronPython 2.7.

## Walidacja

Z katalogu głównego repozytorium:

```powershell
python -B -m unittest discover -s .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests -v
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\validate_native_legacy.ps1
```

Testy jednostkowe obejmują indeks, odczyt ID, kontrolę wersji i wybór języka, z atrapą hosta.
Drugi skrypt używa pierwszego znalezionego Extractora Revita 2022–2025 (albo `-ExtractorDirectory`)
i sprawdza dziewięć profili rzeczywistym parserem. Obsługuje oba warianty parsera (2025.3+ i 2024.0.x).

Sprawdzono:
- 9.11.2026: wszystkie dziewięć profili przechodzi z parserem Revita 2023 (2024.0.2022.0415).
- Wcześniej: osiem profili przeszło z parserem Revita 2022 (2025.3.0.12), a okno przetestowano w IronPython 2.7 / .NET Framework poza Revitem.

**Nie sprawdzono:**
- działania przycisku w Revicie 2022–2025
- okna po tej zmianie
- instalacji pyRevit z lokalizowanym `bundle.yaml`
- parserów Revita 2024/2025
- `db_export` z parserem 2025.3
- pełnego eksportu modelu

Testy parsera i atrapy nie zastępują próby w Revicie.
