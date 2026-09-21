"""Keep native dialogs on Tk's main thread, including on macOS."""
import queue
import sys
import threading
from pathlib import Path


class FolderPicker:
    def __init__(self):
        import tkinter
        self.root = tkinter.Tk()
        self.root.withdraw()
        self.requests = queue.Queue()
        self.root.after(100, self.poll)

    def choose(self, title: str) -> str:
        done = threading.Event()
        result = []
        self.requests.put((title, done, result))
        done.wait()
        if isinstance(result[0], Exception):
            raise result[0]
        return result[0]

    def show_dialog(self, title: str) -> str:
        from tkinter import filedialog
        options = {"title": title, "initialdir": str(Path.home()), "mustexist": True}
        if sys.platform == "win32":
            from tkinter import Toplevel
            # A withdrawn root cannot reliably bring a native dialog above
            # the browser. Give it a mapped, temporary topmost owner instead.
            owner = Toplevel(self.root)
            try:
                owner.withdraw()
                owner.title(title)
                owner.geometry(f"1x1+{self.root.winfo_screenwidth() // 2}+{self.root.winfo_screenheight() // 2}")
                owner.attributes("-alpha", 0.0)
                owner.attributes("-toolwindow", True)
                owner.attributes("-topmost", True)
                owner.deiconify()
                owner.update_idletasks()
                owner.lift()
                owner.focus_force()
                return filedialog.askdirectory(master=self.root, parent=owner, **options)
            finally:
                # Also release the owner after cancellation or dialog errors.
                owner.destroy()
        if sys.platform != "darwin":
            options["parent"] = self.root
        # On macOS, -parent creates an immovable sheet attached to our hidden
        # root. Omit it so Cocoa positions a standalone, movable open panel.
        # master chooses the Tcl interpreter without passing -parent to Tk.
        return filedialog.askdirectory(master=self.root, **options)

    def poll(self):
        try:
            title, done, result = self.requests.get_nowait()
        except queue.Empty:
            pass
        else:
            try:
                result.append(self.show_dialog(title))
            except Exception as exc:
                result.append(exc)
            finally:
                done.set()
        self.root.after(100, self.poll)
