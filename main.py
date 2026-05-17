from __future__ import annotations

import sys
from pathlib import Path

from config.config_manager import load_merged_config
from core.acquisition_controller import AcquisitionController
from gui.main_window import MainWindow


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "PySide6 未安装，请先执行: python -m pip install -r requirements.txt"
        ) from exc

    app = QApplication(sys.argv)
    root = Path(__file__).resolve().parent
    config_path = root / "config" / "default_config.yaml"
    user_config_path = root / "config" / "user_config.yaml"
    config = load_merged_config(config_path, user_config_path)
    controller = AcquisitionController(config)
    window = MainWindow(controller)

    if config.runtime.auto_start and config.runtime.hide_window_on_auto_start:
        window.showMinimized()
    else:
        window.show()

    if config.runtime.auto_start:
        controller.start_auto_mode()

    exit_code = app.exec()
    controller.shutdown()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
