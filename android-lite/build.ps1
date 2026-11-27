param(
    [switch]$Install,
    [string]$Serial = "",
    [string]$Token = "",
    [string]$Keystore = "",
    [string]$KeystorePassword = "",
    [string]$BuildToolsVersion = "34.0.0",
    [string]$Platform = "android-35"
)

# Build the optional HomeMonitor Lite WebView viewer.
#
# The APK is signed with a local keystore that is created on first build and
# must never be committed. The generated password is stored next to it in
# keystore.password (also ignored by git). Delete both only when you intend to
# publish a new Android application identity.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $root
$sdk = Join-Path $env:LOCALAPPDATA "Android\Sdk"
$buildTools = Join-Path $sdk "build-tools\$BuildToolsVersion"
$androidJar = Join-Path $sdk "platforms\$Platform\android.jar"
$build = Join-Path $root "build"
$dist = Join-Path $repo "dist"
$apk = Join-Path $dist "HomeMonitorLite.apk"
if (-not $Keystore) { $Keystore = Join-Path $root "keystore.jks" }
$passwordFile = Join-Path $root "keystore.password"

foreach ($tool in @("aapt2.exe", "aapt.exe", "zipalign.exe", "apksigner.bat", "d8.bat")) {
    if (-not (Test-Path (Join-Path $buildTools $tool))) {
        throw "Missing $tool in $buildTools. Install Android build-tools $BuildToolsVersion."
    }
}
if (-not (Test-Path $androidJar)) {
    throw "Missing android.jar at $androidJar. Install Android platform $Platform."
}

if (Test-Path $build) { Remove-Item -Recurse -Force $build }
New-Item -ItemType Directory -Force -Path $build | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $build "gen") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $build "classes") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $build "dex") | Out-Null
New-Item -ItemType Directory -Force -Path $dist | Out-Null

$resZip = Join-Path $build "res.zip"
& (Join-Path $buildTools "aapt2.exe") compile --dir (Join-Path $root "res") -o $resZip
if ($LASTEXITCODE -ne 0) { throw "aapt2 compile failed" }

$unsigned = Join-Path $build "app-unsigned.apk"
& (Join-Path $buildTools "aapt2.exe") link `
    -o $unsigned `
    -I $androidJar `
    --manifest (Join-Path $root "AndroidManifest.xml") `
    --java (Join-Path $build "gen") `
    --min-sdk-version 21 `
    --target-sdk-version 25 `
    --version-code 1 `
    --version-name 1.0 `
    $resZip
if ($LASTEXITCODE -ne 0) { throw "aapt2 link failed" }

$rJava = Join-Path $build "gen\com\homemonitor\lite\R.java"
$mainJava = Join-Path $root "src\com\homemonitor\lite\MainActivity.java"
& javac -source 1.8 -target 1.8 -bootclasspath $androidJar -classpath $androidJar `
    -d (Join-Path $build "classes") $rJava $mainJava
if ($LASTEXITCODE -ne 0) { throw "javac failed" }

$classFiles = Get-ChildItem (Join-Path $build "classes") -Recurse -Filter *.class |
    ForEach-Object { $_.FullName }
$d8Args = @(
    "--lib", $androidJar,
    "--min-api", "21",
    "--output", (Join-Path $build "dex")
) + $classFiles
& (Join-Path $buildTools "d8.bat") @d8Args
if ($LASTEXITCODE -ne 0) { throw "d8 failed" }

Push-Location (Join-Path $build "dex")
try {
    & (Join-Path $buildTools "aapt.exe") add $unsigned classes.dex
    if ($LASTEXITCODE -ne 0) { throw "aapt add failed" }
} finally {
    Pop-Location
}

$aligned = Join-Path $build "app-aligned.apk"
& (Join-Path $buildTools "zipalign.exe") -f 4 $unsigned $aligned
if ($LASTEXITCODE -ne 0) { throw "zipalign failed" }

if (Test-Path $Keystore) {
    if (-not $KeystorePassword -and (Test-Path $passwordFile)) {
        $KeystorePassword = (Get-Content $passwordFile -Raw).Trim()
    }
    if (-not $KeystorePassword) {
        throw "The keystore exists but its password is unknown. Pass -KeystorePassword or restore $passwordFile."
    }
} else {
    if (-not $KeystorePassword) {
        $bytes = New-Object byte[] 24
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $KeystorePassword = [Convert]::ToBase64String($bytes)
        Set-Content -Path $passwordFile -Value $KeystorePassword -Encoding ASCII
        Write-Host "Created a local signing password in $passwordFile (do not commit it)." -ForegroundColor Yellow
    }
    & keytool -genkeypair -v `
        -keystore $Keystore `
        -storetype JKS `
        -storepass $KeystorePassword `
        -keypass $KeystorePassword `
        -alias homemonitor `
        -keyalg RSA `
        -keysize 2048 `
        -validity 10000 `
        -dname "CN=HomeMonitor Lite, OU=Local, O=HomeMonitor, L=Local, ST=Local, C=US"
    if ($LASTEXITCODE -ne 0) { throw "keytool failed" }
}

& (Join-Path $buildTools "apksigner.bat") sign `
    --ks $Keystore `
    --ks-key-alias homemonitor `
    --ks-pass "pass:$KeystorePassword" `
    --key-pass "pass:$KeystorePassword" `
    --out $apk $aligned
if ($LASTEXITCODE -ne 0) { throw "apksigner failed" }

& (Join-Path $buildTools "apksigner.bat") verify --verbose $apk
if ($LASTEXITCODE -ne 0) { throw "apksigner verify failed" }

$hash = (Get-FileHash $apk -Algorithm SHA256).Hash
$size = (Get-Item $apk).Length
Write-Output ""
Write-Output "Built $apk"
Write-Output "Size   $size bytes"
Write-Output "SHA256 $hash"

if ($Install) {
    if (-not $Serial) {
        $ready = @(& adb devices | Select-String -Pattern "\sdevice$" | ForEach-Object { ($_ -split "\s+")[0] })
        if ($ready.Count -eq 1) {
            $Serial = $ready[0]
        } elseif ($ready.Count -eq 0) {
            throw "No Android device is connected. Enable USB debugging and run 'adb devices'."
        } else {
            throw "More than one device is connected. Pass -Serial from 'adb devices'."
        }
    }
    & adb -s $Serial install -r $apk
    if ($LASTEXITCODE -ne 0) { throw "adb install failed" }
    & adb -s $Serial shell am force-stop com.homemonitor.lite
    if ($Token) {
        Write-Host "Passing the admin token through the launch intent." -ForegroundColor Yellow
        & adb -s $Serial shell am start -n com.homemonitor.lite/.MainActivity --es token $Token
    } else {
        & adb -s $Serial shell am start -n com.homemonitor.lite/.MainActivity
    }
    if ($LASTEXITCODE -ne 0) { throw "adb start failed" }
    Write-Output "Launched HomeMonitor Lite"
}
