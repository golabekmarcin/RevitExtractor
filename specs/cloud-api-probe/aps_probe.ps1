<#
.SYNOPSIS
  Read-only probe: can a self-registered APS app read my ACC hubs and the GUIDs of cloud models?
  Sprawdzian tylko do odczytu: czy wlasna aplikacja APS widzi moje huby ACC i GUID-y modeli w chmurze?

.DESCRIPTION
  Signs in with 3-legged OAuth + PKCE (no client secret), then only reads metadata:
    1. hubs (count, kind)           2. projects per hub (count or HTTP status)
    3. one cloud-workshared model's version extension data: which FIELD NAMES exist.
  It prints counts, HTTP status codes and field names. It never prints hub, project, folder
  or model names or ids, and it writes nothing to disk. The token stays in memory.
  Windows PowerShell 5.1. ASCII only on purpose.

.PARAMETER ClientId
  Client ID of your APS app (type: Desktop, Mobile, Single-Page App).
.PARAMETER Port
  Callback port. The app's callback URL must be exactly http://localhost:<Port>/callback
.PARAMETER MaxCalls
  Upper bound of folder calls while looking for a cloud-workshared model (default 60).
#>
param(
    [Parameter(Mandatory = $true)][string]$ClientId,
    [int]$Port = 8765,
    [int]$MaxCalls = 60
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$base = 'https://developer.api.autodesk.com'
$redirect = "http://localhost:$Port/callback"

function ConvertTo-B64Url([byte[]]$bytes) {
    [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

# --- PKCE ---
$rng = New-Object Security.Cryptography.RNGCryptoServiceProvider
$raw = New-Object byte[] 48
$rng.GetBytes($raw)
$verifier = ConvertTo-B64Url $raw
$sha = [Security.Cryptography.SHA256]::Create()
$challenge = ConvertTo-B64Url ($sha.ComputeHash([Text.Encoding]::ASCII.GetBytes($verifier)))

$authUrl = "$base/authentication/v2/authorize?response_type=code" +
    "&client_id=$([Uri]::EscapeDataString($ClientId))" +
    "&redirect_uri=$([Uri]::EscapeDataString($redirect))" +
    "&scope=$([Uri]::EscapeDataString('data:read'))" +
    "&code_challenge=$challenge&code_challenge_method=S256"

# --- Browser sign-in, callback on localhost ---
$listener = New-Object Net.HttpListener
$listener.Prefixes.Add("http://localhost:$Port/")
$listener.Start()
try {
    Write-Host 'Opening the browser for sign-in. / Otwieram przegladarke do logowania.'
    Start-Process $authUrl
    $task = $listener.GetContextAsync()
    if (-not $task.Wait(180000)) { throw 'Sign-in timed out (3 min). / Przekroczono czas logowania.' }
    $ctx = $task.Result
    $code = $ctx.Request.QueryString['code']
    $err = $ctx.Request.QueryString['error']
    $html = [Text.Encoding]::UTF8.GetBytes('<html><body>You can close this tab. / Mozesz zamknac te karte.</body></html>')
    $ctx.Response.OutputStream.Write($html, 0, $html.Length)
    $ctx.Response.Close()
} finally {
    $listener.Stop()
}
if ($err) { throw "Sign-in refused: $err" }
if (-not $code) { throw 'No authorization code received.' }

$body = @{
    grant_type = 'authorization_code'; client_id = $ClientId; code = $code
    code_verifier = $verifier; redirect_uri = $redirect
}
$tok = Invoke-RestMethod -Method Post -Uri "$base/authentication/v2/token" -Body $body `
    -ContentType 'application/x-www-form-urlencoded'
$headers = @{ Authorization = "Bearer $($tok.access_token)" }
Write-Host 'Signed in. Token held in memory only. / Zalogowano.'

function Get-Api([string]$path) {
    # returns @{ Ok; Status; Json }
    try {
        $r = Invoke-RestMethod -Method Get -Uri "$base$path" -Headers $headers
        return @{ Ok = $true; Status = 200; Json = $r }
    } catch {
        $status = 0
        if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
        return @{ Ok = $false; Status = $status; Json = $null }
    }
}

# --- 1. hubs ---
Write-Host ''
Write-Host '== 1. Hubs =='
$h = Get-Api '/project/v1/hubs'
if (-not $h.Ok) { Write-Host "RESULT: hubs call failed, HTTP $($h.Status)"; return }
$hubs = @($h.Json.data)
Write-Host "Hubs visible: $($hubs.Count)"
$kinds = $hubs | Group-Object { $_.attributes.extension.type } | ForEach-Object { "$($_.Name) x$($_.Count)" }
foreach ($k in $kinds) { Write-Host "  kind: $k" }
if ($hubs.Count -eq 0) {
    Write-Host 'RESULT: 0 hubs. Likely the app is not provisioned in the account (admin step).'
    return
}

# --- 2. projects ---
Write-Host ''
Write-Host '== 2. Projects per hub =='
$i = 0
$projectRefs = @()
foreach ($hub in $hubs) {
    $i++
    $p = Get-Api "/project/v1/hubs/$($hub.id)/projects"
    if ($p.Ok) {
        $list = @($p.Json.data)
        Write-Host "  hub #${i}: projects visible = $($list.Count)"
        foreach ($proj in $list) { $projectRefs += @{ Hub = $hub.id; Project = $proj.id } }
    } else {
        Write-Host "  hub #${i}: projects call failed, HTTP $($p.Status)"
    }
}
if ($projectRefs.Count -eq 0) {
    Write-Host 'RESULT: no project listing worked. HTTP 403 here = app not provisioned (admin step).'
    return
}

# --- 3. one cloud-workshared model: field names of version extension data ---
Write-Host ''
Write-Host '== 3. Cloud-workshared model fields (names only) =='
$calls = 0
$found = $false
foreach ($ref in $projectRefs) {
    if ($found -or $calls -ge $MaxCalls) { break }
    $top = Get-Api "/project/v1/hubs/$($ref.Hub)/projects/$($ref.Project)/topFolders"
    $calls++
    if (-not $top.Ok) { continue }
    $queue = New-Object Collections.Queue
    foreach ($f in @($top.Json.data)) { $queue.Enqueue(@{ Id = $f.id; Depth = 0 }) }
    while ($queue.Count -gt 0 -and -not $found -and $calls -lt $MaxCalls) {
        $cur = $queue.Dequeue()
        $c = Get-Api "/data/v1/projects/$($ref.Project)/folders/$($cur.Id)/contents"
        $calls++
        if (-not $c.Ok) { continue }
        foreach ($v in @($c.Json.included)) {
            if ($v.type -eq 'versions' -and "$($v.attributes.extension.type)" -like '*C4RModel*') {
                $data = $v.attributes.extension.data
                $names = @()
                if ($data) { $names = @($data.PSObject.Properties.Name) }
                Write-Host "  extension.type : $($v.attributes.extension.type)"
                Write-Host "  has projectGuid: $($names -contains 'projectGuid')"
                Write-Host "  has modelGuid  : $($names -contains 'modelGuid')"
                Write-Host "  data field names: $($names -join ', ')"
                Write-Host "  has lastModifiedTime: $([bool]$v.attributes.lastModifiedTime)"
                $found = $true
                break
            }
        }
        if (-not $found -and $cur.Depth -lt 4) {
            foreach ($d in @($c.Json.data)) {
                if ($d.type -eq 'folders') { $queue.Enqueue(@{ Id = $d.id; Depth = $cur.Depth + 1 }) }
            }
        }
    }
}
Write-Host ''
if ($found) {
    Write-Host "RESULT: reached model metadata after $calls calls. Send back the 4 lines above (no names)."
} else {
    Write-Host "RESULT: no cloud-workshared model found within $calls calls (raise -MaxCalls or pick another hub)."
}
