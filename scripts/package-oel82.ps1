param(
    [string]$ImageName = "icu-quality-dashboard-oel82-builder",
    [string]$OutDir = "release"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$OutPath = Join-Path $Root $OutDir
$ContainerName = "icu-quality-dashboard-artifact-$([guid]::NewGuid().ToString('N'))"

Set-Location $Root

if (!(Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is not installed or not in PATH."
}

New-Item -ItemType Directory -Force -Path $OutPath | Out-Null

Write-Host "Building OEL 8.2 binary package image..."
docker build --target artifact -t $ImageName -f Dockerfile .

Write-Host "Copying artifacts..."
docker create --name $ContainerName $ImageName | Out-Null
try {
    docker cp "${ContainerName}:/artifact/icu-quality-dashboard-oel8.2-x86_64.tar.gz" $OutPath
    docker cp "${ContainerName}:/artifact/icu-quality-dashboard" (Join-Path $OutPath "icu-quality-dashboard")
}
finally {
    docker rm $ContainerName | Out-Null
}

Write-Host ""
Write-Host "Done."
Write-Host "Archive: $(Join-Path $OutPath 'icu-quality-dashboard-oel8.2-x86_64.tar.gz')"
Write-Host "Expanded package: $(Join-Path $OutPath 'icu-quality-dashboard')"
