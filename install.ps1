<#
.SYNOPSIS
  Installs the `venice` CLI on Windows (cmd.exe + PowerShell).
.DESCRIPTION
  Downloads venice.py + a flat venice.bat shim into a PATH folder and adds that
  folder to the User PATH. Needs python3 on PATH (or the `python` launcher).
.EXAMPLE
  iwr https://raw.githubusercontent.com/Parsa-Nasiri/venice-free-ai-chat/main/install.ps1 -OutFile i.ps1; .\i.ps1
#>
param(
    [string]$Target = "$HOME\.local\bin"
)
$ErrorActionPreference = "Stop"
$base = "https://raw.githubusercontent.com/Parsa-Nasiri/venice-free-ai-chat/main"

if (!(Test-Path $Target)) { New-Item -ItemType Directory -Path $Target -Force | Out-Null }
Write-Host "Installing venice CLI -> $Target"

Invoke-WebRequest "$base/venice.py"        -OutFile "$Target\venice.py"        -UseBasicParsing
# cmd / PowerShell shim: %~dp0 resolves to the shim's own native dir
'@echo off
python "%~dp0venice.py" %*' | Set-Content -Path "$Target\venice.bat" -Encoding ASCII

# add $Target to User PATH if missing (current shell unaffected; reopen cmd/ps)
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($null -eq $userPath) { $userPath = "" }
$parts = $userPath -split ";" | Where-Object { $_ }
if (-not ($parts -contains $Target)) {
    [Environment]::SetEnvironmentVariable("Path", "User", ($parts + $Target) -join ";")
    Write-Host "Added $Target to User PATH (reopen cmd/powershell to pick it up)."
} else {
    Write-Host "$Target already on User PATH."
}

Write-Host "Done. Verify:  venice doctor"
Write-Host "First run:     venice deploy   (opens Cloudflare token page if no CF_API_TOKEN)"
