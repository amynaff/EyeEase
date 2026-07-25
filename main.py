from app_ui import TapZapLiteApp
from tray import run_tray


def main():
    app = TapZapLiteApp()
    app.protocol("WM_DELETE_WINDOW", app.withdraw)  # closing the panel just hides it
    run_tray(app)
    app.mainloop()


if __name__ == "__main__":
    main()
