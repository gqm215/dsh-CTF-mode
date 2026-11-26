param(
  [Parameter(Mandatory=$true)][int]$ProcId,
  [string]$Action = 'shot',
  [int]$X = 0,
  [int]$Y = 0,
  [string]$Text = ''
)
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class BU {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowThreadProcessId(IntPtr h, out int pid);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr a, int x, int y, int cx, int cy, uint f);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("shcore.dll")] public static extern int SetProcessDpiAwareness(int v);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern bool SetFocus(IntPtr h);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  public static IntPtr FindMain(int pid) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((h, l) => { int p; GetWindowThreadProcessId(h, out p);
      if (p != pid) return true;
      var c = new StringBuilder(128); GetClassName(h, c, 128);
      var t = new StringBuilder(512); GetWindowText(h, t, 512);
      if (c.ToString() == "SunAwtFrame" && t.ToString().StartsWith("Burp Suite")) {
        RECT r; GetWindowRect(h, out r);
        if ((r.Right - r.Left) > 400) { found = h; return false; }
      }
      return true; }, IntPtr.Zero);
    return found;
  }
  public static void Click(int x, int y) {
    SetCursorPos(x, y);
    System.Threading.Thread.Sleep(120);
    mouse_event(0x0002, 0, 0, 0, UIntPtr.Zero); // down
    System.Threading.Thread.Sleep(60);
    mouse_event(0x0004, 0, 0, 0, UIntPtr.Zero); // up
  }
}
"@
try { [BU]::SetProcessDpiAwareness(2) | Out-Null } catch { }
[BU]::SetProcessDPIAware() | Out-Null
Start-Sleep -Milliseconds 200
$h = [BU]::FindMain($ProcId)
if ($h -eq 0) { "no main window for pid $ProcId"; exit 1 }
[BU]::ShowWindow($h, 9) | Out-Null
Start-Sleep -Milliseconds 500
[BU]::SetWindowPos($h, [IntPtr]::new(-1), 0,0,0,0, 0x0003) | Out-Null
Start-Sleep -Milliseconds 400
[BU]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 700
$r = New-Object BU+RECT
[BU]::GetWindowRect($h, [ref]$r) | Out-Null
$w=[int]($r.Right-$r.Left); $ht=[int]($r.Bottom-$r.Top)
"hwnd=$h rect=$($r.Left),$($r.Top) ${w}x${ht}"

switch ($Action) {
  'shot' {
    $bmp = New-Object System.Drawing.Bitmap $w, $ht
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($r.Left, $r.Top, 0, 0, $bmp.Size)
    $out = "D:\CTF\_review\burp-$ProcId.png"
    $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
    "shot: $out"
    $g.Dispose(); $bmp.Dispose()
  }
  'click' {
    $ax = $r.Left + $X; $ay = $r.Top + $Y
    "click rel=($X,$Y) abs=($ax,$ay)"
    [BU]::Click($ax, $ay)
    Start-Sleep -Milliseconds 900
    "clicked"
  }
  'type' {
    [System.Windows.Forms.SendKeys]::SendWait($Text)
    Start-Sleep -Milliseconds 700
    "typed: $Text"
  }
}


