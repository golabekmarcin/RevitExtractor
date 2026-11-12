# Revit Extractor · Analyzer

Lokalna aplikacja webowa do oglądania modelu SVF, rysunków PDF oraz właściwości z eksportu RevitExtractor. Główny ekran to interaktywny viewer 3D połączony z inspektorem elementów.

## GitHub Pages

**[Otwórz wersję online](https://kopecp.github.io/RevitExtractor/)** w Chrome lub Edge i wybierz **Otwórz folder**.
Strona odczytuje wskazany `output` bez lokalnego Node.js; pliki modelu pozostają na komputerze.
Po odświeżeniu wybierz folder ponownie. Dostępne są model 3D, PDF-y, parametry i tabele SQLite.
Przycisk **Eksportuj z Revita** zawiera instrukcję oraz jeden interaktywny skrypt PowerShell.
`Start-RevitExport.ps1` zaczyna od wyboru zainstalowanej wersji Revita z Extractorem.
Można też ręcznie wskazać folder instalacji; lista wersji nie jest ograniczona do 2026.

Publikację z brancha `online`, skrypt i wymagania opisuje [główna instrukcja](../README.md).
`npm run build:pages` tworzy osobny katalog `dist`; lokalny serwer korzysta z `public`.
Oba tryby współdzielą interpretację właściwości i modeli źródłowych.

## Uruchomienie lokalne

1. Uruchom **`Start-Analyzer.cmd`** w tym folderze.
2. Otworzy się przeglądarka pod adresem **http://127.0.0.1:4317**.
3. Aplikacja automatycznie odnajdzie eksporty w sąsiednich folderach `*/output` i otworzy najnowszy.
4. Aby otworzyć inny eksport, użyj **Otwórz folder**. Wybierz folder w oknie systemowym albo wklej jego pełną ścieżkę. Obsługiwane są folder `output`, jego katalog nadrzędny oraz `Resource`.
5. Zatrzymaj serwer przez `Ctrl+C` w oknie terminala.

Wymagany **Node.js 24 lub nowszy** (zainstalowany samodzielnie lub z Company Portal) oraz przeglądarka z WebGL (np. Chrome lub Edge). Python i venv nie są potrzebne. Zależności npm są tylko w lokalnym `node_modules`; `Start-Analyzer.cmd` zainstaluje je, jeśli brakuje PDF.js, i zaufa magazynowi certyfikatów Windows (`NODE_USE_SYSTEM_CA=1`), więc firmowy proxy podpisujący HTTPS działa bez dodatkowej konfiguracji. Nie ma instalacji globalnych ani kroku budowania frontendu.

English: needs **Node.js 24 or later** (install it yourself or from the Company Portal) and a WebGL browser (Chrome or Edge). No Python. `Start-Analyzer.cmd` installs the npm packages into the local `node_modules` when PDF.js is missing and trusts the Windows certificate store (`NODE_USE_SYSTEM_CA=1`), so a company proxy that re-signs HTTPS works without extra setup. If `npm ci` still reports a certificate error, run `npm config set cafile "<path to root.pem>"`; never disable `strict-ssl`.

Uruchomienie z terminala:

```powershell
cd C:\Users\Piotr.Kopec\source\RevitExtractor\Analyzer
npm ci --omit=optional --ignore-scripts
npm start
```

Opcjonalnie:

```powershell
node server.mjs --port 4318
node server.mjs --output "C:\eksporty\projekt\output" --open
```

## Przykład na ostatnim eksporcie

Przetestowany zestaw: `../test-333cd21fb42b444282bb5082acb2573d/output` — **Snowdon Towers Sample HVAC**, 23.10.2026.

- 1 widok 3D: **3D HVAC Layout**.
- **4639** identyfikatorów obiektów z geometrią w tym widoku.
- **39** PDF-ów: rzuty, rzuty sufitów, elewacje i arkusze.
- **160 488** rekordów bazy właściwości. Liczba obejmuje również typy, rekordy pomocnicze i dane linków; nie jest liczbą elementów widocznych w 3D.

Szybki scenariusz:

1. Obróć model lewym przyciskiem myszy, przybliż kółkiem, przesuń środkowym przyciskiem.
2. Kliknij urządzenie lub kanał — inspektor po prawej pokaże jego parametry.
3. Użyj **Zbliż**, **Izoluj**, **Ukryj** i **Pokaż wszystko**.
4. **Przekrój** włącza/wyłącza płaszczyznę cięcia, **Drzewo** otwiera strukturę modelu. Standardowy pasek Autodesk zawiera także dodatkowe narzędzia nawigacji i pomiaru.
5. W zakładce **Dane** wyszukaj `1365662`. Wybierz **Round Duct [1365662]** (`dbId 3199`) i użyj **Zbliż** albo **Izoluj**, aby przejść do tego kanału.
6. W **Rysunkach** wyszukaj `M101` i otwórz arkusz. PDF ma osobne przybliżenie oraz obsługę stron.

## Co obsługuje wersja 0.1

| Obszar | Możliwości |
| --- | --- |
| Model | Bezpośrednie wczytanie SVF i plików geometrii, obrót/zoom/pan, wybór, izolowanie, ukrywanie, przekrój, drzewo modelu |
| Inspektor | dbId, Revit ElementId, UniqueId, grupy parametrów, wyszukiwanie parametrów, wartości odziedziczone z typu |
| Rysunki | Galeria miniatur, wyszukiwanie, lokalny renderer PDF.js, powiększenie, strony, otwarcie oryginalnego PDF |
| Dane | Wyszukiwanie nazw i identyfikatorów, filtr kategorii, stronicowanie po filtrowaniu, eksport bieżącej strony do CSV |
| SQLite | Podgląd czterech oryginalnych tabel `model.sdb`: identyfikatory, atrybuty, wartości i EAV |
| Eksporty | Wykrywanie sąsiednich wyników, przełączanie zestawów, otwarcie własnej ścieżki |

`dbId` jest identyfikatorem rekordu w danym eksporcie; **nie jest Revit ElementId**. Połączenie viewera z inspektorem używa dbId. Rekord bez geometrii w bieżącym widoku nadal można obejrzeć w tabeli; przyciski nawigacji 3D są wtedy wyłączone.

Parametry zachowują **wartości i jednostki z eksportu**. Aplikacja nie przelicza ich automatycznie na SI. Informacja „z typu” oznacza wartość pochodzącą z powiązanego rekordu typu.

## Widoczność modeli i kategorii

Otwórz **Drzewo → Modele**. Każdy model źródłowy ma oczko; po rozwinięciu zobaczysz kategorie z osobnymi oczkami. Wyłączenie kategorii działa tylko w danym modelu. Wyłączenie całego modelu zachowuje ustawienia jego kategorii i pojedynczych ukrytych elementów.

- **Kategorie** zachowuje dotychczasowe drzewo Autodesk z rodzinami i typami. Oczko kategorii działa globalnie, pozostawiając wyłączone modele wyłączone.
- Złote oznaczenie wskazuje częściową widoczność. Licznik pokazuje widoczne/wszystkie obiekty geometrii bieżącego widoku; obejmuje również geometryczne części elementów złożonych, więc może różnić się od licznika instancji w natywnym drzewie.
- Kategorie odpowiadają gałęziom drzewa bieżącego widoku. Np. zagnieżdżona część okna jest sterowana z gałęzi Windows, nawet jeśli jej własny rekord właściwości ma kategorię Generic Models.
- Model bez geometrii w danym widoku ma nieaktywne oczko. Samo odwołanie do niezaładowanego linka, bez metadanych eksportu lub rekordów z jego prefiksem, nie tworzy modelu źródłowego.
- **Pokaż wszystko** resetuje widoczność obu poziomów. Ustawienia nie są zapisywane między widokami, eksportami ani sesjami.
- Ukrywanie nie pozostawia półprzezroczystych obiektów. Przybliżenie i izolacja nie włączają po cichu modelu lub kategorii wyłączonej w drzewku.

Na eksporcie `test-f5a35b5a55bf40a9a4b14ecd2ca573d7/output` widok **Cover** zawiera geometrię wszystkich sześciu linków; widok **{3D}** ma samą geometrię HVAC. Przełączniki nie mogą pokazać geometrii, której nie zapisano w wybranym SVF.

Podgląd: [drzewo modeli](docs/source-models.png). Wyniki testów: [weryfikacja widoczności](docs/VERIFICATION-models.md).

## Lokalność i ograniczenia

- Eksporty są odczytywane bez kopiowania i bez zapisu do oryginalnych plików. `model.sdb` jest otwierany w trybie `readOnly`.
- Serwer nasłuchuje wyłącznie na `127.0.0.1`. Nie wysyła modelu ani PDF-ów do usług konwersji. Nie potrzebuje tokenu APS ani uruchomionego Revita.
- Silnik 3D **Autodesk Viewer 7.130.0** jest pobierany z oficjalnego CDN Autodesk, zgodnie z nagłówkiem licencji SDK. Pierwsze otwarcie 3D wymaga internetu; ta wersja nie jest gwarantowanym rozwiązaniem całkowicie offline. Analityka SDK jest wyłączona opcjami inicjalizacji.
- PDF.js **6.4.299** jest serwowany z lokalnego `node_modules`. PDF-y i baza działają bez dostępu do CDN Autodesk po instalacji zależności.
- Lista widoków powstaje z rzeczywistych plików SVF/PDF. Nadrzędny `bubble.json` ostatniego eksportu zawiera część statusów `inprogress`, mimo obecności gotowych zasobów; te statusy nie blokują ich przeglądania.
- Otwieranie natywnego `.rvt`, edycja modelu, zapisywanie zmian parametrów i federacja wielu eksportów nie są częścią tej wersji.
- Interfejs jest przeznaczony przede wszystkim do pracy na komputerze. W bardzo wąskim panelu aplikacji warto otworzyć adres w normalnej przeglądarce.
- Wersja Pages używa wyboru folderu i odczytu plików w przeglądarce. Poniższe API serwera Node.js i wklejanie ścieżek dotyczą tylko trybu lokalnego.

## Struktura i testy

```text
Analyzer/
  Start-Analyzer.cmd     launcher Windows
  server.mjs            serwer HTTP, wybór folderu, API i zasoby
  lib/exports.mjs       wykrywanie eksportów i widoków
  lib/properties.mjs    indeks właściwości i odczyt SQLite
  public/               HTML, CSS, JavaScript, viewer 3D i PDF
  tests/                testy integracyjne na rzeczywistym eksporcie
  docs/                 zapisane podglądy i wyniki weryfikacji
```

```powershell
npm run check
npm test
```

Testy korzystają domyślnie z powyższego eksportu Snowdon. Weryfikują rozpoznawanie katalogów, zgodność GZIP z SQLite (w tym ostatni rekord), dziedziczenie parametrów, filtrowanie/paginację, podawanie SVF i zakresów PDF, ochronę ścieżek i żądań, ograniczenie tabel oraz niezmienność SHA-256 źródłowego `model.sdb`.

Źródła integracji: [lokalne ładowanie modeli w Autodesk Viewer](https://aps.autodesk.com/blog/dwf-local-support-aps-viewer), [przykłady renderowania PDF.js](https://mozilla.github.io/pdf.js/examples/). PDF.js jest dostępny na licencji Apache-2.0; licencja znajduje się w `node_modules/pdfjs-dist/LICENSE`.
