$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..')).Path
$EnvFile = Join-Path $Root '.env'
if (Test-Path $EnvFile) {
  Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
      Set-Item -Path "Env:$($matches[1])" -Value $matches[2].Trim().Trim('"').Trim("'")
    }
  }
}
$Port = if ($env:EASEL_OPENCODE_PORT) { $env:EASEL_OPENCODE_PORT } else { '18789' }
$Log = Join-Path $env:TEMP 'easel-opencode.log'
$PidFile = Join-Path $env:TEMP 'easel-opencode.pid'

function Is-Live {
  try {
    $Headers = @{}
    if ($env:OPENCODE_SERVER_PASSWORD) {
      $Username = if ($env:OPENCODE_SERVER_USERNAME) { $env:OPENCODE_SERVER_USERNAME } else { 'opencode' }
      $Token = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${Username}:$($env:OPENCODE_SERVER_PASSWORD)"))
      $Headers.Authorization = "Basic $Token"
    }
    $null = Invoke-RestMethod "http://127.0.0.1:$Port/global/health" -Headers $Headers -TimeoutSec 2
    return $true
  } catch { return $false }
}
$Action = if ($args.Count) { $args[0] } else { 'status' }

switch ($Action) {
  'start' {
    if (Is-Live) { Write-Host '[easel] OpenCode server already running'; exit 0 }
    if (-not (Get-Command opencode -ErrorAction SilentlyContinue)) { Write-Error 'OpenCode CLI not found'; exit 1 }
    $p = Start-Process opencode -ArgumentList @('serve','--hostname','127.0.0.1','--port',$Port) -RedirectStandardOutput $Log -RedirectStandardError "$Log.err" -PassThru -WindowStyle Hidden
    Set-Content $PidFile $p.Id
    foreach ($i in 1..20) { if (Is-Live) { Write-Host "[easel] OpenCode server started (PID $($p.Id))"; exit 0 }; Start-Sleep -Milliseconds 250 }
    Write-Error "OpenCode server failed to start; check $Log"; exit 1
  }
  'stop' {
    if (Test-Path $PidFile) { $id = Get-Content $PidFile; Stop-Process -Id $id -ErrorAction SilentlyContinue; Remove-Item $PidFile -Force; Write-Host '[easel] OpenCode server stopped' } else { Write-Host '[easel] OpenCode server was not running' }
  }
  'restart' { & $MyInvocation.MyCommand.Path stop; & $MyInvocation.MyCommand.Path start }
  'status' { if (Is-Live) { Write-Host '[easel] OpenCode server running'; exit 0 }; Write-Host '[easel] OpenCode server not running'; exit 1 }
  'logs' { Get-Content $Log -Wait }
  default { Write-Error 'Usage: opencode-gateway.ps1 {start|stop|restart|status|logs}'; exit 1 }
}
