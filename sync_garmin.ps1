Set-Location $PSScriptRoot

Write-Host "Spoustim Garmin export..."
python garmin_browser_export.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "Export selhal." -ForegroundColor Red
    exit 1
}

$status = git status --porcelain garmin_archive.json
if (-not $status) {
    Write-Host "garmin_archive.json se nezmenil, neni co commitovat." -ForegroundColor Yellow
    exit 0
}

$date = Get-Date -Format "yyyy-MM-dd"
git add garmin_archive.json
git commit -m "Sync Garmin archive $date"
git push origin HEAD

Write-Host "Hotovo!" -ForegroundColor Green
