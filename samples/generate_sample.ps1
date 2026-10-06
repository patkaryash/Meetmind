# Synthesizes samples/sample_meeting.wav from samples/meeting_script.txt
# using the built-in Windows SAPI voices (no network needed).
Add-Type -AssemblyName System.Speech
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$text = Get-Content -Raw -Path (Join-Path $scriptDir "meeting_script.txt")
$out = Join-Path $scriptDir "sample_meeting.wav"

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice("Microsoft David Desktop")
$synth.Rate = -1
$synth.SetOutputToWaveFile($out)
$synth.Speak($text)
$synth.SetOutputToNull()
$synth.Dispose()

Write-Host "Wrote $out"
