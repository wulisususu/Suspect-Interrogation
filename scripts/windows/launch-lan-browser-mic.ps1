param(
    [Parameter(Mandatory = $true)]
    [string]$Origin,

    [ValidateSet('auto', 'edge', 'chrome')]
    [string]$Browser = 'auto'
)

$ErrorActionPreference = 'Stop'

try {
    $uri = [Uri]$Origin
} catch {
    throw "Origin 无效，例如：http://192.168.1.50:18080"
}

if ($uri.Scheme -notin @('http', 'https')) {
    throw 'Origin 只允许 http 或 https。'
}

function Test-PrivateHost([string]$HostName) {
    if ($HostName -in @('localhost', '127.0.0.1', '::1')) { return $true }

    $ip = $null
    if (-not [System.Net.IPAddress]::TryParse($HostName, [ref]$ip)) {
        return $HostName.EndsWith('.local') -or $HostName.EndsWith('.lan')
    }

    if ($ip.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
        return $ip.Equals([System.Net.IPAddress]::IPv6Loopback)
    }

    $bytes = $ip.GetAddressBytes()
    if ($bytes[0] -eq 10) { return $true }
    if ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) { return $true }
    if ($bytes[0] -eq 192 -and $bytes[1] -eq 168) { return $true }
    if ($bytes[0] -eq 127) { return $true }
    return $false
}

if (-not (Test-PrivateHost $uri.Host)) {
    throw "拒绝为公网地址启用浏览器测试权限：$($uri.Host)。本脚本只允许 localhost / RFC1918 / .local / .lan。"
}

$candidates = @()
if ($Browser -in @('auto', 'edge')) {
    $candidates += @(
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe"
    )
}
if ($Browser -in @('auto', 'chrome')) {
    $candidates += @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    )
}

$browserExe = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $browserExe) {
    throw '未找到 Edge/Chrome。可安装后重试，或用 -Browser edge / chrome 指定。'
}

$authority = $uri.GetLeftPart([System.UriPartial]::Authority)
$path = if ([string]::IsNullOrWhiteSpace($uri.AbsolutePath)) { '/' } else { $uri.AbsolutePath }
$target = "$authority$path"
if ($uri.Query) {
    $target = "$target$($uri.Query)&audioInput=browser"
} else {
    $target = "$target?audioInput=browser"
}

$profile = Join-Path $env:TEMP 'suspect-interrogation-lan-browser-profile'
New-Item -ItemType Directory -Force -Path $profile | Out-Null

$args = @(
    "--user-data-dir=$profile",
    "--unsafely-treat-insecure-origin-as-secure=$authority",
    '--new-window',
    $target
)

Write-Host "LAN browser microphone test origin: $authority"
Write-Host '浏览器打开后，请在地址栏左侧站点权限中允许“麦克风”。'
Write-Host '此模式不会创建公网入口，也不会使用 FRP。'
Start-Process -FilePath $browserExe -ArgumentList $args
