# Eksport setup 2022

Przycisk pyRevit dla **Revita 2022**. Czyta widoki aktywnego projektu i zapisuje
`index.json` dla Extractora: widoki i arkusze 2D, widoki 3D oraz bazę SQLite.
Nie zmienia modelu, nie zapisuje RVT i nie uruchamia eksportu.

Skopiuj cały folder `ExportSetup22.pushbutton` do panelu pyRevit albo użyj go
w tej lokalizacji, jeśli rozszerzenie jest już podłączone. Wykonaj **Reload
pyRevit** i otwórz **Eksport setup 2022** w projekcie Revita 2022.

- **Tylko zaznaczone** zapisuje liczbowe `view_ids` z `ElementId.IntegerValue`.
  Pusty wybór blokuje zapis. Filtry nie usuwają wcześniejszych zaznaczeń.
- **Domyślny zakres Extractora** pomija listę ID; zakres wynika z zapisanego
  modelu i ustawień publikacji. Nie oznacza wszystkich widoków.
- Wyłączenie 2D/3D usuwa daną gałąź; SQLite jest jawne jako `properties_data.pdb`.
- Zachowane opcje zaawansowane: dane AEC, opis dokumentu, master views i F2D.
  Pominięto rozszerzone właściwości (parser zawsze je wyłącza) i topologię
  (klient nie rejestruje zadania eksportu). SQLite sprawdzamy przez
  `PropertyDbStorageType=Sqlite`; starsze `GeneratePropertyDB` zawsze zwraca
  `false` w tej instalacji i nie opisuje wyboru lokalnej bazy.
- Ten profil nie udostępnia IFC/DWG ani edycji setupów IFC. Zainstalowany klient
  `Revit 2022\RevitExtractor\RevitExtractor_Client.exe` w wersji `2025.3.0.12`
  nie zawiera zadań IFC/DWG ani nie rejestruje ich w `TaskManager.BuildTasks`.
  Sam odczyt `export.to` przez parser nie uruchamia tych eksportów.
  Pliki IFC/DWG wyeksportuj poleceniem **Eksportuj** w Revicie.

Przed eksportem zapisz RVT. Używaj indeksu z tego samego modelu i Extractora
z instalacji **Revita 2022** (`Revit 2022\RevitExtractor\RevitExtractor.exe`).
Launcher `Start-RevitExport.ps1` z tego repozytorium zaczyna od wyboru wersji;
wybierz **2022** albo podaj parametr `-RevitVersion 2022`.

Zakres wersji ustawiono na 2022–2022 w `bundle.yaml`, zgodnie z
[metadanymi pakietów pyRevit](https://github.com/pyrevitlabs/pyRevit/blob/develop/docs/extensions.md).
Kod ma dodatkową kontrolę wersji przy uruchomieniu i działa w IronPython 2.7.

## Walidacja

Z katalogu głównego repozytorium:

```powershell
python -B -m unittest discover -s .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests -v
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\validate_native_2022.ps1
```

Testy obejmują konfigurację i kontrolę wersji z atrapą hosta. Osobny skrypt
sprawdza osiem profili rzeczywistym parserem z instalacji Revita 2022.
Sprawdzono również kompilację oraz okno WPF w IronPython 2.7 / .NET Framework
poza Revitem, z zastępczym hostem i przykładową listą widoków.
Pełny eksport modelu i uruchomienie przycisku w sesji Revita wymagają próby
w aplikacji; test parsera ani test okna poza Revitem ich nie zastępują.
