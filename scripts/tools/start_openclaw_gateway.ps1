param(
    [switch]$OpenDashboard = $true
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-EnvFromDotEnv {
    param(
        [Parameter(Mandatory = $true)][string]$DotEnvPath,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if (-not (Test-Path $DotEnvPath)) {
        return $null
    }

    $line = Get-Content $DotEnvPath | Where-Object { $_ -match "^\s*$Name\s*=" } | Select-Object -First 1
    if (-not $line) {
        return $null
    }

    $m = [regex]::Match($line, "^\s*$Name\s*=\s*(.+?)\s*$")
    if (-not $m.Success) {
        return $null
    }

    $v = $m.Groups[1].Value.Trim()
    $v = $v.Trim('"').Trim("'")
    if ([string]::IsNullOrWhiteSpace($v)) {
        return $null
    }
    return $v
}

function Resolve-PersonaFile {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )
    $base = Join-Path $RepoRoot "core\character\configs"
    $candidates = @()

    if ($env:XIAOYOU_OPENCLAW_PERSONA) {
        $candidates += (Join-Path $base $env:XIAOYOU_OPENCLAW_PERSONA)
    }
    # Aveline 的 QQ 专属人设已删除，首选核心人设
    $candidates += (Join-Path $base "core_aveline.json")
    $candidates += (Join-Path $base "sfw\Aveline_DeepSeek_SFW.json")
    $candidates += (Join-Path $base "base_aveline.json")

    foreach ($p in $candidates) {
        if (Test-Path $p) {
            return $p
        }
    }

    $fallback = Get-ChildItem -Path $base -Recurse -Filter *.json -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($fallback) {
        return $fallback.FullName
    }
    return $null
}

function Resolve-RecentChatFile {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )
    $historyDir = Join-Path $RepoRoot "history\short_term"
    if (-not (Test-Path $historyDir)) {
        return $null
    }
    $default = Join-Path $historyDir "default_user_short.json"
    if (Test-Path $default) {
        return $default
    }
    $latest = Get-ChildItem -Path $historyDir -Filter *_short.json -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latest) {
        return $latest.FullName
    }
    return $null
}

function Sync-OpenClawWorkspaceContext {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )
    $userHome = [Environment]::GetFolderPath("UserProfile")
    $workspaceDir = Join-Path $userHome ".openclaw\workspace"
    $markerPath = Join-Path $RepoRoot ".openclaw_sync_marker.txt"
    Set-Content -Path $markerPath -Value ("sync_started=" + (Get-Date).ToString("s") + "`nworkspace=" + $workspaceDir) -Encoding UTF8
    New-Item -Path $workspaceDir -ItemType Directory -Force | Out-Null
    $syncOk = $false
    try {

    $personaFile = Resolve-PersonaFile -RepoRoot $RepoRoot
    $persona = $null
    if ($personaFile -and (Test-Path $personaFile)) {
        try {
            # Most repo configs are UTF-8 without BOM; PowerShell 5.1 defaults to ANSI, so force UTF-8.
            $persona = Get-Content -Raw -Encoding UTF8 $personaFile | ConvertFrom-Json -Depth 100
        }
        catch {
            $persona = $null
        }
    }

    $identityName = "Aveline"
    $identityVibe = "Calm, precise, companion-like"
    $identityContext = ""
    $userDisplayName = "User"
    $systemPrompt = ""

    if ($persona) {
        $hasIdentity = $persona.PSObject.Properties.Name -contains "identity"
        if ($hasIdentity -and $persona.identity) {
            if (($persona.identity.PSObject.Properties.Name -contains "cn_name") -and $persona.identity.cn_name) {
                $identityName = [string]$persona.identity.cn_name
            }
            elseif (($persona.identity.PSObject.Properties.Name -contains "name") -and $persona.identity.name) {
                $identityName = [string]$persona.identity.name
            }
            if (($persona.identity.PSObject.Properties.Name -contains "context") -and $persona.identity.context) {
                $identityContext = [string]$persona.identity.context
            }
        }
        $hasLanguageStyle = $persona.PSObject.Properties.Name -contains "language_style"
        if ($hasLanguageStyle -and $persona.language_style -and ($persona.language_style.PSObject.Properties.Name -contains "tone") -and $persona.language_style.tone) {
            $identityVibe = [string]$persona.language_style.tone
        }
        $hasUserProfile = $persona.PSObject.Properties.Name -contains "user_profile"
        if ($hasUserProfile -and $persona.user_profile -and ($persona.user_profile.PSObject.Properties.Name -contains "name") -and $persona.user_profile.name) {
            $userDisplayName = [string]$persona.user_profile.name
        }
        $hasSystemPrompt = $persona.PSObject.Properties.Name -contains "system_prompt_template"
        if ($hasSystemPrompt -and $persona.system_prompt_template) {
            $systemPrompt = [string]$persona.system_prompt_template
        }
    }

    if ($userDisplayName -eq "User" -and $personaFile -and ($personaFile -replace "/", "\") -match "\\qq\\") {
        $userDisplayName = "Master"
    }
    if ($userDisplayName -eq "User" -and $systemPrompt) {
        if ($systemPrompt -match "Master") {
            $userDisplayName = "Master"
        } else {
            $m = [regex]::Match($systemPrompt, "陪伴(?:我的)?\s*([A-Za-z0-9_\u4e00-\u9fff]{1,12})")
            if ($m.Success) {
                $userDisplayName = $m.Groups[1].Value
            }
        }
    }
    if ($userDisplayName -match "^\s*你是") {
        $userDisplayName = "Master"
    }

    $identityPath = Join-Path $workspaceDir "IDENTITY.md"
    $userPath = Join-Path $workspaceDir "USER.md"
    $soulPath = Join-Path $workspaceDir "SOUL.md"
    $chatPath = Join-Path $workspaceDir "XIAOYOU_RECENT_CHAT.md"
    $bootstrapPath = Join-Path $workspaceDir "BOOTSTRAP.md"
    $customUserTemplate = Join-Path $RepoRoot "core\character\configs\openclaw\USER.md"
    $customSoulTemplate = Join-Path $RepoRoot "core\character\configs\openclaw\SOUL.md"

    $identityContent = @(
        "# IDENTITY.md - Synced From Xiaoyou Backend",
        "",
        "- **Name:** $identityName",
        "- **Creature:** Aveline backend agent",
        "- **Vibe:** $identityVibe",
        "- **Emoji:** none",
        "- **Avatar:**",
        "",
        "## Runtime Context",
        "",
        "- Persona source: $personaFile",
        "- Persona context: $identityContext",
        "- Generated by: scripts/tools/start_openclaw_gateway.ps1",
        ""
    ) -join "`n"
    Set-Content -Path $identityPath -Value $identityContent -Encoding UTF8

    $userContent = ""
    if (Test-Path $customUserTemplate) {
        $userContent = Get-Content -Raw -Encoding UTF8 $customUserTemplate
    } else {
        $userContent = @(
            "# USER.md - Synced From Xiaoyou Backend",
            "",
            "- **Name:** $userDisplayName",
            "- **What to call them:** $userDisplayName",
            "- **Pronouns:**",
            "- **Timezone:** Asia/Shanghai",
            "- **Notes:** Data sourced from backend persona/memory",
            ""
        ) -join "`n"
    }
    Set-Content -Path $userPath -Value $userContent -Encoding UTF8

    if (Test-Path $customSoulTemplate) {
        Set-Content -Path $soulPath -Value (Get-Content -Raw -Encoding UTF8 $customSoulTemplate) -Encoding UTF8
    } else {
        $soulLines = @(
            "# SOUL.md - Backend Persona Policy",
            "",
            "This file is generated from Xiaoyou backend persona configuration.",
            "",
            "## System Prompt Template",
            "",
            '```text',
            $systemPrompt,
            '```',
            ""
        )
        Set-Content -Path $soulPath -Value ($soulLines -join "`n") -Encoding UTF8
    }

        $recentChatFile = Resolve-RecentChatFile -RepoRoot $RepoRoot
        $chatLines = @("# XIAOYOU_RECENT_CHAT.md", "")
        if ($recentChatFile -and (Test-Path $recentChatFile)) {
            try {
                # Backend short-term history can include huge embeddings; strip them to keep ConvertFrom-Json stable.
                $rawRecent = Get-Content -Raw -Encoding UTF8 $recentChatFile
                $rawRecent = [regex]::Replace($rawRecent, '"embedding"\s*:\s*"[^"]*"\s*,?', '', 'IgnoreCase')
                $recent = $rawRecent | ConvertFrom-Json -Depth 100
                $recentItems = @($recent)
                $slice = $recentItems | Select-Object -Last 20
                foreach ($item in $slice) {
                    $r = "unknown"
                    if ($item -and ($item.PSObject.Properties.Name -contains "role") -and $null -ne $item.role) {
                        $r = [string]$item.role
                    } elseif ($item -and ($item.PSObject.Properties.Name -contains "source") -and $null -ne $item.source) {
                        $r = [string]$item.source
                    }
                    $c = ""
                    if ($item -and ($item.PSObject.Properties.Name -contains "content") -and $null -ne $item.content) {
                        $c = [string]$item.content
                    }
                    if (-not [string]::IsNullOrWhiteSpace($c)) {
                        $chatLines += "- [$r] $c"
                    }
                }
            }
            catch {
                $chatLines += "- Failed to parse $recentChatFile"
            }
        }
        if ($chatLines.Count -le 2) {
            if ($recentChatFile -and (Test-Path $recentChatFile)) {
                $raw = Get-Content -Raw -Encoding UTF8 $recentChatFile
                $mFallback = [regex]::Match($raw, '"content"\s*:\s*"([^"]+)"')
                if ($mFallback.Success) {
                    $chatLines += "- [assistant] " + $mFallback.Groups[1].Value
                } else {
                    $chatLines += "- No recent chat found in backend history."
                }
            } else {
                $chatLines += "- No recent chat found in backend history."
            }
        }
        Set-Content -Path $chatPath -Value ($chatLines -join "`n") -Encoding UTF8

        if (Test-Path $bootstrapPath) {
            Remove-Item $bootstrapPath -Force
        }
        $syncOk = $true
    }
    finally {
        if ($syncOk) {
            Add-Content -Path $markerPath -Value ("`nsync_done=" + (Get-Date).ToString("s")) -Encoding UTF8
        } else {
            Add-Content -Path $markerPath -Value ("`nsync_failed=" + (Get-Date).ToString("s")) -Encoding UTF8
        }
    }
}

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$openclawDir = Join-Path $repoRoot "external\openclaw-main"
$dotEnv = Join-Path $repoRoot ".env"
$healthUrl = "http://127.0.0.1:18789/health"

if (-not (Test-Path $openclawDir)) {
    Write-Error "OpenClaw directory not found: $openclawDir"
}

Sync-OpenClawWorkspaceContext -RepoRoot $repoRoot

$deepseek = Get-EnvFromDotEnv -DotEnvPath $dotEnv -Name "DEEPSEEK_API_KEY"
if ($deepseek) {
    $env:DEEPSEEK_API_KEY = $deepseek
}

$dashscope = Get-EnvFromDotEnv -DotEnvPath $dotEnv -Name "DASHSCOPE_API_KEY"
if ($dashscope) {
    $env:DASHSCOPE_API_KEY = $dashscope
    # OpenClaw provider resolution prefers provider-native env names.
    # Map DashScope key to OpenAI/Qwen aliases so custom provider placeholders
    # do not get treated as literal API keys.
    $env:OPENAI_API_KEY = $dashscope
    $env:QWEN_PORTAL_API_KEY = $dashscope
}

Push-Location $openclawDir
try {
    if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
        throw "pnpm not found in PATH."
    }

    try {
        $health = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 2
        if ($health.StatusCode -eq 200) {
            Write-Host "[INFO] OpenClaw gateway is already running on 127.0.0.1:18789, skip start."
            if ($OpenDashboard) {
                Write-Host "[INFO] Opening OpenClaw dashboard with token..."
                & pnpm openclaw dashboard
            }
            exit 0
        }
    }
    catch {
        # Not running yet, continue to start.
    }

    if (-not (Test-Path (Join-Path $openclawDir "node_modules"))) {
        Write-Host "[INFO] node_modules missing, running pnpm install..."
        & pnpm install
        if ($LASTEXITCODE -ne 0) {
            throw "pnpm install failed with exit code $LASTEXITCODE"
        }
    }

    Write-Host "[INFO] Starting OpenClaw gateway at http://127.0.0.1:18789 ..."
    if ($OpenDashboard) {
        # Open dashboard in a separate process so the gateway can keep running in this terminal.
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "cd /d `"$openclawDir`" && pnpm openclaw dashboard" | Out-Null
    }
    & pnpm openclaw gateway --port 18789 --allow-unconfigured --verbose
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
