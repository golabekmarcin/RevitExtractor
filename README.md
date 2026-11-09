# RevitExtractor

**[Otwórz Analyzer](https://kopecp.github.io/RevitExtractor/)** — przeglądarka lokalnych eksportów Autodesk Revit Extractor.

## Od RVT do przeglądarki

1. W Revicie zapisz model RVT i używane zestawy **Collaborate → Publish Settings**.
   Do podstawowej próby nie potrzebujesz pyRevit ani osobnego `index.json` — konfiguracja jest zaszyta w skrypcie.
2. Opcjonalnie przygotuj własny `index.json` przyciskiem **Eksport setup** w pyRevit,
   np. aby wskazać konkretne widoki lub włączyć IFC.
   [Instrukcja instalacji przycisku](pyRevit/Extractor.extension/RVTExtractor.tab/Setup.panel/README.md).
   Możesz sklonować repo (`git clone --branch online https://github.com/kopecp/RevitExtractor.git`)
   i skopiować cały `ExportSetupLegacy.pushbutton` dla Revita 2022–2025 albo
   `ExportSetup.pushbutton` dla Revita 2026 do swojego panelu pyRevit.
   Własna konfiguracja musi pochodzić z tego samego modelu.
3. Na stronie wybierz **Eksportuj z Revita → Pobierz PowerShell**.
   Pobierasz jeden plik `Start-RevitExport.ps1`. Potrzebujesz Windows i zainstalowanej wybranej wersji Revita z `RevitExtractor.exe`; skrypt niczego nie instaluje.
4. Uruchom skrypt przez **Uruchom za pomocą programu PowerShell** albo w folderze pobranego pliku:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-RevitExport.ps1
   ```

   Parametr `ExecutionPolicy` dotyczy tylko tego procesu; nie zmienia zasad Windows na stałe.
5. Najpierw wybierz **wersję Revita**: wpisz numer pozycji lub rok wersji z listy. **M** pozwala wskazać inny folder instalacji, **Q** anuluje.
   Skrypt wyszukuje instalacje z Extractorem w `Program Files\Autodesk` i rejestrze Windows. Nie wybiera automatycznie najnowszej wersji.
   Przy pytaniu o konfigurację naciśnij **Enter**, aby użyć wbudowanej. Możesz też wkleić ścieżkę do własnego `index.json` lub wybrać **P**, aby otworzyć okno wyboru.
   Następnie wskaż `.rvt` — wklej ścieżkę albo naciśnij Enter, aby wybrać model w oknie.
   Wybierz folder wyników (domyślnie `Dokumenty\RevitExtractor`) i potwierdź eksport.
   Model i własny indeks powinny odpowiadać wybranej wersji; dostępne formaty eksportu zależą od jej Extractora.
6. Poczekaj na zakończenie. Każdy eksport dostaje osobny folder `export-DATA-ID` z `output`, `logs`, `journals`, użytym `index.json`, `console.log` i `stderr.log`.
7. W Analyzerze kliknij **Otwórz folder** i wybierz `output` lub jego bezpośredni folder nadrzędny.

Przeglądarka obsługuje SVF 3D, PDF, parametry, tabele SQLite, modele źródłowe i kategorie.
Nie otwiera bezpośrednio `.rvt`. Skrypt uruchamiasz samodzielnie w Windows.
Starszy `extractorScript_v1.ps1` przekazuje teraz uruchomienie i parametry do tego samego launchera
z wyborem wersji. Główny `index.json` pozostaje przykładem z konkretnego projektu;
do nowego modelu użyj konfiguracji wbudowanej lub własnego indeksu.

## Wbudowany indeks

Enter przy wyborze konfiguracji (lub parametr `-UseDefaultIndex`) wybiera:

```json
{
  "metadata": {
    "parameters": {
      "derivative_type": {
        "2dviewing": {},
        "3dviewing": {},
        "properties_data": { "pdb": true }
      }
    }
  }
}
```

To podstawowy profil 2D + 3D + baza parametrów, bez IFC/DWG ani listy `view_unique_ids`.
Dobór widoków pozostaje po stronie natywnego Extractora. Nie oznacza eksportu wszystkich widoków ani gwarantowanego krótkiego przebiegu.
W Revit zestawy do publikacji ustawia się w **Collaborate → Publish Settings**;
[dokumentacja Autodesk](https://help.autodesk.com/cloudhelp/2026/ENU/Revit-Cloud/files/GUID-09FBF9E2-6ECF-447D-8FA8-12AB16495BC3.htm)
opisuje domyślny widok 3D i arkusze 2D przy publikowaniu do chmury.
Dokładny zestaw wyników lokalnego Extractora zależy od zapisanego RVT i wymaga sprawdzenia na danym modelu.

Skrypt zapisuje wbudowany indeks jako `index.json` w nowym folderze eksportu dopiero po potwierdzeniu.
Własny indeks jest kopiowany bez zmiany zawartości. Niepoprawny własny plik powoduje błąd;
skrypt nie zastępuje go po cichu szerszą konfiguracją domyślną.

## GitHub Pages i dane lokalne

- Użyj aktualnego Chrome lub Edge na komputerze. Strona wymaga HTTPS, service workerów i WebGL.
- Folder jest udostępniany wyłącznie do odczytu. Aplikacja nie wysyła jego plików na GitHub ani do usługi konwersji.
- Pliki są dostępne podczas otwartej sesji. Po odświeżeniu strony wybierz folder ponownie.
- Silnik Autodesk Viewer 7.130.0 ładuje się z CDN Autodesk, więc do uruchomienia 3D potrzebny jest internet. PDF.js i SQLite WASM są częścią strony.
- Duże bazy właściwości i geometria zajmują RAM. Tabele SQLite ładują `model.sdb` do pamięci dopiero przy pierwszym wejściu w tabelę.
- Lokalny Analyzer z Node.js nadal działa: [instrukcja](Analyzer/README.md).

## Aktualizowanie strony

Workflow [pages.yml](.github/workflows/pages.yml) publikuje tylko `Analyzer/dist` po pushu na **`online`**.
Nie publikuje modeli, folderów `test-*`, przykładowego `index.json` ani całego repozytorium.
Workflow sprawdza składnię, wykonuje testy niezależne od prywatnych eksportów i buduje stronę.
PR-y do `online` i `master` są sprawdzane bez publikacji.

W repozytorium wybierz **Settings → Pages → Source: GitHub Actions**.
Środowisko `github-pages` musi dopuszczać branch `online`.
Po późniejszym merge do `master` publikacja nadal następuje z `online`;
aby przełączyć ją na `master`, zmień zarówno `push.branches`, warunek `deploy.if`, jak i regułę środowiska.
Mechanizm opisuje [dokumentacja GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

Budowanie lokalne (Node.js 24+):

```powershell
cd Analyzer
npm ci --ignore-scripts --omit=optional
npm run check
npm run test:pages
npm run build:pages
```

Wynik `Analyzer/dist` należy podawać przez HTTP localhost lub HTTPS, również pod ścieżką `/RevitExtractor/`.
Otwieranie HTML przez `file://` nie obsługuje trybu Pages.
`npm test` dodatkowo wykonuje dotychczasowe testy lokalnego serwera, wymagające próbnego eksportu Snowdon.

## Skrypt bez uruchamiania eksportu

Do sprawdzenia własnych ścieżek i konfiguracji:

```powershell
.\Start-RevitExport.ps1 -RevitVersion 2022 -IndexPath 'D:\Projekt\index.json' -ModelPath 'D:\Projekt\Model.rvt' -OutputParent 'D:\Eksporty' -ValidateOnly
```

Bez `-IndexPath` walidacja używa wbudowanej konfiguracji; można też jawnie dodać `-UseDefaultIndex`.
Parametry `-IndexPath` i `-UseDefaultIndex` wykluczają się.
Ta opcja nie uruchamia Revita i nie tworzy folderów. Właściwy eksport zawsze pyta o potwierdzenie.
`-ValidateOnly` wymaga `-RevitVersion` albo `-RevitDirectory` i nie pyta o wybór instalacji.
W zwykłym uruchomieniu te parametry również pozwalają pominąć menu wersji.
Jeżeli podasz oba, skrypt sprawdzi, czy wskazany folder zawiera wybraną wersję Revita.
Lista wersji nie jest ograniczona do konkretnego zestawu lat; wymagane są `Revit.exe`
i `RevitExtractor\RevitExtractor.exe` w wybranej instalacji. Numer kompilacji Extractora
nie musi być zgodny z rokiem Revita.
