#requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Offline,
    [switch]$PassThru
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$repo = Split-Path -Parent $PSScriptRoot
$plugin = Join-Path $repo 'plugins/windows-desktop'
$cache = Join-Path $repo '.build/downloads'

function Get-VerifiedArchive {
    param([string]$Url, [string]$Sha256)

    $name = [IO.Path]::GetFileName(([uri]$Url).AbsolutePath)
    $path = Join-Path $cache $name
    if ((Test-Path -LiteralPath $path -PathType Leaf) -and
        (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -eq $Sha256) {
        return $path
    }
    if ($Offline) {
        throw "Offline build needs a valid $name in $cache. Run prepare-runtime.ps1 with network access."
    }

    [void][IO.Directory]::CreateDirectory($cache)
    $download = "$path.$([guid]::NewGuid().ToString('N')).download"
    try {
        Write-Host "Downloading $name"
        $savedProgress = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'
        try {
            Invoke-WebRequest -Uri $Url -OutFile $download -UseBasicParsing -TimeoutSec 180
        } finally {
            $ProgressPreference = $savedProgress
        }
        $actual = (Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash
        if ($actual -ne $Sha256) {
            throw "SHA-256 mismatch for ${name}: expected $Sha256, got $actual"
        }
        Move-Item -LiteralPath $download -Destination $path -Force
        return $path
    } finally {
        if (Test-Path -LiteralPath $download -PathType Leaf) {
            Remove-Item -LiteralPath $download -Force
        }
    }
}

function Install-ArchiveEntry {
    param(
        [IO.Compression.ZipArchiveEntry]$Entry,
        [string]$RelativePath
    )

    $path = Join-Path $plugin $RelativePath
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path))

    if (Test-Path -LiteralPath $path -PathType Leaf) {
        # Leave a matching file in place, including an executable in use.
        $source = $Entry.Open()
        try {
            $matches = (Get-FileHash -InputStream $source -Algorithm SHA256).Hash -eq
                (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
        } finally {
            $source.Dispose()
        }
        if ($matches) {
            return $RelativePath
        }
    }

    $staging = "$path.$([guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $staging)
        Move-Item -LiteralPath $staging -Destination $path -Force
    } finally {
        if (Test-Path -LiteralPath $staging -PathType Leaf) {
            Remove-Item -LiteralPath $staging -Force
        }
    }
    return $RelativePath
}

# Pins are taken from the upstream files linked in THIRD_PARTY.md.
$pythonArchive = Get-VerifiedArchive `
    'https://www.python.org/ftp/python/3.13.17/python-3.13.17-embed-amd64.zip' `
    '9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38'
$cuaArchive = Get-VerifiedArchive `
    'https://github.com/trycua/cua/releases/download/cua-driver-rs-v0.53.0/cua-driver-rs-0.53.0-windows-x86_64.zip' `
    '9dcf88dfdd9cd75613130d23ad25a9656ed1ecacc5e4bc7f24b763d788316243'

$files = [Collections.Generic.List[string]]::new()
$zip = [IO.Compression.ZipFile]::OpenRead($pythonArchive)
try {
    foreach ($entry in $zip.Entries) {
        if ($entry.FullName -notmatch '^[a-zA-Z0-9_][a-zA-Z0-9_.-]*$') {
            throw "Unexpected CPython archive member: $($entry.FullName)"
        }
        if ($entry.FullName -ne 'python313._pth') {
            $files.Add((Install-ArchiveEntry $entry "runtime/$($entry.FullName)"))
        }
    }
} finally {
    $zip.Dispose()
}

$pathFile = 'runtime/python313._pth'
$pathConfig = Join-Path $plugin $pathFile
$pathContent = "python313.zip`r`n.`r`n../app`r`n"
if (!(Test-Path -LiteralPath $pathConfig -PathType Leaf) -or
    [IO.File]::ReadAllText($pathConfig) -cne $pathContent) {
    [IO.File]::WriteAllText($pathConfig, $pathContent, [Text.Encoding]::ASCII)
}
$files.Add($pathFile)

$zip = [IO.Compression.ZipFile]::OpenRead($cuaArchive)
try {
    foreach ($name in @('cua-driver.exe', 'cua-driver-uia.exe', 'LICENSE', 'THIRD_PARTY_NOTICES.md')) {
        $entry = $zip.GetEntry("cua-driver-rs-0.53.0-windows-x86_64/$name")
        if ($null -eq $entry) {
            throw "Missing Cua archive member: $name"
        }
        $files.Add((Install-ArchiveEntry $entry "app/vendor/cua/$name"))
    }
} finally {
    $zip.Dispose()
}

if ($PassThru) {
    $files
} else {
    Write-Host "Prepared CPython 3.13.17 and Cua Driver 0.53.0 for Windows x64 in $plugin"
}
