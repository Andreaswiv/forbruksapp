# Bygger en ferdig programmappe for Windows: build\PengeneMine\{python, app}
# Python følger med (den «innebygde» utgaven fra python.org), så PC-en trenger ingenting fra før.
# Kjøres på GitHub (se .github/workflows/windows.yml), men fungerer også på en vanlig Windows-PC.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-Location (Split-Path $PSScriptRoot -Parent)

$PyVersion = "3.12.10"
$Out = "build\PengeneMine"
if (Test-Path build) { Remove-Item -Recurse -Force build }
New-Item -ItemType Directory "$Out\python", "$Out\app" | Out-Null

Write-Host "Laster ned Python $PyVersion ..."
Invoke-WebRequest "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip" -OutFile build\python.zip
Expand-Archive build\python.zip "$Out\python"

# Slå på site-packages og gjør app-mappen importerbar
$pth = Get-ChildItem "$Out\python\python3*._pth" | Select-Object -First 1
$zip = $pth.BaseName + ".zip"
@($zip, ".", "Lib\site-packages", "..\app", "import site") | Set-Content $pth.FullName -Encoding ascii

Write-Host "Installerer pakker ..."
Invoke-WebRequest "https://bootstrap.pypa.io/get-pip.py" -OutFile build\get-pip.py
& "$Out\python\python.exe" build\get-pip.py --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "get-pip feilet" }
& "$Out\python\python.exe" -m pip install --no-warn-script-location --disable-pip-version-check -r windows\requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install feilet" }

Write-Host "Kopierer appen ..."
foreach ($item in "app.py", "launcher.py", "mcp_server.py", "forbruk", "data", ".streamlit", "eksempeldata") {
    Copy-Item -Recurse $item "$Out\app\"
}
New-Item -ItemType Directory "$Out\app\windows" | Out-Null
Copy-Item windows\ikon.ico, windows\ikon.png "$Out\app\windows\"
Get-ChildItem "$Out\app" -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force

# Ferdigkompilert Python gjør første oppstart raskere
& "$Out\python\python.exe" -m compileall -q "$Out\app" | Out-Null
Write-Host "Ferdig: $Out"
