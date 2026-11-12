@echo off
rem Starts the local Analyzer. On the first run it installs the npm packages (needs Internet).
rem Messages are English first, then Polish (ASCII only, so any console code page shows them).
cd /d "%~dp0"

rem Machine-wide Node.js installs are normally on PATH; add the default folder if this console missed it.
where node >nul 2>nul
if errorlevel 1 if exist "%ProgramFiles%\nodejs\node.exe" set "PATH=%PATH%;%ProgramFiles%\nodejs"

where node >nul 2>nul
if errorlevel 1 (
  echo Node.js 24 or later is required, and it was not found. Install it yourself or from the Company Portal,
  echo then open a new console. Restart Revit too, so it sees the new PATH.
  echo Wymagany jest Node.js 24 lub nowszy, a nie zostal znaleziony. Zainstaluj go samodzielnie lub z Company Portal,
  echo potem otworz nowa konsole. Uruchom ponownie rowniez Revit, aby zobaczyl nowy PATH.
  pause
  exit /b 1
)
node -e "if (Number(process.versions.node.split('.')[0]) < 24) process.exit(1)"
if errorlevel 1 (
  echo Node.js 24 or later is required.
  echo Wymagany jest Node.js 24 lub nowszy.
  pause
  exit /b 1
)

rem Trust the Windows certificate store (the same one browsers use), so a company proxy that
rem re-signs HTTPS traffic works without extra setup. Certificate checking stays on.
if not defined NODE_USE_SYSTEM_CA set "NODE_USE_SYSTEM_CA=1"

if not exist "node_modules\pdfjs-dist\build\pdf.mjs" (
  echo Installing the Analyzer packages once ^(needs Internet^)...
  echo Instalowanie pakietow Analyzera ^(jednorazowo, wymaga Internetu^)...
  call npm ci --omit=optional --ignore-scripts
  if errorlevel 1 (
    echo.
    echo npm ci failed. If the message mentions a certificate, ask IT for the company root certificate
    echo and run: npm config set cafile "C:\path\to\root.pem"
    echo npm ci nie powiodlo sie. Jesli komunikat dotyczy certyfikatu, popros dzial IT o firmowy certyfikat
    echo glowny i uruchom: npm config set cafile "C:\sciezka\root.pem"
    pause
    exit /b 1
  )
)
node server.mjs --open
if errorlevel 1 pause
