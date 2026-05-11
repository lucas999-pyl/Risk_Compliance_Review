param(
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (-not (Test-Path ".venv")) {
    Write-Host "Creating local virtual environment..."
    python -m venv .venv
}

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment Python not found: $Python"
}

Write-Host "Installing project dependencies..."
& $Python -m pip install --upgrade pip
& $Python -m pip install -e .

if (-not (Test-Path ".env")) {
    Write-Host "Creating portable .env for offline demo mode..."
    @"
APP_NAME=Chemical Compliance RAG Tool
DATABASE_PATH=data/risk-review.db
STORAGE_DIR=data/objects
CHEM_RAG_VECTOR_STORE_DIR=data/vector_store/chemical_rag
RCR_ENABLE_LLM=false
CHEM_RAG_EMBEDDING_PROVIDER=qwen
CHEM_RAG_EMBEDDING_MODEL=text-embedding-v4
CHEM_RAG_EMBEDDING_DIMENSIONS=1024
CHEM_RAG_LLM_PROVIDER=qwen
CHEM_RAG_LLM_MODEL=qwen3.6-plus
CHEM_RAG_REQUEST_TIMEOUT_SECONDS=20
"@ | Set-Content -LiteralPath ".env" -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path "data", "data\objects", "data\vector_store\chemical_rag" | Out-Null

Write-Host ""
Write-Host "Starting Chemical Compliance RAG Tool on http://127.0.0.1:$Port/"
Write-Host "Press Ctrl+C to stop."
& $Python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port $Port
