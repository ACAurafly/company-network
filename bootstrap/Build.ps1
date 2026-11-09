param(
    [Parameter(Mandatory = $true)][string]$PayloadZipPath,
    [string]$OutputPath = (Join-Path $PSScriptRoot 'CompanyNetwork.exe')
)
$ErrorActionPreference = 'Stop'
$payload = (Resolve-Path -LiteralPath $PayloadZipPath).Path
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw '需要 .NET Framework 4.8 的 64 位 C# 编译器。' }
$output = [System.IO.Path]::GetFullPath($OutputPath)
$arguments = @(
    '/nologo', '/langversion:5', '/target:winexe', '/platform:x64', '/optimize+',
    ('/out:' + $output),
    ('/win32icon:' + (Join-Path $PSScriptRoot 'CompanyNetwork.ico')),
    ('/win32manifest:' + (Join-Path $PSScriptRoot 'CompanyNetwork.manifest')),
    ('/resource:' + $payload + ',company.payload.zip'),
    '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
    '/reference:System.ServiceProcess.dll', '/reference:System.Web.Extensions.dll',
    '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
    (Join-Path $PSScriptRoot 'BootstrapCore.cs'), (Join-Path $PSScriptRoot 'Payload.cs'),
    (Join-Path $PSScriptRoot 'WindowsIntegration.cs'), (Join-Path $PSScriptRoot 'Program.cs'), (Join-Path $PSScriptRoot 'OperationController.cs')
)
& $compiler @arguments
if ($LASTEXITCODE -ne 0) { throw ('编译失败，退出码 ' + $LASTEXITCODE) }
Get-Item -LiteralPath $output | Select-Object FullName, Length
