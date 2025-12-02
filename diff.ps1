# save-diff.ps1
# Save current git diffs (unstaged + staged) to a timestamped patch file

# Go to script directory if you want consistent file placement
Set-Location (Get-Location)

# Create a timestamped filename unless user provided one
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outputFile = if ($args.Count -gt 0) { $args[0] } else { "git_diff_$timestamp.patch" }

# Write diff sections to the file
"# === Unstaged changes ===" | Out-File $outputFile -Encoding utf8
git diff | Out-File $outputFile -Append -Encoding utf8

"`n# === Staged changes ===" | Out-File $outputFile -Append -Encoding utf8
git diff --cached | Out-File $outputFile -Append -Encoding utf8

Write-Host "✅ Git diff sa ved to: $outputFile"
