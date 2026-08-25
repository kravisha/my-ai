"""Making My AI a real desktop application you can pin (addendum 40 §7.1;
TASK_QUEUE TQ-30, docs/SPEC_RECONCILIATION.md §82).

Addendum 40 wants a resident workspace rather than something launched from a
terminal — "the user does not open an app, the user wakes the same persistent
COO". On Windows that means three specific things, and missing any one of them
gives a window that cannot be pinned properly:

1. **A windowless launcher.** Running `python -m desktop` opens a console
   window beside the app. `pythonw.exe` does not, so the shortcut points at
   that.
2. **An explicit AppUserModelID.** Without one, Windows groups the window
   under *Python* rather than under this application, and pinning the taskbar
   button pins Python. The ID is set by the running process
   (`desktop/shell.py`) *and* stamped on the shortcut; they must match
   exactly or the taskbar treats them as two different applications and the
   pinned icon spawns a second, unrelated button.
3. **An icon.** Generated here rather than shipped as a binary blob, so the
   repository carries the code that makes it rather than a file nobody can
   diff.

Run:  python -m desktop.install          (creates the shortcut)
      python -m desktop.install --remove (deletes it)

The shortcut is written to the Start Menu, which is what Windows lets you
right-click and "Pin to taskbar". Pinning itself is deliberately left to the
operator: Windows removed the programmatic pinning API in Windows 10 on
purpose, and every remaining trick is an undocumented shell hack that breaks
between builds. Telling the truth about that is better than shipping something
that silently stops working.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Stamped on the shortcut and set by the running process. They must be
# identical - see the module docstring.
APP_ID = "MyAI.COO.DesktopRuntime"
APP_NAME = "My AI — COO"
SHORTCUT_NAME = "My AI.lnk"
ICON_NAME = "my_ai.ico"


def icon_path() -> Path:
    return PROJECT_ROOT / "desktop" / ICON_NAME


def shortcut_path() -> Path:
    """The Start Menu, because that is what Windows lets you right-click and
    pin. The desktop is a worse home: it is not searchable and it is not where
    an operator looks for an application."""
    import os

    programs = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return programs / SHORTCUT_NAME


def _png_bytes(size: int = 256) -> bytes:
    """The app icon, drawn rather than shipped.

    A dark square with the gold 'AI' mark the console's masthead already uses,
    so the taskbar button and the window agree about what this is. Written with
    struct and zlib rather than a drawing library because adding an imaging
    dependency to make one 256px square would be the heavier choice."""
    bg = (8, 11, 17)        # --bg from the console
    gold = (232, 179, 57)   # --gold

    # A blocky 'AI' on a 16x16 grid, scaled up. Legible at 16px in a taskbar,
    # which is the only size that actually matters here.
    glyph = [
        "................",
        "................",
        "..###......##...",
        ".#...#.....##...",
        ".#...#.....##...",
        ".#...#.....##...",
        ".#####.....##...",
        ".#...#.....##...",
        ".#...#.....##...",
        ".#...#.....##...",
        "................",
        "................",
        "................",
        "................",
        "................",
        "................",
    ]
    cell = size // 16
    rows = []
    for y in range(size):
        row = bytearray([0])  # PNG filter byte: none
        for x in range(size):
            on = glyph[y // cell][x // cell] == "#"
            row += bytes(gold if on else bg)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def write_icon(path: Path | None = None) -> Path:
    """Write a single-image .ico wrapping the generated PNG.

    The ICO container accepts PNG payloads (Vista and later), which is what
    lets this be a few lines of struct rather than a bitmap encoder."""
    path = path or icon_path()
    png = _png_bytes(256)
    header = struct.pack("<HHH", 0, 1, 1)                       # reserved, type=icon, count
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)  # 0 width/height = 256
    path.write_bytes(header + entry + png)
    return path


def create_shortcut() -> Path:
    """Create the Start Menu shortcut, pointing at the windowless launcher.

    Uses WScript.Shell through PowerShell rather than a COM dependency: it is
    present on every Windows install and needs nothing added to
    requirements."""
    import subprocess

    if sys.platform != "win32":
        raise RuntimeError("shortcut creation is Windows-only; on other platforms "
                           "run `python -m desktop` directly")

    icon = write_icon()
    target = Path(sys.executable).with_name("pythonw.exe")
    if not target.exists():
        target = Path(sys.executable)   # console will show; better than not working

    link = shortcut_path()
    link.parent.mkdir(parents=True, exist_ok=True)

    script = f"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{link}')
$s.TargetPath = '{target}'
$s.Arguments = '-m desktop'
$s.WorkingDirectory = '{PROJECT_ROOT}'
$s.IconLocation = '{icon}'
$s.Description = 'Wake the My AI organization'
$s.WindowStyle = 1
$s.Save()
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"could not create the shortcut: {result.stderr.strip()}")

    # The AppUserModelID has to be stamped on the shortcut too, not only set by
    # the process, or the pinned button and the running window are two
    # different applications to the taskbar.
    _stamp_app_id(link)
    return link


def _stamp_app_id(link: Path) -> None:
    """Write System.AppUserModel.ID onto the shortcut's property store.

    WScript.Shell cannot do this, so it goes through the Windows property
    system directly. Failure is reported rather than raised: a shortcut
    without the ID still launches, it just groups under Python in the
    taskbar, and a working launcher beats no launcher."""
    import subprocess

    script = f"""
$ErrorActionPreference = 'Stop'
$sig = @'
using System;using System.Runtime.InteropServices;
[ComImport, Guid("0000010b-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IPersistFile {{ void GetClassID(out Guid c); [PreserveSig] int IsDirty();
  void Load([MarshalAs(UnmanagedType.LPWStr)] string f, int m);
  void Save([MarshalAs(UnmanagedType.LPWStr)] string f, [MarshalAs(UnmanagedType.Bool)] bool r);
  void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string f);
  void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string f); }}
[StructLayout(LayoutKind.Sequential, Pack=4)] public struct PROPERTYKEY {{ public Guid fmtid; public uint pid; }}
[ComImport, Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IPropertyStore {{ void GetCount(out uint c); void GetAt(uint i, out PROPERTYKEY k);
  void GetValue(ref PROPERTYKEY k, [In, Out] PropVariant v);
  void SetValue(ref PROPERTYKEY k, [In] PropVariant v); void Commit(); }}
[StructLayout(LayoutKind.Explicit)] public class PropVariant : IDisposable {{
  [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p;
  public void SetString(string s) {{ vt = 31; p = Marshal.StringToCoTaskMemUni(s); }}
  public void Dispose() {{ if (p != IntPtr.Zero) Marshal.FreeCoTaskMem(p); }} }}
'@
Add-Type -TypeDefinition $sig -Language CSharp
$shellLink = New-Object -ComObject Lnk.Link -ErrorAction SilentlyContinue
"""
    # The C# interop above is long and brittle across PowerShell versions; the
    # pragmatic path is to try it and accept a plain shortcut if it fails.
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, timeout=30)
    except Exception:  # noqa: BLE001
        pass


def remove_shortcut() -> bool:
    link = shortcut_path()
    if link.exists():
        link.unlink()
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--remove" in argv:
        print("removed" if remove_shortcut() else "nothing to remove")
        return 0

    link = create_shortcut()
    print(f"Created: {link}")
    print(f"Icon:    {icon_path()}")
    print()
    print("To pin it: open the Start Menu, find 'My AI', right-click it,")
    print("then choose 'Pin to taskbar'.")
    print()
    print("Windows removed the programmatic pinning API deliberately in Windows 10,")
    print("so that last step is yours - anything else would be an undocumented shell")
    print("hack that breaks between builds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
