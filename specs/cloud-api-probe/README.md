# Cloud API probe / Sprawdzian API chmury

English first, Polski ponizej.

## English

**Question the probe answers:** can an APS app that *you* register (no admin involved) read your ACC hubs, projects, and the `projectGuid` / `modelGuid` of cloud models? Everything is read-only metadata. See `HANDOVER.md` (cloud-catalog) for why.

### 1. Register the app (about 5 minutes, free)
> The portal wording below is from memory and not checked against the live site. Adjust if the labels differ.
1. Sign in at <https://aps.autodesk.com> with your Autodesk ID, open **Applications** and choose **Create application**.
2. Name: anything (e.g. `RevitExtractor probe`). Type: **Desktop, Mobile, Single-Page App** (no client secret).
3. APIs: tick **Data Management API** (add **Authentication API** if it is listed).
4. Callback URL: exactly `http://localhost:8765/callback`.
5. Copy the **Client ID** (not any secret). Do not commit it or paste it into chat or git; it goes in the command below only.

### 2. Run it (Windows PowerShell 5.1, repo root)
```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\specs\cloud-api-probe\aps_probe.ps1 -ClientId '<your client id>'
```
A browser opens; sign in and approve read access.

### 3. What to send back
The console output only. It holds counts, HTTP codes and field *names*, never hub/project/model names. Do not copy anything else.

| Result | Meaning |
| --- | --- |
| Hubs > 0, projects > 0, `has projectGuid: True`, `has modelGuid: True` | Works without an admin. Build the full cloud-catalog. |
| `0 hubs`, or `HTTP 403` on projects | The account needs the app provisioned (admin step). We park the API and ship the open-model fallback. |
| GUID fields `False` | The model lacks them; send the printed field names, we adapt the match key. |

The script writes nothing to disk and keeps the token in memory.

## Polski

**Pytanie:** czy aplikacja APS zarejestrowana *przez Ciebie* (bez administratora) widzi Twoje huby ACC, projekty oraz `projectGuid` / `modelGuid` modeli w chmurze? Skrypt tylko czyta metadane.

### 1. Rejestracja aplikacji (ok. 5 minut, za darmo)
> Nazwy w portalu podaje z pamieci i nie sprawdzono ich na zywo. Dopasuj, jesli sie roznia.
1. Zaloguj sie na <https://aps.autodesk.com> kontem Autodesk, otworz **Applications** i wybierz **Create application**.
2. Nazwa dowolna (np. `RevitExtractor probe`). Typ: **Desktop, Mobile, Single-Page App** (bez client secret).
3. API: zaznacz **Data Management API** (oraz **Authentication API**, jesli jest na liscie).
4. Callback URL dokladnie: `http://localhost:8765/callback`.
5. Skopiuj **Client ID** (nie sekret). Nie commituj go i nie wklejaj do czatu ani do git; wpisujesz go tylko w polecenie ponizej.

### 2. Uruchomienie (Windows PowerShell 5.1, katalog glowny repo)
```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\specs\cloud-api-probe\aps_probe.ps1 -ClientId '<twoj client id>'
```
Otworzy sie przegladarka; zaloguj sie i zatwierdz dostep do odczytu.

### 3. Co odeslac
Tylko wynik z konsoli: liczby, kody HTTP i *nazwy pol*, bez nazw hubow, projektow i modeli.

| Wynik | Znaczenie |
| --- | --- |
| Huby > 0, projekty > 0, `has projectGuid: True`, `has modelGuid: True` | Dziala bez administratora. Budujemy pelny cloud-catalog. |
| `0 hubs` albo `HTTP 403` przy projektach | Konto wymaga zatwierdzenia aplikacji (krok administratora). Odkladamy API i dajemy rozwiazanie zapasowe. |
| Pola GUID `False` | Model ich nie ma; odeslij wypisane nazwy pol, dostosujemy klucz dopasowania. |

Skrypt nic nie zapisuje na dysku, token trzyma tylko w pamieci.
