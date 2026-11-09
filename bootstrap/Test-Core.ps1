$ErrorActionPreference = 'Stop'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
$output = Join-Path $PSScriptRoot 'BootstrapCoreTests.exe'
& $compiler /nologo /langversion:5 /target:exe /platform:x64 ('/out:' + $output) `
    (Join-Path $PSScriptRoot 'BootstrapCore.cs') (Join-Path $PSScriptRoot 'BootstrapCoreTests.cs')
if ($LASTEXITCODE -ne 0) { throw ('测试编译失败，退出码 ' + $LASTEXITCODE) }
& $output
if ($LASTEXITCODE -ne 0) { throw ('测试失败，退出码 ' + $LASTEXITCODE) }
