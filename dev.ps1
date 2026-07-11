# Community Management dev helper for Windows PowerShell.
# Usage:  .\dev.ps1 <command>
# Commands: up, down, migrate, seed, test, status, health, logs
# The Makefile is for Unix shells; this mirrors it on Windows.

param(
    [Parameter(Position = 0)]
    [string]$Command = "help"
)

$ApiKey = "change-me"
$Base = "http://localhost:8000"

function Invoke-Api($Path) {
    Invoke-RestMethod -Uri "$Base$Path" -Headers @{ "X-API-Key" = $ApiKey } | ConvertTo-Json -Depth 6
}

switch ($Command) {
    "up"      { docker compose up --build }
    "down"    { docker compose down }
    "migrate" { docker compose exec api alembic upgrade head }
    "seed"    { docker compose exec api python -m scripts.seed_dev_data }
    "test"    { docker compose exec api pytest -q }
    "status"  { Invoke-Api "/ingestion/status" }
    "health"  { Invoke-RestMethod -Uri "$Base/health" -Headers @{ "X-API-Key" = $ApiKey } | ConvertTo-Json -Depth 6 }
    "logs"    { docker compose logs -f api worker beat }
    default   {
        Write-Host "Community Management dev commands:" -ForegroundColor Cyan
        Write-Host "  .\dev.ps1 up       # build and start the stack"
        Write-Host "  .\dev.ps1 migrate  # apply database migrations"
        Write-Host "  .\dev.ps1 seed     # load synthetic dev fixtures"
        Write-Host "  .\dev.ps1 test     # run the pytest suite"
        Write-Host "  .\dev.ps1 status   # ingestion row counts + cursors"
        Write-Host "  .\dev.ps1 health   # readiness check"
        Write-Host "  .\dev.ps1 down     # stop the stack"
        Write-Host "  .\dev.ps1 logs     # tail api/worker/beat logs"
    }
}
