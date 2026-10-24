"""Run 4B Imaging without starting FastAPI or connecting to a database."""

import argparse
import json
from pathlib import Path
import sys


def core_self_test(destination):
    import numpy as np
    from .volume import demonstration, load_series
    catalog = demonstration()
    loaded = load_series(catalog.series[0])
    assert loaded.voxels.shape == (64, 64, 64)
    assert np.isfinite(loaded.voxels).all()
    assert loaded.completeness == "not_established"
    report = {"core_self_test": "passed", "synthetic_only": True, "report": loaded.report()}
    Path(destination).write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test-core", type=Path, help="Generated data only; write a bounded test report and exit.")
    parser.add_argument("--smoke-ui", type=Path, help="Generated data only; capture real Qt/VTK smoke artifacts.")
    args = parser.parse_args()
    if args.self_test_core:
        core_self_test(args.self_test_core)
        return 0
    from PySide6 import QtCore, QtWidgets
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts)
    from .gui import MainWindow, STYLE
    application = QtWidgets.QApplication(sys.argv[:1])
    application.setApplicationName("4B Imaging")
    application.setLayoutDirection(QtCore.Qt.RightToLeft)
    application.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    window.view.widget.Initialize()
    if args.smoke_ui:
        from .smoke import check_ui
        try:
            check_ui(application, window, args.smoke_ui)
            return 0
        finally:
            window.close()
            application.processEvents()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
