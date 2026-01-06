# PCLink Development Environment Setup
# Run this before starting PCLink to use extensions from pclink-extensions workspace

$env:PCLINK_EXTENSIONS_PATH = "C:\Dev\Projects\python\pclink-extensions\extensions"

Write-Host "✅ Extension path set to: $env:PCLINK_EXTENSIONS_PATH" -ForegroundColor Green
Write-Host ""
Write-Host "Now you can run: pclink" -ForegroundColor Cyan
Write-Host ""
Write-Host "Extensions will be loaded from pclink-extensions workspace" -ForegroundColor Yellow
