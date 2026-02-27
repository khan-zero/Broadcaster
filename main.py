import sys
import tkinter as tk
import tkinter.messagebox
import logging
from src.ui.app import App

if __name__ == "__main__":
    app = None
    try:
        app = App()
        app.report_callback_exception = app.handle_exception
        app.mainloop()
    except Exception as e:
        logging.error(f"Critical Startup Error: {e}", exc_info=True)
        
        # Fallback error message if UI fails to start
        root = tk.Tk()
        root.withdraw()
        tkinter.messagebox.showerror(
            "Critical Error",
            f"Application failed to start.\n\n{e}\n\nCheck error_log.txt for details."
        )
        root.destroy()
