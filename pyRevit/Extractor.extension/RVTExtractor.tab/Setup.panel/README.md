# Eksport setup — przycisk pyRevit

Wariant dla **Revita 2022** znajduje się w osobnym folderze
[`ExportSetup22.pushbutton`](ExportSetup22.pushbutton/README.md).
Poniższa instrukcja dotyczy wariantu `ExportSetup.pushbutton` dla Revita 2026.

Generator `index.json` dla natywnego Autodesk Revit Extractor 2026. Czyta widoki
aktywnego projektu RVT i zapisuje konfigurację w miejscu wybranym przez użytkownika.
Zakładka **Setup IFC** pozwala zastosować ustawienia IFC do danych modelu.
Nie uruchamia Extractora i nie zapisuje pliku RVT — zapisujesz go samodzielnie.

## Dodanie przycisku

Skopiuj **cały** folder `ExportSetup.pushbutton` do wybranego katalogu `*.panel`
w swojej aktywnej rozszerzalnej strukturze pyRevit, np.:

```text
TwojeNarzedzia.extension/
  TwojaZakladka.tab/
    Eksport.panel/
      ExportSetup.pushbutton/
        bundle.yaml
        script.py
        extractor_config.py
        extractor_model.py
        extractor_ui.py
        extractor_ifc.py
        extractor_ifc_storage.py
        ui.xaml
```

Następnie użyj Reload pyRevit. Przycisk wymaga projektu w Revit 2026+ oraz silnika
IronPython pyRevit (bez znacznika `#! python3`). Kod jest zgodny z IronPython 2.7.
Pliki przycisku są samodzielne: nie odwołują się do repozytorium po instalacji.
Nie rejestrujemy automatycznie rozszerzenia ani nie zmieniamy konfiguracji pyRevit.

## Użycie

1. Otwórz projekt RVT, który później ma przetwarzać Extractor.
2. Kliknij **Eksport setup**. Domyślnie włączone są 2D, 3D i SQLite.
3. Dla każdej grupy wybierz **Domyślny zakres Extractora** albo **Tylko zaznaczone**.
4. W trybie zaznaczania możesz filtrować typ, szukać po nazwie, numerze arkusza
   lub ElementId oraz zaznaczać/odznaczać wszystkie aktualnie widoczne pozycje.
   Zaznaczenia ukryte przez filtr pozostają zaznaczone i są uwzględniane w eksporcie.
5. Opcje zaawansowane zawierają dane AEC, opis dokumentu, master views, topologię,
   rozszerzone właściwości, F2D oraz dodatkowe formaty DWG i IFC.
6. Opcjonalnie przygotuj **Setup IFC** zgodnie z instrukcją poniżej.
7. Sprawdź zakładkę **Podgląd index.json** i kliknij **Zapisz index.json**.

Na [stronie Analyzer](https://kopecp.github.io/RevitExtractor/) wybierz **Eksportuj z Revita**
i pobierz `Start-RevitExport.ps1`. Ten jeden plik zaczyna od wyboru wersji Revita,
a następnie pyta o ścieżkę do indeksu, modelu RVT
oraz folderu wyników; `index.json` możesz zapisać w dowolnym miejscu.
Jeśli wystarcza podstawowy zakres 2D + 3D + parametry, naciśnij Enter przy pytaniu
o konfigurację w PowerShellu: użyje wbudowanego indeksu, bez potrzeby używania pyRevit.
Indeks musi pochodzić z tego samego modelu, który wskażesz w skrypcie,
i być zgodny z wybraną wersją Extractora. Dla tego wariantu przycisku wybierz Revit 2026.
Nowe/zmienione widoki muszą być zapisane w RVT przed uruchomieniem Extractora;
konfigurator sam modelu nie zapisuje. Starszy `extractorScript_v1.ps1` uruchamia
teraz ten sam launcher z wyborem wersji i modelu.

## Znaczenie ustawień

- **Domyślny zakres** nie oznacza wszystkich widoków. Nie zapisuje listy ID;
  wybór pozostaje po stronie Extractora (np. zapisanych zestawów publikacji).
- **Tylko zaznaczone** zapisuje `view_unique_ids`. Arkusze i widoki 2D trafiają
  do wspólnej listy `2dviewing`; 3D ma osobną listę. Pusty wybór blokuje zapis.
- Wyłączenie 2D/3D usuwa odpowiednią gałąź. Wpisanie `false` zamiast gałęzi
  nie jest prawidłowym sposobem wyłączenia widoków w tym natywnym parserze.
- SQLite jest zawsze zapisane jawnie jako `properties_data.pdb`.
- Domyślne opcje zaawansowane są pomijane, więc niezmieniony preset daje taki
  sam minimalny indeks jak wcześniejsza konfiguracja 2D + 3D + SQLite.
- Ustawienia zaawansowane 3D są zapisywane tylko, gdy włączone jest 3D;
  F2D tylko przy 2D, a rozszerzone właściwości tylko przy SQLite.
- DWG/IFC włącza `export.to`. IFC może dodatkowo wskazać nazwany setup zapisany
  przez naszą zakładkę. Dostępność i zakres wyników zależą od natywnego eksportera.
- Brak szablonów widoków, arkuszy zastępczych, niedrukowalnych widoków oraz
  samodzielnych zestawień. Widoki z modeli podlinkowanych nie są listowane.

Celowo nie wystawiamy `xref`, `xrefMap`, opcji AIM/chmurowych ani
`force_full_export` (nie dotyczy lokalnej bazy SQLite w tej wersji parsera).
To opcje innych trybów przetwarzania; `xrefMap` może dodatkowo przenosić pliki.
Odnajdywanie linków w zwykłej próbie pozostaje zadaniem Extractora.

## Setup IFC

1. Otwórz zakładkę **Setup IFC** i wybierz istniejący setup Autodesk, np. `PiKej`.
   Lista czyta nazwane setupy z modelu, zapisane jako JSON lub starsza mapa.
   Jeśli lista jest pusta, zapisz nazwany setup w oknie IFC Autodesk i otwórz
   konfigurator ponownie. `In-Session Setup` nie jest trwałym zapisem w RVT.
2. Sprawdź przeniesione opcje i opis uproszczeń. Ogólne IFC 4 oraz IFC 4.3 przechodzą
   na IFC 4 Reference View; inne wersje spoza wariantów edytora na IFC 2x3 CV2.
   Tryby linków „ten sam projekt/teren” przechodzą na **osobne pliki IFC**.
   Możesz poprawić obsługiwane opcje przed zastosowaniem.
3. Kliknij **Przygotuj setup dla Extractora**. Jedna transakcja dopisuje lub
   aktualizuje starszy zapis na **tym samym elemencie DataStorage**, pod **tą samą
   nazwą**. Oryginalny JSON pozostaje niezmieniony. Przycisk włącza IFC i wybór
   setupu w generowanym indeksie. Operację można cofnąć w Revicie.
4. Kliknij **Zapisz index.json**, zamknij okno i **zapisz RVT samodzielnie**.
   Przy modelu współdzielonym zapisz/synchronizuj tę wersję, którą odczyta Extractor.
5. Uruchom swój eksport. W jego logu sprawdź
   `Export IFC using settings: PiKej` (lub nazwę wybranego setupu) zamiast `(default)`.
   Zaznaczenie linków należy potwierdzić obecnością ich wynikowych plików IFC.

Przy następnym otwarciu wybierz ten sam setup, włącz **Eksportuj IFC** i
**Wskaż wybrany setup w index.json**. Jeśli jest tylko jeden setup, zostaje wybrany
automatycznie. Gdy jego źródłowy JSON się nie zmienił, formularz przywraca ostatnio
przygotowane ustawienia dla Extractora. Zmiana źródła wymaga ponownego przygotowania.
Niezastosowane zmiany blokują zapis indeksu korzystającego z tego setupu.
**Wczytaj ustawienia źródłowe** odtwarza propozycję ze źródła, zmieniając tylko
formularz. Reset całego okna przywraca ostatnio zapisane ustawienia dla Extractora.

Nazwa jest przekazywana przez `metadata.parameters.direct_params.IFCExportOption`.
Przygotowujemy kompatybilną reprezentację wybranego setupu, bez tworzenia nowej
nazwy ani nowego elementu DataStorage. Natywne `(default)` oznacza eksport
z pustymi opcjami API; nie odpowiada mu setup zapisany w RVT. Wyłączenie wyboru
setupu usuwa `IFCExportOption` z generowanego indeksu.

Dla źródła JSON świadomie przygotowujemy prostą próbę zgodności: plik `.ifc`,
bez filtra aktywnego widoku, faza według domyślnych reguł eksportera. Przenosimy
opcje widoczne w formularzu; pozostałe pola są wymienione w podglądzie pominięć.
Nie przenosimy m.in. georeferencji, zewnętrznych Pset/mapowań, zapisu IFC GUID
i teselacji. Ich oryginalne wartości pozostają w JSON. Dla istniejącej starszej
mapy zachowujemy pola niewystawione w edytorze i zmieniamy tylko widoczne opcje.
Lista widoków 2D/3D dotyczy danych przeglądarki, nie zakresu IFC.

### Przechowywanie i ograniczenia

Na istniejącym `DataStorage` zapisujemy dodatkową `Entity` według schematu Autodesk
`DCB88B13-594F-44F6-8F5D-AE9477305AC3`, nazwa schematu
`IFCExportConfigurationMap`, pole `MapField` typu `IDictionary<string,string>`.
Przy konwersji JSON słownik zawiera również `RVTExtractorOwner=ExportSetup/2`
oraz `RVTExtractorSourceJson` z kopią tekstu źródła. Pozwala to wykryć późniejszą
edycję w Autodesk; natywny czytnik ignoruje te klucze. Nie zmieniamy definicji
istniejącego schematu. Konflikt nazwy (także z wbudowanymi setupami), niezgodny
schemat, zmienione dane i odmowa wypożyczenia elementu blokują zapis.
Błąd transakcji powoduje wycofanie zmian. Otwarcie okna tylko czyta dane.

Okno IFC Autodesk 2026 zapisuje setupy w innym schemacie:
`C2A3E6FE-CE51-4F35-8FF1-20C34567B687`, z JSON-em w polu `MapField`.
Zainstalowany Extractor 2026.7.2.16 nie czyta tego schematu. Zapis konfiguracji
w oknie Autodesk może usunąć starszą reprezentację, zapisując ponownie JSON.
Dlatego po edycji w Autodesk otwórz naszą zakładkę ponownie i przygotuj setup
dla Extractora przed następnym eksportem. W razie duplikatów nazw przygotowanie
jest blokowane, aby nie dopuścić do błędu natywnego czytnika.

Definicję starszego schematu sprawdzono w
[kodzie Autodesk IFC Release_20.0.0](https://github.com/Autodesk/revit-ifc/blob/Release_20.0.0/Source/IFCExporterUIOverride/IFCExportConfigurationsMap.cs).
Obsługiwane klucze oraz wybór nazwy potwierdzono w lokalnym
`RevitExtractor_Client.dll` i `ExtractorUtility_2025.dll`.
Opis ograniczenia nowych konfiguracji:
[Autodesk — Export IFC from RVT](https://aps.autodesk.com/blog/export-ifc-rvt-using-revit-automation-api-part-i).

## Walidacja

```powershell
python -B -m unittest discover -s .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests -v
```

Testy obejmują konfigurację, konwersję JSON i obsługę zapisu. Sprawdzono kompilację w IronPython 2.7,
inicjalizację i układ WPF, wiązanie checkboxów z zaznaczeniami, zachowanie wyboru
przy filtrowaniu, reset oraz zapis i zastępowanie pliku UTF-8. Test okna działał
poza Revitem, z zastępczym środowiskiem aplikacji i przykładową listą widoków.
Nowa zakładka została sprawdzona z atrapą zapisu: otwarcie/reset nie zapisują,
konwersja zachowuje źródło, zastosowanie ustawia jego nazwę w indeksie, a
niezastosowane zmiany blokują zapis. Sprawdzono ponowne otwarcie i pustą listę.
Testy transakcji z atrapą API obejmują rollback, błędny commit, blokadę współdzielenia,
zmianę danych po wypożyczeniu i modele bez możliwości zapisu. Nie zastępują testu
prawdziwej transakcji, Undo ani współdzielenia w Revicie.

Parser Autodesk poprawnie odczytał siedem konfiguracji: domyślną, wybrane 2D,
wybrane 3D, bez bazy, samą bazę, opcje zaawansowane oraz same dodatkowe formaty.
Parser odczytał również `IFCExportOption=PiKej` z wygenerowanego
indeksu; adapter storage zaimportowano w IronPython z rzeczywistym RevitAPI.
Walidacja parserem potwierdza odczyt opcji, ale nie pełny eksport. Pierwsze
uruchomienie przycisku w pyRevit, rzeczywiste listowanie modelu i eksport
nowych kombinacji (szczególnie bez SQLite, F2D, DWG/IFC), zapis i ponowne odczytanie
setupu z RVT oraz eksport linków wymagają próby w Revicie.

Źródła: lokalny parser `Autodesk.ExtractorUtility.IndexJson` z instalacji Revit
2026.7.2.16 oraz [API formularzy pyRevit](https://docs.pyrevitlabs.io/reference/pyrevit/forms/_ipy/).
