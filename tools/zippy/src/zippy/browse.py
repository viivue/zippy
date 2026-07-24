"""Native file/folder picker via tkinter (stdlib), for browsing local paths.

zippy runs on the user's own machine and works with file *paths*, not
uploads, so this is the only way the browser-based UI can reach the
filesystem without the user typing a path by hand. If tkinter isn't
available, `available()` returns False and the frontend falls back to a
plain text input.
"""

from __future__ import annotations

import threading

try:
    import tkinter as tk
    from tkinter import filedialog

    _TKINTER_AVAILABLE = True
except ImportError:
    _TKINTER_AVAILABLE = False

_dialog_lock = threading.Lock()


def available() -> bool:
    return _TKINTER_AVAILABLE


def browse(mode: str, filetypes: list[tuple[str, str]] | None = None) -> str | None:
    """Open a native file or folder picker. Returns the chosen path, or None if cancelled.

    mode: "file" or "folder". Raises RuntimeError if tkinter is unavailable.
    Dialog calls are serialized — only one can be open at a time.
    """
    if not _TKINTER_AVAILABLE:
        raise RuntimeError("tkinter is not available on this system")

    with _dialog_lock:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            if mode == "folder":
                path = filedialog.askdirectory(parent=root)
            else:
                kwargs: dict = {"parent": root}
                if filetypes:
                    kwargs["filetypes"] = [*filetypes, ("All files", "*.*")]
                path = filedialog.askopenfilename(**kwargs)
        finally:
            root.destroy()

    return path or None
