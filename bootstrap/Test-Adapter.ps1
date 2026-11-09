$ErrorActionPreference = 'Stop'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
$output = Join-Path $PSScriptRoot 'AdapterSetupTests.exe'
$arguments = @(
    '/nologo', '/langversion:5', '/target:exe', '/platform:x64',
    '/main:CompanyNetwork.AdapterSetupTests', ('/out:' + $output),
    '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
    '/reference:System.ServiceProcess.dll', '/reference:System.Web.Extensions.dll',
    '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
    (Join-Path $PSScriptRoot 'BootstrapCore.cs'), (Join-Path $PSScriptRoot 'Payload.cs'),
    (Join-Path $PSScriptRoot 'WindowsIntegration.cs'), (Join-Path $PSScriptRoot 'Program.cs'), (Join-Path $PSScriptRoot 'OperationController.cs'), (Join-Path $PSScriptRoot 'Diagnostics.cs'),
    (Join-Path $PSScriptRoot 'AdapterSetupTests.cs')
)
& $compiler @arguments
if ($LASTEXITCODE -ne 0) { throw '网卡流程测试编译失败。' }
& $output
if ($LASTEXITCODE -ne 0) { throw '网卡流程测试失败。' }
