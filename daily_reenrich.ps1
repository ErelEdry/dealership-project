# Daily automation - finish issue #2 (uniform enrichment provenance) within
# Groq's free-tier daily token budget.
#
# Quota-resilient & self-terminating: re-enriches only stale rows (last enriched
# before the cutoff), stops cleanly when the daily token cap is hit, and disables
# its own scheduled task once no stale rows remain.
#
# Registered as scheduled task 'DealershipAI-ReenrichProvenance'.

$ErrorActionPreference = 'Continue'
$proj   = 'C:\Users\Erel\Documents\Claude\Projects\DE Project\dealership-ai'
$cutoff = '2026-08-17'
$task   = 'DealershipAI-ReenrichProvenance'

$logDir = Join-Path $proj 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir ("reenrich_{0}.log" -f (Get-Date -Format 'yyyy-MM-dd_HHmmss'))

Set-Location $proj
("[{0}] daily reenrich starting (cutoff {1})" -f (Get-Date -Format o), $cutoff) | Tee-Object $log

# Ensure the stack is up (no-op if already running; requires the Docker engine).
docker compose up -d 2>&1 | Tee-Object $log -Append

# Resume: quota-resilient, skips already-migrated rows, stops cleanly on 429.
docker compose exec -T api python -m app.etl.pipeline --reenrich-before $cutoff 2>&1 | Tee-Object $log -Append

# If no stale rows remain, the migration is done - disable this task.
$remaining = (docker compose exec -T api python -m scripts.reenrich_status --cutoff $cutoff 2>$null | Select-Object -Last 1)
if ($remaining) { $remaining = $remaining.ToString().Trim() }
("[{0}] remaining stale rows: {1}" -f (Get-Date -Format o), $remaining) | Tee-Object $log -Append

if ($remaining -eq '0') {
    Disable-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue | Out-Null
    ("[{0}] all rows migrated - task '{1}' disabled." -f (Get-Date -Format o), $task) | Tee-Object $log -Append
}
