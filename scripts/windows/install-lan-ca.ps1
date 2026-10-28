param(
    [string]$Origin = "https://192.168.0.9:18080"
)

$ErrorActionPreference = "Stop"

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Administrator)) {
    throw "请以管理员身份运行 PowerShell，以便将局域网 CA 安装到 LocalMachine Trusted Root。"
}

$originUri = [Uri]$Origin
if ($originUri.Scheme -ne "https") {
    throw "Origin 必须使用 https://"
}
$curlBypass = @("--noproxy", $originUri.Host)

$tempDir = Join-Path $env:TEMP "suspect-interrogation-lan-ca"
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
$caPath = Join-Path $tempDir "suspect-interrogation-lan-ca.crt"

Write-Host "[1/4] 下载公开 LAN CA（仅此引导请求临时跳过证书校验）..."
& curl.exe @curlBypass -k --fail --silent --show-error "$($Origin.TrimEnd('/'))/api/v1/tls/ca.crt" -o $caPath
if ($LASTEXITCODE -ne 0) { throw "下载 LAN CA 失败。" }

$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($caPath)
Write-Host "[2/4] CA Subject: $($cert.Subject)"
Write-Host "      SHA-256: $($cert.GetCertHashString([Security.Cryptography.HashAlgorithmName]::SHA256))"

Write-Host "[3/4] 导入 LocalMachine Trusted Root..."
& certutil.exe -addstore -f Root $caPath | Out-Host
if ($LASTEXITCODE -ne 0) { throw "导入 Windows Trusted Root 失败。" }

$trusted = Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Thumbprint -eq $cert.Thumbprint }
if (-not $trusted) { throw "CA 导入后未在 LocalMachine Root 中找到。" }

Write-Host "[4/4] 使用严格 HTTPS 验证服务..."
& curl.exe @curlBypass --ssl-no-revoke --fail --silent --show-error "$($Origin.TrimEnd('/'))/health/live" | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Windows 已安装 CA，但严格 HTTPS 验证失败。" }

Write-Host "完成。请关闭旧的特殊参数浏览器窗口，再用普通 Edge/Chrome 打开：$Origin"
