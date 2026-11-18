#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$OutputDirectory,
    [switch]$Offline
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$repo = Split-Path -Parent $PSScriptRoot
if (!$OutputDirectory) {
    $OutputDirectory = Join-Path $repo 'dist'
}
$plugin = 'plugins/windows-desktop'
$manifest = Get-Content -LiteralPath (Join-Path $repo "$plugin/plugin.json") -Raw | ConvertFrom-Json
if ($manifest.version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][a-zA-Z0-9.-]+)?$') {
    throw "Invalid plugin version: $($manifest.version)"
}

$files = [Collections.Generic.List[string]]::new()
$files.AddRange([string[]]@(
    '.agents/plugins/marketplace.json'
    'README.md'
    'LICENSE'
    'THIRD_PARTY.md'
    "$plugin/plugin.json"
    "$plugin/mcp.json"
    "$plugin/.codex-plugin/plugin.json"
    "$plugin/app/server.py"
    "$plugin/app/worker.ps1"
    "$plugin/skills/windows-uia-background/SKILL.md"
))
$pluginRoot = Join-Path $repo $plugin
foreach ($subdir in @('app', 'skills', 'assets')) {
    $path = Join-Path $pluginRoot $subdir
    if (!(Test-Path -LiteralPath $path -PathType Container)) {
        continue
    }
    foreach ($item in (Get-ChildItem -LiteralPath $path -File -Recurse)) {
        $relative = $item.FullName.Substring($pluginRoot.Length + 1).Replace('\', '/')
        if ($relative -notmatch '(^|/)(__pycache__|vendor)/|\.(py[co]|tmp)$') {
            $files.Add("$plugin/$relative")
        }
    }
}

foreach ($dependency in (& (Join-Path $PSScriptRoot 'prepare-runtime.ps1') -Offline:$Offline -PassThru)) {
    $files.Add("$plugin/$dependency")
}

$output = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)
[void][IO.Directory]::CreateDirectory($output)
$name = "windows-desktop-mcp-$($manifest.version)-windows-x64.zip"
$target = Join-Path $output $name
$temporaryZip = "$target.$([guid]::NewGuid().ToString('N')).tmp"
try {
    # Use forward slashes and add files individually to preserve dot directories.
    $zip = [IO.Compression.ZipFile]::Open($temporaryZip, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($relative in ($files | Sort-Object -Unique)) {
            $path = Join-Path $repo $relative
            $entry = $zip.CreateEntry($relative, [IO.Compression.CompressionLevel]::Optimal)
            $entry.LastWriteTime = [DateTimeOffset]::new(2020, 1, 1, 0, 0, 0, [TimeSpan]::Zero)
            $inputStream = [IO.File]::OpenRead($path)
            try {
                $entryStream = $entry.Open()
                try {
                    $inputStream.CopyTo($entryStream)
                } finally {
                    $entryStream.Dispose()
                }
            } finally {
                $inputStream.Dispose()
            }
        }
    } finally {
        $zip.Dispose()
    }
    $hash = (Get-FileHash -LiteralPath $temporaryZip -Algorithm SHA256).Hash.ToLowerInvariant()
    Move-Item -LiteralPath $temporaryZip -Destination $target -Force
    [IO.File]::WriteAllText("$target.sha256", "$hash  $name`n", [Text.Encoding]::ASCII)
    Write-Output $target
} finally {
    if (Test-Path -LiteralPath $temporaryZip -PathType Leaf) {
        Remove-Item -LiteralPath $temporaryZip -Force
    }
}
