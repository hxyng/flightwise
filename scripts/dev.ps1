# Starts backend (uvicorn :8000) and frontend (vite :5173) in separate windows.
$root = Split-Path -Parent $PSScriptRoot
Start-Process powershell -WorkingDirectory (Join-Path $root "backend") `
  -ArgumentList "-NoExit", "-Command", "python -m uvicorn flightwise.api:app --reload --port 8000"
Start-Process powershell -WorkingDirectory (Join-Path $root "frontend") `
  -ArgumentList "-NoExit", "-Command", "npm run dev"
Write-Host "Backend http://localhost:8000/api/health  |  Frontend http://localhost:5173"
