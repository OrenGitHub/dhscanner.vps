$start = Get-Date
docker compose `
-f .\compose\compose.base.yaml `
-f .\compose\compose.app.yaml `
-f .\compose\compose.fronts.yaml `
-f .\compose\compose.prebuilt.yaml `
-f .\compose\compose.workers.yaml up -d
$end = Get-Date
$duration = $end - $start
Write-Host "Finished: ( $($duration.TotalSeconds) seconds)"