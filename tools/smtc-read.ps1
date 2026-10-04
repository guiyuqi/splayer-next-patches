# 读取 Windows 系统媒体控件（SMTC）当前会话的曲目信息
#
# 用法： powershell.exe -NoProfile -ExecutionPolicy Bypass -File <本文件>
# 说明：SMTC 元数据由播放器通过 media-ctrl 原生模块写入，用它验证 setMetadata 是否真的生效
Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null
# 曲目名多为日文：强制 UTF-8 输出，避免 CP936 转码后对不上
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
  })[0]

function Await($WinRtTask, $ResultType) {
  $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
  $netTask = $asTask.Invoke($null, @($WinRtTask))
  $netTask.Wait(-1) | Out-Null
  $netTask.Result
}

$mgr = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
$manager = Await ($mgr::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
$session = $manager.GetCurrentSession()
if (-not $session) {
  Write-Output "NO_SESSION"
  exit 0
}

$props = Await ($session.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
$playback = $session.GetPlaybackInfo()
Write-Output ("SOURCE={0}" -f $session.SourceAppUserModelId)
Write-Output ("STATUS={0}" -f $playback.PlaybackStatus)
Write-Output ("TITLE={0}" -f $props.Title)
Write-Output ("ARTIST={0}" -f $props.Artist)
Write-Output ("ALBUM={0}" -f $props.AlbumTitle)
Write-Output ("THUMBNAIL={0}" -f $(if ($props.Thumbnail) { "yes" } else { "no" }))
