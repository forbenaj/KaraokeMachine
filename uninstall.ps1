$hostName = "com.dkaraoke.downloader"
$registryPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$hostName"

if (Test-Path $registryPath) {
  Remove-Item -Path $registryPath -Force
  Write-Host "Removed native host: $hostName"
} else {
  Write-Host "Native host is not registered."
}
