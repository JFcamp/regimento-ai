<#
.SYNOPSIS
  Sobe o Regimento.AI no Windows: backend (FastAPI, porta 8000) + frontend (Vite, porta 5173).

.DESCRIPTION
  Na primeira vez, baixa o modelo de embeddings e gera o índice (cerca de 20 minutos em CPU) e instala
  as dependências do frontend. Ctrl+C encerra os dois serviços.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\run.ps1
  powershell -ExecutionPolicy Bypass -File .\run.ps1 -Reindexar
  powershell -ExecutionPolicy Bypass -File .\run.ps1 -SemNavegador
#>
param(
    [switch]$Reindexar,
    [switch]$SemNavegador
)

# "Continue": no Windows PowerShell 5.1, "Stop" transforma qualquer aviso no stderr de um programa nativo
# (Python, npm) em erro fatal. Os erros reais são tratados pelo $LASTEXITCODE.
$ErrorActionPreference = "Continue"
$raiz = $PSScriptRoot
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"

function Passo([string]$texto) { Write-Host "`n==> $texto" -ForegroundColor Magenta }
function Falhar([string]$texto) { Write-Host "ERRO: $texto" -ForegroundColor Red; exit 1 }

Passo "Conferindo Python e Node"
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Falhar "Python 3.12 não encontrado no PATH." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Falhar "Node.js (npm) não encontrado no PATH." }
python --version
node --version

Passo "Conferindo dependências do backend"
# find_spec só verifica se o pacote existe, sem importar (importar o sentence_transformers leva ~1 min)
$faltando = python -c "import importlib.util as u; m=['fastapi','faiss','fitz','rank_bm25','sentence_transformers','rapidfuzz','uvicorn','pydantic_settings','httpx']; print(','.join(x for x in m if u.find_spec(x) is None))"
if ($LASTEXITCODE -ne 0 -or $faltando) {
    Write-Host "Faltando: $faltando"
    Write-Host "Instalando backend/requirements.txt ..."
    python -m pip install -r (Join-Path $raiz "backend\requirements.txt")
    if ($LASTEXITCODE -ne 0) { Falhar "Falha ao instalar as dependências do backend." }
}

if (-not (Test-Path (Join-Path $raiz ".env"))) {
    Write-Host "Aviso: .env não encontrado. Sem GEMINI_API_KEY o chat só responde as perguntas sugeridas que estiverem no cache." -ForegroundColor Yellow
    Write-Host "       Copie .env.example para .env e preencha as chaves." -ForegroundColor Yellow
}

$indice = Join-Path $raiz "data\index\index.faiss"
if ($Reindexar -or -not (Test-Path $indice)) {
    Passo "Gerando o índice (primeira vez: ~20 min em CPU)"
    Push-Location $raiz
    try {
        python -m backend.download_model
        if ($LASTEXITCODE -ne 0) { Falhar "Falha ao baixar o modelo de embeddings." }
        python -m backend.ingest
        if ($LASTEXITCODE -ne 0) { Falhar "Falha na ingestão (veja a mensagem acima)." }
    } finally { Pop-Location }
}

$front = Join-Path $raiz "frontend"
if (-not (Test-Path (Join-Path $front "node_modules"))) {
    Passo "Instalando dependências do frontend"
    Push-Location $front
    try {
        npm install --no-fund --no-audit
        if ($LASTEXITCODE -ne 0) { Falhar "Falha no npm install." }
    } finally { Pop-Location }
}

Passo "Subindo o backend em http://127.0.0.1:8000"
$logBack = Join-Path $raiz "data\cache\backend.log"
New-Item -ItemType Directory -Force (Split-Path $logBack) | Out-Null
$backend = Start-Process -FilePath python `
    -ArgumentList "-X", "utf8", "-W", "ignore", "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory $raiz -RedirectStandardOutput $logBack -RedirectStandardError "$logBack.err" -WindowStyle Hidden -PassThru

try {
    Write-Host "Carregando índice e modelo de embeddings (pode levar ~1 min) ..."
    $pronto = $false
    for ($i = 0; $i -lt 90; $i++) {
        if ($backend.HasExited) { Falhar "O backend parou. Veja $logBack.err" }
        try {
            $h = Invoke-RestMethod "http://127.0.0.1:8000/health" -TimeoutSec 3
            if ($h.status -eq "ok") { $pronto = $true; break }
            if ($h.status -eq "erro") { Falhar "Índice com erro: $($h.erro_indice)" }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $pronto) { Falhar "O backend não ficou pronto a tempo. Veja $logBack.err" }
    Write-Host "Backend pronto: $($h.indice.chunks) trechos de $($h.indice.documentos) documentos. Gemini configurado: $($h.chaves.gemini)" -ForegroundColor Green

    Passo "Subindo o frontend em http://127.0.0.1:5173  (Ctrl+C para encerrar tudo)"
    if (-not $SemNavegador) { Start-Job -ScriptBlock { Start-Sleep 4; Start-Process "http://127.0.0.1:5173" } | Out-Null }
    Push-Location $front
    try { npm run dev } finally { Pop-Location }
} finally {
    if ($backend -and -not $backend.HasExited) {
        Write-Host "`nEncerrando o backend ..."
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
}
