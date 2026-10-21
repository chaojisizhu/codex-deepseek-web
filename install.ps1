# Install the ds-web Codex plugin on Windows (PowerShell 5.1+ / 7+).
#
#   .\install.ps1              # install / update
#   .\install.ps1 -Uninstall   # remove
#
# Creates the same layout as install.sh:
#   %USERPROFILE%\.agents\plugins\marketplace.json
#   %USERPROFILE%\plugins\ds-web\...
#
# Env: CODEX_HOME (default %USERPROFILE%\.codex)
[CmdletBinding()]
param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

$SrcDir        = Split-Path -Parent $MyInvocation.MyCommand.Path
$CodexHome     = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
$Marketplace   = "personal"
$PluginName    = "ds-web"
$MarketplaceFile = Join-Path $HOME ".agents\plugins\marketplace.json"
$PluginDest    = Join-Path $HOME "plugins\$PluginName"
$PluginId      = "$PluginName@$Marketplace"

if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw "codex CLI not found on PATH. Install it with: winget install --id OpenAI.Codex"
}

# Codex on Windows is often the npm shim codex.cmd; call it through cmd.exe so
# PowerShell resolves it consistently in both hosted and interactive sessions.
function Invoke-Codex {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    & cmd.exe /d /c codex @Args
    if ($LASTEXITCODE -ne 0) { throw "codex $($Args -join ' ') failed with exit code $LASTEXITCODE" }
}

function Invoke-CodexQuiet {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    & cmd.exe /d /c codex @Args 2>&1 | Out-Null
}

$Py = $null
foreach ($candidate in @("python", "py", "python3")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch "WindowsApps") { $Py = $candidate; break }
}
if (-not $Py) {
    throw "Python 3.9+ not found on PATH (tried python, py, python3). Install it from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'."
}

if ($Uninstall) {
    try { Invoke-CodexQuiet plugin remove $PluginId } catch { }
    if (Test-Path $PluginDest) { Remove-Item -Recurse -Force $PluginDest }
    Write-Host "removed $PluginName (marketplace entry in $MarketplaceFile left untouched)"
    exit 0
}

# 1. Copy the plugin payload into %USERPROFILE%\plugins\<name>.
New-Item -ItemType Directory -Force -Path $PluginDest | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $MarketplaceFile) | Out-Null
Get-ChildItem -Force -Path $PluginDest | Remove-Item -Recurse -Force
$exclude = @(".git", "__pycache__")
Get-ChildItem -Force -Path $SrcDir | Where-Object { $exclude -notcontains $_.Name } | ForEach-Object {
    Copy-Item -Recurse -Force -Path $_.FullName -Destination (Join-Path $PluginDest $_.Name)
}
Write-Host "plugin payload copied to $PluginDest"

# 2. Register / refresh the marketplace entry idempotently.
$entry = [ordered]@{
    name   = $PluginName
    source = [ordered]@{ source = "local"; path = "./plugins/$PluginName" }
    policy = [ordered]@{ installation = "AVAILABLE"; authentication = "ON_INSTALL" }
    category = "Research"
}
if (Test-Path $MarketplaceFile) {
    $payload = Get-Content -Raw $MarketplaceFile | ConvertFrom-Json
} else {
    $payload = [pscustomobject]@{ name = $Marketplace; interface = [pscustomobject]@{ displayName = "Personal" }; plugins = @() }
}
$plugins = @($payload.plugins) | Where-Object { $_ -and $_.name -ne $PluginName }
$plugins += [pscustomobject]$entry
$payload.plugins = @($plugins)
if (-not $payload.name) { $payload | Add-Member -NotePropertyName name -NotePropertyValue $Marketplace }
$payload | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 $MarketplaceFile
Write-Host "marketplace entry written: $MarketplaceFile"

# 3. Pin a Python launcher that exists on this machine (no per-platform MCP
#    command override exists in Codex, and Windows has no `python3`).
$interpreter = & $Py (Join-Path $PluginDest "scripts\select_python_command.py") $PluginDest
if ($LASTEXITCODE -ne 0) { throw "failed to select a Python interpreter for the MCP server" }
Write-Host "MCP server will launch with: $interpreter"

# 4. Register the marketplace and install the plugin.
Invoke-CodexQuiet plugin marketplace add $HOME
try { Invoke-CodexQuiet plugin remove $PluginId } catch { }
Invoke-Codex plugin add $PluginId

Write-Host @"

Installed $PluginId

Required config — $CodexHome\config.toml (GPT / default sessions keep it off):

  [plugins."$PluginId".mcp_servers.ds_web]
  enabled = false

Required config — $CodexHome\deepseek.config.toml (DeepSeek sessions turn it on):

  model = "deepseek-v4-flash"
  model_provider = "deepseek"
  [plugins."$PluginId".mcp_servers.ds_web]
  enabled = true

Give Codex the API key (PowerShell, persists for your user):

  setx DEEPSEEK_API_KEY "sk-..."

Run DeepSeek with:  codex --profile deepseek
"@
