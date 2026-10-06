# Is this WINDOWS machine able to run ARC (through WSL2 + Docker Desktop)? Checks only; changes nothing.
# Open PowerShell (normal, not admin) and run:
#   powershell -ExecutionPolicy Bypass -File preflight-windows.ps1
# Each line ends in OK, WARN or FAIL. Send the whole output to Claude if anything is not OK.
$fail = 0
function Line($state, $what, $note) { "{0,-5} {1,-28} {2}" -f $state, $what, $note; if ($state -eq 'FAIL') { $script:fail++ } }

$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$build = [int]$os.BuildNumber
if ($build -ge 19041) { Line OK 'Windows' "$($os.Caption) build $build" } else { Line FAIL 'Windows' "build $build is too old for WSL2 (need 19041+)" }
if ($env:PROCESSOR_ARCHITECTURE -eq 'AMD64') { Line OK 'CPU type' "x64, $($cpu.Name.Trim())" } else { Line FAIL 'CPU type' "$env:PROCESSOR_ARCHITECTURE (x64 needed)" }
Line OK 'CPU cores' "$($cs.NumberOfLogicalProcessors) logical"
$gb = [math]::Round($cs.TotalPhysicalMemory / 1GB)
if ($gb -ge 30) { Line OK 'memory' "$gb GB -> give WSL 26 GB (.wslconfig), 1 cluster, maybe 2" }
elseif ($gb -ge 20) { Line WARN 'memory' "$gb GB -> 1 cluster only" } else { Line FAIL 'memory' "$gb GB is not enough (one cluster needs ~14 GB plus Windows)" }
$free = [math]::Round((Get-PSDrive C).Free / 1GB)
if ($free -ge 80) { Line OK 'disk C: free' "$free GB" } elseif ($free -ge 45) { Line WARN 'disk C: free' "$free GB (80+ recommended)" } else { Line FAIL 'disk C: free' "$free GB (need ~45 GB)" }

$virt = $cpu.VirtualizationFirmwareEnabled
$hyp = $cs.HypervisorPresent
if ($hyp -or $virt) { Line OK 'virtualization' 'enabled' } else { Line FAIL 'virtualization' 'OFF in BIOS/UEFI: WSL2 and Docker cannot start. The lab admin must enable Intel VT-x' }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$inAdmins = (whoami /groups) -match 'S-1-5-32-544'
if ($admin -or $inAdmins) { Line OK 'admin rights' 'this user is an administrator' } else { Line FAIL 'admin rights' 'not an administrator: installing WSL and Docker Desktop needs one. Ask the lab admin' }

$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
if ($wsl) {
  $out = (wsl.exe -l -v 2>$null) -replace "`0", '' | Where-Object { $_.Trim() }
  if ($out -match 'Ubuntu') { Line OK 'WSL' ('Ubuntu installed: ' + (($out | Select-String 'Ubuntu') -join ' | ').Trim()) }
  else { Line WARN 'WSL' 'no Ubuntu yet -> PowerShell as admin: wsl --install -d Ubuntu' }
} else { Line WARN 'WSL' 'not installed -> PowerShell as admin: wsl --install -d Ubuntu' }

$dd = Test-Path 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
if ($dd) { Line OK 'Docker Desktop' 'installed' } else { Line WARN 'Docker Desktop' 'not installed yet (docs/LAB-SETUP.md step 1B.3)' }
$cfg = Join-Path $env:USERPROFILE '.wslconfig'
if (Test-Path $cfg) { Line OK '.wslconfig' ((Get-Content $cfg | Where-Object { $_ -match 'memory|processors|swap' }) -join ', ') } else { Line WARN '.wslconfig' 'missing: WSL would get only half the memory (docs/LAB-SETUP.md step 1B.2)' }

foreach ($u in 'https://ghcr.io/v2/', 'https://registry-1.docker.io/v2/', 'https://github.com') {
  try { $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 12 -ErrorAction Stop; Line OK $u "reachable ($($r.StatusCode))" }
  catch { $c = $_.Exception.Response.StatusCode.value__; if ($c) { Line OK $u "reachable ($c)" } else { Line FAIL $u 'NOT reachable: firewall or proxy? Ask the lab admin' } }
}
$gpu = (Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match 'NVIDIA' } | Select-Object -First 1).Name
if ($gpu) { Line OK 'GPU' "$gpu (not needed for data collection; for training later)" } else { Line WARN 'GPU' 'no NVIDIA GPU seen (fine for data collection)' }
$sleep = (powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 2>$null | Select-String 'Current AC Power Setting Index') -replace '.*: ', ''
if ($sleep -and ([Convert]::ToInt32($sleep, 16) -ne 0)) { Line WARN 'sleep' "the PC sleeps after $([Convert]::ToInt32($sleep, 16) / 60) min idle: set Sleep to Never (sleep breaks Docker)" } else { Line OK 'sleep' 'never (on mains power)' }

""
if ($fail -gt 0) { "RESULT: $fail FAIL. Fix those first." } else { "RESULT: no FAIL. Follow docs/LAB-SETUP.md step 1B, then inside Ubuntu run: bash setup/preflight.sh" }
