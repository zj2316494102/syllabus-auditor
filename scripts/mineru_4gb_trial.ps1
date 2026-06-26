# MinerU PoC for 4GB VRAM (RTX 3050 Laptop) — course env only, no extractor changes.
# Usage:
#   conda activate course
#   cd "C:\Users\Administrator\Desktop\课程方案\dev1"
#   .\scripts\mineru_4gb_trial.ps1 -Install
#   .\scripts\mineru_4gb_trial.ps1 -Pdf "data\某份.pdf"
#   .\scripts\mineru_4gb_trial.ps1 -Pdf "data\某份.pdf" -ForceCpu

param(
    [switch]$Install,
    [string]$Pdf = "",
    [switch]$ForceCpu,
    [string]$OutputRoot = "C:\mineru_trial\output"
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host "`n==> $msg" -ForegroundColor Cyan
}

if ($Install) {
    Write-Step "Upgrade pip"
    python -m pip install --upgrade pip

    Write-Step "Install MinerU pipeline extra from PyPI (NOT hybrid/vlm — needs 8GB+ VRAM)"
    # Do NOT use --index-url here; that replaces PyPI and mineru won't be found.
    pip install "mineru[pipeline]"

    Write-Step "Install CUDA torch for pipeline GPU acceleration (optional but faster on 4GB)"
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

    Write-Step "Verify"
    mineru --version
    python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
    exit 0
}

if (-not $Pdf) {
    Write-Host @"
MinerU 4GB trial helper

Install:
  .\scripts\mineru_4gb_trial.ps1 -Install

Run one PDF (pipeline backend, 4GB-safe):
  .\scripts\mineru_4gb_trial.ps1 -Pdf "data\xxx.pdf"

Force pure CPU if GPU still OOM:
  .\scripts\mineru_4gb_trial.ps1 -Pdf "data\xxx.pdf" -ForceCpu
"@
    exit 0
}

if (-not (Test-Path $Pdf)) {
    throw "PDF not found: $Pdf"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

# 4GB strategy: pipeline only. hybrid-auto-engine loads 4-5 models (~8GB+).
$env:MINERU_HYBRID_BATCH_RATIO = "1"

if ($ForceCpu) {
    $env:MINERU_DEVICE_MODE = "cpu"
    $env:CUDA_VISIBLE_DEVICES = ""
    Write-Step "Force CPU mode (slow but stable, zero VRAM)"
} else {
    Remove-Item Env:MINERU_DEVICE_MODE -ErrorAction SilentlyContinue
    Remove-Item Env:CUDA_VISIBLE_DEVICES -ErrorAction SilentlyContinue
    Write-Step "Pipeline + GPU (official min 4GB VRAM). OOM? rerun with -ForceCpu"
}

Write-Step "Parse: $Pdf"
mineru -p $Pdf `
    -o $OutputRoot `
    -b pipeline `
    -l ch `
    -m auto `
    -f false `
    -t true

Write-Step "Done. Check output under: $OutputRoot"
