import argparse
import sys

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QDialog

from app import autostart, config, db
from app.odoo_client import OdooClient
from app.ui import theme
from app.ui.setup_wizard import SetupWizard


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minimized", action="store_true")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # keep running while minimized to tray
    theme.apply_theme(app)

    conn = db.connect()

    cfg = config.load_config()
    password = config.get_password(cfg.odoo_username) if cfg else None

    if not cfg or not password:
        wizard = SetupWizard(conn)
        if wizard.exec() != QDialog.DialogCode.Accepted:
            return 0
        cfg = config.load_config()
        password = config.get_password(cfg.odoo_username)

    # Re-sync the Windows registry entry with the saved preference on every
    # launch so it self-heals if the exe was reinstalled to a new path.
    autostart.set_enabled(cfg.ui.autostart_enabled)

    client = OdooClient(cfg.odoo_url, cfg.odoo_db, cfg.odoo_username, password)

    from app.ui.main_window import MainWindow  # local import: only needed once config/db are ready

    window = MainWindow(conn=conn, client=client)
    if not args.minimized:
        window.show()

    exit_code = app.exec()
    QThreadPool.globalInstance().waitForDone(5000)  # let in-flight RPC workers finish before teardown
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
