$ErrorActionPreference = "Stop"

$WebappRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $WebappRoot "..\venv\Scripts\python.exe"

function Invoke-ProjectCheck {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description falló con código $LASTEXITCODE."
    }
}

Push-Location $WebappRoot
try {
    Invoke-ProjectCheck { & $Python manage.py check } "El chequeo de Django"
    Invoke-ProjectCheck { & $Python manage.py test recommender.tests --noinput } "Las pruebas"
    Invoke-ProjectCheck { npm.cmd run build } "La compilación de Vite"
}
finally {
    Pop-Location
}
