$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RootDir

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 "$RootDir/launch.py" @Args
    exit $LASTEXITCODE
}

if (Get-Command python -ErrorAction SilentlyContinue) {
    & python "$RootDir/launch.py" @Args
    exit $LASTEXITCODE
}

Write-Error "Python 3 is required."
