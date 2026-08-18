$ErrorActionPreference = 'Stop'
$app = 'C:\vitab\build\dist-r4\Vi-Analyza.exe'
$work = 'C:\vitab\build\dist-r4'
$pdf = 'C:\vitab\06_5np-podorys 5np legenda.pdf'
$ocrPdf = 'C:\vitab\02_Podorys 1NP.pdf'
$proc = Start-Process -FilePath $app -WorkingDirectory $work -PassThru
try {
  $ping = $null
  $port = $null
  foreach ($attempt in 1..80) {
    Start-Sleep -Seconds 1
    foreach ($candidate in 8765..8785) {
      try {
        $value = Invoke-RestMethod ("http://127.0.0.1:$candidate/api/ping") -TimeoutSec 1
        if ($value.krivky) { $ping = $value; $port = $candidate; break }
      } catch {}
    }
    if ($ping) { break }
  }
  if (-not $ping) { throw 'Runtime nenašiel modul kriviek.' }
  if (-not ($ping.ocr -and $ping.legend -and $ping.kataster -and $ping.konkurencia)) {
    throw "Neúplný runtime: $($ping | ConvertTo-Json -Compress)"
  }
  $curve = Invoke-RestMethod "http://127.0.0.1:$port/api/krivky" -Method Post -InFile $pdf -ContentType 'application/pdf' -TimeoutSec 120
  if (-not $curve.ok -or $curve.stats.glyphs -lt 1 -or $curve.stats.cells -lt 1) {
    throw "Čítanie kriviek zlyhalo: $($curve | ConvertTo-Json -Compress)"
  }
  $ocr = Invoke-RestMethod "http://127.0.0.1:$port/api/legend" -Method Post -InFile $ocrPdf -ContentType 'application/pdf' -Headers @{'X-Filename'='Nove-Suty-A-1NP.pdf'} -TimeoutSec 300
  if (-not $ocr.ok -or $ocr.via -ne 'ocr' -or -not $ocr.csv) {
    throw "OCR legenda zlyhala: $($ocr | ConvertTo-Json -Compress)"
  }
  [ordered]@{ ping=$ping; curveStats=$curve.stats; ocrVia=$ocr.via; ocrCsvLength=$ocr.csv.Length } | ConvertTo-Json -Depth 4 -Compress
} finally {
  Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}
