# Make synthetic test WAVs (24 kHz, 16-bit, mono) with the Windows built-in voices.
# Usage: pwsh scripts/make_fixtures.ps1
Add-Type -AssemblyName System.Speech
$dir = Join-Path $PSScriptRoot "..\tests\fixtures"
New-Item -ItemType Directory -Force $dir | Out-Null
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(24000,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono)
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer

function Save($name, $prompt) {
    $s.SetOutputToWaveFile((Join-Path $dir $name), $fmt)
    $s.Speak($prompt)
    $s.SetOutputToNull()
}

$p = New-Object System.Speech.Synthesis.PromptBuilder
$p.AppendText("Book a table for two at seven on Friday.")
Save "fluent.wav" $p

$p = New-Object System.Speech.Synthesis.PromptBuilder
$p.AppendText("Book a table for")
$p.AppendBreak([TimeSpan]::FromSeconds(3))
$p.AppendText("two at seven on Friday.")
Save "pause.wav" $p

$p = New-Object System.Speech.Synthesis.PromptBuilder
$p.AppendText("My name is Binula and I live in Matara, near Weligama.")
Save "names.wav" $p

$p = New-Object System.Speech.Synthesis.PromptBuilder
$p.StartVoice("Microsoft David Desktop"); $p.AppendText("I would like to book a table for tonight, please."); $p.EndVoice()
$p.AppendBreak([TimeSpan]::FromMilliseconds(800))
$p.StartVoice("Microsoft Zira Desktop"); $p.AppendText("Sure. How many people will be joining you, and what time works best?"); $p.EndVoice()
$p.AppendBreak([TimeSpan]::FromMilliseconds(800))
$p.StartVoice("Microsoft David Desktop"); $p.AppendText("Four people at eight o'clock."); $p.EndVoice()
Save "two_voices.wav" $p

$s.Dispose()
Get-ChildItem $dir -Filter *.wav | Select-Object Name, Length
