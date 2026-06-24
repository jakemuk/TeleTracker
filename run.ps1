<#
.SYNOPSIS
    Runs TeleGatherer.py using the project's virtual environment (Python 3.9).

.DESCRIPTION
    Ensures the script always runs with the .venv interpreter (which has the
    project's dependencies installed) instead of any global Python install.
    The MTProto download feature depends on kurigram - a maintained drop-in fork
    of the abandoned Pyrogram - which is installed in .venv; running under a
    global interpreter that lacks it will fail. Any arguments passed to this
    script are forwarded to TeleGatherer.py unchanged.

.EXAMPLE
    .\run.ps1 --info -t <BOT_TOKEN>

.EXAMPLE
    .\run.ps1 -t <BOT_TOKEN> -c <CHAT_ID>
#>

$ErrorActionPreference = "Stop"

# Resolve paths relative to this script so it works from any working directory.
$scriptRoot = $PSScriptRoot
$venvPython = Join-Path $scriptRoot ".venv\Scripts\python.exe"
$target     = Join-Path $scriptRoot "TeleGatherer.py"

if (-not (Test-Path $venvPython)) {
    Write-Error "Virtual environment not found at '$venvPython'. Create it with: python -m venv .venv  then: .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}

if (-not (Test-Path $target)) {
    Write-Error "TeleGatherer.py not found at '$target'."
    exit 1
}

# Forward all arguments through to the script.
& $venvPython $target @args
exit $LASTEXITCODE
