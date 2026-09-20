# Clean leftover Remotion temp asset copies (public/ gets copied into system Temp
# on every render/still - a full public/ can be ~1GB per run).
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools/clean_remotion_temp.ps1        # all remotion-* dirs
#   powershell -ExecutionPolicy Bypass -File tools/clean_remotion_temp.ps1 -Days 1 # only older than 1 day
param([int]$Days = 0)
$roots = @($env:TEMP, $env:TMP) | Where-Object { $_ } | Select-Object -Unique
$freed = 0
foreach ($r in $roots) {
  if (-not (Test-Path $r)) { continue }
  Get-ChildItem $r -Directory -Filter 'remotion-*' -ErrorAction SilentlyContinue | ForEach-Object {
    $age = (New-TimeSpan -Start $_.LastWriteTime).TotalDays
    if ($age -ge $Days) {
      $size = (Get-ChildItem $_.FullName -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
      if (-not $size) { $size = 0 }
      Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
      $script:freed += $size
      Write-Host ("removed {0} ({1:N1} MB)" -f $_.Name, ($size / 1MB))
    }
  }
}
Write-Host ("done, freed {0:N1} MB" -f ($freed / 1MB))
