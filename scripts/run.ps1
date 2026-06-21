param(
    [string]$Mode = "hybrid",
    [string]$Script = "",
    [float]$Duration = 180.0
)

$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

if (-not $Script -and -not (Test-Path "data/sample_script.txt")) {
    Write-Host "Creating sample script and running pipeline..." -ForegroundColor Cyan
    python main.py --create-sample --mode $Mode --duration $Duration
} elseif ($Script) {
    Write-Host "Running pipeline with: $Script" -ForegroundColor Cyan
    python main.py --script $Script --mode $Mode --duration $Duration
} else {
    Write-Host "Running pipeline with existing sample..." -ForegroundColor Cyan
    python main.py --script "data/sample_script.txt" --mode $Mode --duration $Duration
}
