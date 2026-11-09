$ErrorActionPreference = 'Stop'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
$outputDirectory = Join-Path $PSScriptRoot '../build'
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
$output = Join-Path $outputDirectory 'DiagnosticsTests.exe'
$sources = @('BootstrapCore.cs', 'Payload.cs', 'WindowsIntegration.cs', 'Program.cs', 'OperationController.cs', 'Diagnostics.cs', 'DiagnosticsTests.cs') | ForEach-Object { Join-Path $PSScriptRoot $_ }
& $compiler /nologo /langversion:5 /target:exe /platform:x64 /main:CompanyNetwork.DiagnosticsTests ('/out:' + $output) /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.ServiceProcess.dll /reference:System.Web.Extensions.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll @sources
if ($LASTEXITCODE -ne 0) { throw '诊断测试编译失败。' }
& $output
if ($LASTEXITCODE -ne 0) { throw '诊断测试失败。' }
