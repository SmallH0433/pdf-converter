"""macOS-only application appearance helpers.

The Windows and Linux builds continue to use QFluentWidgets' defaults.  On
macOS we retain the existing controls, but let Qt use the platform system font
and native focus behavior so the application feels at home beside AppKit apps.
"""
from __future__ import annotations

import platform

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication


IS_MACOS = platform.system() == "Darwin"


def configure_application(app: QApplication) -> None:
    """Apply settings that should only affect the macOS build."""
    if not IS_MACOS:
        return
    app.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont))
    app.setEffectEnabled(Qt.UIEffect.UI_AnimateCombo, True)


# Imported lazily above in configure_application's module to keep this helper
# harmless on platforms whose Qt plugins expose a smaller set of UI effects.
from PySide6.QtCore import Qt  # noqa: E402  (intentional late import)
