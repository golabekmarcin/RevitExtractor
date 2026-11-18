# Eksport: eksport jednym przyciskiem (Revit 2022 i nowsze)

[English](README.md) · Polski

Przycisk pyRevit, który eksportuje modele Revita natywnym Autodesk Revit Extractorem, **bez otwartego modelu** w Revicie. Wybierasz modele z folderów, opcjonalnie widoki jednego modelu, i uruchamiasz eksport. Polecenie wraca od razu, a okno statusu pokazuje postęp i wynik.

**Stan: zbudowany i przetestowany jednostkowo poza Revitem. Jeszcze nie uruchomiony w Revicie.** Zob. Weryfikacja.

## Instalacja

Sklonuj repozytorium i dodaj `<klon>\pyRevit` jako własny folder rozszerzeń w ustawieniach pyRevit, potem **Reload pyRevit**. Przycisk nazywa się `Eksport` (zakładka RevitExtractor, panel Setup). Przycisk potrzebuje `lib\` tego rozszerzenia, więc nie da się go skopiować osobno. Stare przyciski `ExportSetup` i `ExportSetupLegacy` nie są zmienione i nadal działają.

Eksport wymaga tylko Revita, pyRevit i Extractora dostarczanego z Revitem. **Node.js jest opcjonalny**: używa go wyłącznie „Otwórz w Analyzerze” z lokalnym Analyzerem.

**Znane ograniczenie:** Revit 2025 i nowsze działają na .NET 8, gdzie niektóre typy .NET wymagają dodatkowego odwołania do zestawu (`libx_dotnet.py` je dodaje). Nieprzetestowane w Revicie 2025+, dopóki właściciel tego nie potwierdzi; w Revicie 2022-2024 nic się nie zmienia.

Do lokalnego Analyzera:
1. Zainstaluj Node.js 24 lub nowszy samodzielnie albo z Company Portal. Potem uruchom Revit ponownie, aby zobaczył nowy `PATH`.
2. Jednorazowo uruchom dwuklikiem `Analyzer\Start-Analyzer.cmd`. Zainstaluje pakiety npm (wymaga Internetu) i zaufa magazynowi certyfikatów Windows, więc firmowy proxy podpisujący HTTPS działa bez dodatkowej konfiguracji; sprawdzanie certyfikatów pozostaje włączone. Jeśli `npm ci` nadal zgłasza błąd certyfikatu, poproś dział IT o firmowy certyfikat główny i uruchom `npm config set cafile "<ścieżka do root.pem>"`. Nie wyłączaj `strict-ssl`.

Bez Node.js i pakietów przycisk otwiera folder wyników i stronę internetową, po komunikacie, który można wyłączyć opcją „Nie pokazuj ponownie”.

## Użycie

1. Przy **zamkniętych modelach** kliknij **Eksport**. Przy otwartym modelu przycisk jest wyszarzony; jeśli mimo to zostanie kliknięty, pojawi się komunikat i nic nie jest czytane.
2. **Dodaj folder…** (jeden lub więcej folderów głównych, przeszukiwanych rekurencyjnie; dyski lokalne lub serwer plików). Lista wypełnia się w trakcie skanowania. Pomijane są pliki kopii zapasowych (`*.0001.rvt`), foldery `Backup` i lokalne kopie centrali. Modele zapisane w nowszym Revicie są wyszarzone; starsze można eksportować z ostrzeżeniem (eksport aktualizuje kopię). Pliki, których wersji nie da się odczytać, są wyszarzone z podpowiedzią.
3. Zaznacz modele. Pole wyszukiwania przyjmuje słowa w dowolnej kolejności lub regex; ▾ w nagłówkach Katalog i Wersja Revita filtruje. **Zaznacz wszystkie widoczne** dotyczy tylko widocznych, dostępnych wierszy.
4. Wybierz **folder wyników** (domyślnie `%USERPROFILE%\RevitExtractor`, poza OneDrive; gdy wybrany folder jest synchronizowany przez OneDrive, pojawia się ostrzeżenie; każdy eksport dostaje własny folder `export-<data>-<id>`) i zakres: **Domyślny zakres Extractora** albo **Wspólny index.json** (odrzucany przy kilku modelach, jeśli zawiera identyfikatory widoków).
5. **Eksportuj** dodaje do kolejki jeden eksport na każdy zaznaczony model. Okno **pozostaje otwarte**: zaznaczenia są czyszczone, a krótki komunikat podaje liczbę dodanych eksportów, więc możesz zaznaczyć kolejne modele i dodać je bez ponownego otwierania przycisku (ten sam model można dodać ponownie). Jeśli przekazanie się nie uda, czerwona linia błędu podaje przyczynę, a zaznaczenia zostają do ponowienia. Zamknij okno, gdy skończysz; zamknięcie nie dodaje już niczego do kolejki. **Wybierz widoki…** (zaznaczony dokładnie jeden model) czyta ten model w tle (odłączony, tylko do odczytu, worksety zamknięte, nigdy niezapisywany) i otwiera okno widoków: zaznacz widoki 2D, arkusze i widoki 3D, przełącz bazę SQLite i opcje, **Zapisz index.json…**, **Wstecz** lub **Eksportuj**.
6. **Okno statusu** pokazuje eksporty po kolei: stan, postęp i czas. Otwórz folder wyników, Otwórz w Analyzerze i Anuluj eksport działają na podświetlonym wierszu; prawy przycisk myszy na wierszu zaznacza go i oferuje Pokaż model w Eksploratorze plików oraz Pokaż folder eksportu w Eksploratorze plików. Wyczyść zakończone usuwa z listy zakończone, nieudane i anulowane eksporty; trwające i oczekujące zostają, a żadne pliki nie są usuwane. Gdy okno modeli jest otwarte, okno statusu nadal się odświeża, ale nie przyjmuje kliknięć (okno modeli jest modalne): zamknij okno modeli, aby użyć Anuluj eksport, Wyczyść zakończone lub menu wiersza. Zamknięcie okna statusu krzyżykiem minimalizuje je, dopóki eksporty czekają lub trwają. Eksporty działają dalej po zamknięciu okna i Revita; niezaczęte są odrzucane, gdy Revit się zamknie. Po ponownym uruchomieniu Revita **Eksport** pokazuje eksport, który nadal trwa z poprzedniej sesji (znaleziony w folderze wyników; tylko obserwowany, więc nie można go tam anulować, a nowe eksporty czekają na niego).

### Modele z chmury (ACC)

Wybierz **Chmura (ACC)** w „Modele z”, aby zobaczyć modele z chmury, które Revit już przechowuje na tym komputerze. Nic nie jest pobierane, a do zbudowania listy nie otwiera się żaden model.
1. Nazwy pochodzą z **dzienników** Revita (`%LOCALAPPDATA%\Autodesk\Revit\Autodesk Revit <rok>\Journals`) i są łączone z plikami w `...\CollaborationCache` po identyfikatorach projektu i modelu. Dlatego widać tylko modele **otwarte na tym komputerze** (bezpośrednio lub jako linki). Plik z pamięci podręcznej bez znanej nazwy nigdy nie jest pokazywany pod identyfikatorem; karta projektu je zlicza („Modele w pamięci podręcznej bez nazwy: N. Otwórz je raz w Revicie, aby je dodać.”). Jeśli żaden dziennik nie zawiera nazwy modelu z chmury, komunikat o tym informuje; użyj przycisku **Zapamiętaj model z chmury** (obok tego przycisku) przy otwartym modelu.
2. **Zaznacz projekty** do wyświetlenia; na początku żaden nie jest zaznaczony, a wybór jest zapisywany dla użytkownika. Wiersze innych projektów są wyszarzone („Poza wybranymi projektami.”). Dwa modele o tej samej nazwie w jednym projekcie: można zaznaczyć tylko nowszą kopię.
3. Każdy wiersz pokazuje **datę kopii**: czas kopii w pamięci podręcznej, czyli tak aktualnej, jak ostatnie otwarcie tego modelu na tym komputerze (nic nie jest twierdzone o wersji w chmurze). Kopie starsze niż 7 dni mają uwagę; nadal można je eksportować.
4. **Eksportuj** (i **Wybierz widoki…**) najpierw jednorazowo czyta w tle linki Revit modelu z kopii w pamięci podręcznej (wynik jest zapamiętywany, dopóki kopia się nie zmieni). Każdy eksport umieszcza potem pliki w swoim folderze `model` pod ich prawdziwymi nazwami: domyślnie każdy plik z pamięci podręcznej jest **dowiązaniem twardym** (druga nazwa tego samego pliku: bez kopiowania, bez dodatkowego miejsca na dysku, sekundy zamiast minut; pamięć podręczna nigdy nie jest zapisywana, a ostrzeżenie pojawia się, gdy plik zmienił się w trakcie eksportu). Plik, którego nie da się dowiązać (inny dysk lub atrybut tylko do odczytu), jest kopiowany, z postępem „Kopiowanie z pamięci podręcznej” w oknie statusu. Ustaw `"cloud_hardlinks": false` w `%APPDATA%\RevitExtractor\preferences.json`, aby zawsze kopiować. Extractor otwiera plik z folderu `model`; nazwy te i foldery `_backup` Revita są usuwane po eksporcie. Link, którego nie ma w pamięci podręcznej, jest eksportowany bez niego, z uwagą.
5. Do pamięci podręcznej **nic nie jest zapisywane**. Po zakończeniu Extractora kopie są usuwane; zostaje `model\stage.json` (nazwy, rozmiary i daty kopii). Najpierw sprawdź wolne miejsce na dysku: kopie i własna kopia tymczasowa Extractora muszą się zmieścić.

Nieprzetestowane: wybór na poziomie folderów (dzienniki nie zawierają folderów), formaty dzienników po Revicie 2022. Zob. Weryfikacja.

Eksporty idą **po jednym**: w przetestowanej wersji Extractora drugi Extractor kończy się błędem na stałym potoku. Jeśli na komputerze działa już inny Extractor, kolejka czeka.

Ustawienia (foldery, folder wyników) są w pliku konfiguracji pyRevit, który wtedy zawiera ścieżki: nie udostępniaj go. Pamięć podręczna listy modeli to `%APPDATA%\RevitExtractor\catalog-cache.json`, także ze ścieżkami modeli. Pamięć chmury to `%APPDATA%\RevitExtractor\cloud-catalog.json`; zawiera nazwy projektów i plików klienta: nigdy jej nie udostępniaj ani nie commituj.

Cały tekst jest po angielsku i po polsku, według ustawienia języka pyRevit (domyślnie angielski).

## Weryfikacja

2026-11-11, główny komputer (Revit 2023, bez pyRevit, CPython 3):
- wszystkie testy jednostkowe: 554 OK. Oba okna działają na atrapach WPF; `validate_xaml.ps1` ładuje oba pliki XAML w prawdziwym WPF;
- `run_extractor_integration.ps1`: prawdziwy Extractor uruchomiony z tej samej specyfikacji co kolejka: PASS (także `-Cancel`); `-Parallel 2` FAIL (stały potok);
- `v1_test_kit.ps1 -Setup` i `-Check` uruchomiono na takim eksporcie.

2026-11-16, ten sam komputer: wszystkie testy jednostkowe 924 OK (w tym karta Chmura na atrapach WPF i kolejka z kopiowaniem); `validate_xaml.ps1` 6 PASS; `run_extractor_integration.ps1 -Cloud` PASS (fałszywe drzewo pamięci podręcznej w `%TEMP%`, skopiowany model wyeksportowany prawdziwym Extractorem, pliki w pamięci podręcznej bez zmian, został tylko `stage.json`); `v1_test_kit.ps1 -Check` wypisuje wyłącznie liczby dotyczące chmury.

**Niezweryfikowane dla karty Chmura:** wszystko wewnątrz Revita: prawdziwe wiersze dzienników (sprawdzone ręcznie wcześniej, tylko w Revicie 2022), otwarcie w tle pliku z pamięci podręcznej, lista linków prawdziwego modelu z chmury, czas kopiowania i reakcja Revita w trakcie kopiowania, geometria linków w widoku federacyjnym 3D oraz karta Chmura w prawdziwym oknie. Lista kontrolna to część H pliku `specs/v1-revit-test.md`.

**Niezweryfikowane:** IronPython 2.7 (testy działają na CPython 3), pyRevit i wszystko wewnątrz Revita: wyszarzanie przycisku, okna wyboru, `BasicFileInfo.Extract` z timera skanu, prawdziwe otwarcie w tle, okno statusu i przekazanie między silnikami skryptów, zamknięcie Revita w trakcie eksportu, wiersze Revit 2025 i 2026 oraz polski tekst w prawdziwych oknach. Lista kontrolna do tego wszystkiego to `specs/v1-revit-test.md`; wyniki zostaną zapisane tutaj.
