param(
    [Parameter(Mandatory = $true)][string]$Action,
    [string]$EncodedPayload = ""
)

$ErrorActionPreference = "Stop"
$decoded = if ($EncodedPayload) { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($EncodedPayload)) } else { "{}" }
$input = $decoded | ConvertFrom-Json

function Out-Json($obj) {
    $obj | ConvertTo-Json -Depth 6 -Compress
}

# ── 截屏：全虚拟屏幕 → PNG base64 ──
function Invoke-Screenshot {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $vs = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $bmp = New-Object System.Drawing.Bitmap $vs.Width, $vs.Height
    try {
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.CopyFromScreen($vs.Left, $vs.Top, 0, 0, $bmp.Size)
        $ms = New-Object System.IO.MemoryStream
        $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
        return @{ ok = $true; result = @{ base64 = [Convert]::ToBase64String($ms.ToArray()); mime = "image/png"; width = $vs.Width; height = $vs.Height } }
    } finally {
        if ($g) { $g.Dispose() }
        if ($bmp) { $bmp.Dispose() }
    }
}

# ── 键鼠注入（user32 P/Invoke，SendInput UNICODE 输入）──
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class CuaNative {
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [StructLayout(LayoutKind.Sequential)]
    public struct INPUT { public uint type; public InputUnion U; }
    [StructLayout(LayoutKind.Explicit)]
    public struct InputUnion { [FieldOffset(0)] public KEYBDINPUT ki; [FieldOffset(0)] public MOUSEINPUT mi; }
    [StructLayout(LayoutKind.Sequential)]
    public struct KEYBDINPUT { public uint wVk; public uint wScan; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
    [StructLayout(LayoutKind.Sequential)]
    public struct MOUSEINPUT { public int dx; public int dy; public uint mouseData; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
    public const uint INPUT_MOUSE = 0; public const uint INPUT_KEYBOARD = 1;
    public const uint KEYEVENTF_KEYUP = 0x0002; public const uint KEYEVENTF_UNICODE = 0x0004;
    public const uint MOUSEEVENTF_WHEEL = 0x0800; public const uint MOUSEEVENTF_LEFTDOWN = 0x0002; public const uint MOUSEEVENTF_LEFTUP = 0x0004;
    public const uint MOUSEEVENTF_RIGHTDOWN = 0x0008; public const uint MOUSEEVENTF_RIGHTUP = 0x0010; public const uint MOUSEEVENTF_MIDDLEDOWN = 0x0020; public const uint MOUSEEVENTF_MIDDLEUP = 0x0040;
    public static void SendKeyInput(uint vk, uint scan, uint flags) {
        var inputs = new INPUT[1];
        inputs[0].type = INPUT_KEYBOARD;
        inputs[0].U.ki.wVk = vk; inputs[0].U.ki.wScan = scan; inputs[0].U.ki.dwFlags = flags;
        SendInput(1, inputs, Marshal.SizeOf(typeof(INPUT)));
    }
    [DllImport("user32.dll")] public static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);
    [DllImport("user32.dll")] public static extern uint MapVirtualKey(uint uCode, uint uMapType);
}
"@

function Send-UnicodeText([string]$text) {
    foreach ($ch in $text.ToCharArray()) {
        $code = [int]$ch
        $down = 0; $up = 0
        if ($code -ge 0xD800 -and $code -le 0xDBFF) { $down = 0x0001 }  # high surrogate: no KEYUP
        if ($code -ge 0xDC00 -and $code -le 0xDFFF) { $up = 0x0002 }    # low surrogate: no KEYDOWN
        $flags = 0x0004 -bor $down -bor $up
        [CuaNative]::SendKeyInput(0, $code, $flags)
        if ($down -eq 0 -and $up -eq 0) { [CuaNative]::SendKeyInput(0, $code, 0x0004 -bor 0x0002) }
    }
}

function Send-KeyChord([string]$chord) {
    # "ctrl+shift+t" / "enter" / "win+r" → SendInput vk 序列（按住修饰键 → 点主键 → 松开）
    $vkMap = @{
        enter = 0x0D; tab = 0x09; esc = 0x1B; escape = 0x1B; space = 0x20; backspace = 0x08; delete = 0x2E; del = 0x2E
        insert = 0x2D; home = 0x24; end = 0x23; pageup = 0x21; pagedown = 0x22
        left = 0x25; up = 0x26; right = 0x27; down = 0x28
        ctrl = 0x11; control = 0x11; alt = 0x12; shift = 0x10; win = 0x5B; super = 0x5B
        a = 0x41; b = 0x42; c = 0x43; d = 0x44; e = 0x45; f = 0x46; g = 0x47; h = 0x48; i = 0x49; j = 0x4A
        k = 0x4B; l = 0x4C; m = 0x4D; n = 0x4E; o = 0x4F; p = 0x50; q = 0x51; r = 0x52; s = 0x53; t = 0x54
        u = 0x55; v = 0x56; w = 0x57; x = 0x58; y = 0x59; z = 0x5A
        f1 = 0x70; f2 = 0x71; f3 = 0x72; f4 = 0x73; f5 = 0x74; f6 = 0x75; f7 = 0x76; f8 = 0x77; f9 = 0x78; f10 = 0x79; f11 = 0x7A; f12 = 0x7B
        0 = 0x30; 1 = 0x31; 2 = 0x32; 3 = 0x33; 4 = 0x34; 5 = 0x35; 6 = 0x36; 7 = 0x37; 8 = 0x38; 9 = 0x39
    }
    $parts = $chord.ToLower().Split("+") | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    $vks = @()
    foreach ($p in $parts) {
        if ($vkMap.ContainsKey($p)) { $vks += [uint32]$vkMap[$p] }
        elseif ($p.Length -eq 1) { $vks += [uint32][char]::ToUpper($p[0]) }
    }
    if ($vks.Count -eq 0) { throw "unknown key chord: $chord" }
    foreach ($vk in $vks) {
        if ($vk -ge 0x30) { [CuaNative]::SendKeyInput(0, $vk, 0) } else { [CuaNative]::SendKeyInput($vk, 0, 0) }
    }
    [array]::Reverse($vks)
    foreach ($vk in $vks) {
        if ($vk -ge 0x30) { [CuaNative]::SendKeyInput(0, $vk, 0x0002) } else { [CuaNative]::SendKeyInput($vk, 0, 0x0002) }
    }
}

# ── 动作分发 ──
switch ($Action) {
    "screenshot" { Out-Json (Invoke-Screenshot) }
    "get_app_state" {
        $shot = Invoke-Screenshot
        Out-Json @{ ok = $true; result = @{ base64 = $shot.result.base64; mime = $shot.result.mime; kind = "visual_only" } }
    }
    "list_apps" {
        $apps = Get-Process | Where-Object { $_.MainWindowTitle } | ForEach-Object {
            @{ pid = $_.Id; name = $_.ProcessName; title = $_.MainWindowTitle }
        }
        Out-Json @{ ok = $true; result = @{ apps = $apps } }
    }
    "left_click" {
        $x = [int]$input.x; $y = [int]$input.y
        [CuaNative]::SetCursorPos($x, $y)
        Start-Sleep -Milliseconds 60
        switch ($input.button) {
            "right" { [CuaNative]::mouse_event(0x0008, 0, 0, 0, [UIntPtr]::Zero); [CuaNative]::mouse_event(0x0010, 0, 0, 0, [UIntPtr]::Zero) }
            "middle" { [CuaNative]::mouse_event(0x0020, 0, 0, 0, [UIntPtr]::Zero); [CuaNative]::mouse_event(0x0040, 0, 0, 0, [UIntPtr]::Zero) }
            default { [CuaNative]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero); [CuaNative]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero) }
        }
        Out-Json @{ ok = $true; result = @{ action_sent = $true } }
    }
    "double_click" {
        $x = [int]$input.x; $y = [int]$input.y
        [CuaNative]::SetCursorPos($x, $y)
        Start-Sleep -Milliseconds 60
        foreach ($i in 1..2) {
            [CuaNative]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero); [CuaNative]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
            if ($i -eq 1) { Start-Sleep -Milliseconds 90 }
        }
        Out-Json @{ ok = $true; result = @{ action_sent = $true } }
    }
    "scroll" {
        $amount = if ($input.amount) { [int]$input.amount } else { 3 }
        $dir = if ($input.direction) { $input.direction.ToLower() } else { "down" }
        $delta = if ($dir -eq "up") { 240 } else { -240 }
        foreach ($i in 1..$amount) { [CuaNative]::mouse_event(0x0800, 0, 0, [uint32]($delta -band 0xFFFFFFFF), [UIntPtr]::Zero); Start-Sleep -Milliseconds 60 }
        Out-Json @{ ok = $true; result = @{ action_sent = $true } }
    }
    "type" { Send-UnicodeText ([string]$input.text); Out-Json @{ ok = $true; result = @{ action_sent = $true } } }
    "key" { Send-KeyChord ([string]$input.text); Out-Json @{ ok = $true; result = @{ action_sent = $true } } }
    "request_access" { Out-Json @{ ok = $true; result = @{ granted = $true } } }
    "stop_computer_control" { Out-Json @{ ok = $true; result = @{ stopped = $true } } }
    "set_value" { Out-Json @{ ok = $false; error = @{ code = "not_settable"; message = "v1 视觉模式不支持 set_value（无 UIA 树），请用 click + type" } } }
    default { Out-Json @{ ok = $false; error = @{ code = "action_unavailable"; message = "CUA v1 不支持动作: $Action" } } }
}
