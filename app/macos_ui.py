"""macOS-only application appearance helpers.

The Windows and Linux builds continue to use QFluentWidgets' defaults.  On
macOS the Qt window is bridged to AppKit so macOS 27 can render its current
sidebar material and unified titlebar.  Older supported macOS releases keep
working because the bridge only uses long-standing AppKit material APIs.
"""
from __future__ import annotations

import ctypes
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


def configure_liquid_glass_window(window, _sidebar) -> bool:
    """Configure the native unified titlebar used by the macOS shell.

    The sidebar itself is painted by Qt.  Embedding an ``NSVisualEffectView``
    next to Qt's backing store can cover Qt child widgets in a frozen app, so
    the stable cross-build solution keeps native material at window chrome and
    uses system-matched colors for the navigation layer.
    """
    if not IS_MACOS:
        return False

    try:
        import AppKit
        import objc

        native_window_view = objc.objc_object(
            c_void_p=ctypes.c_void_p(int(window.winId())))
        native_window = native_window_view.window()
        if native_window is None:
            return False

        native_window.setStyleMask_(
            native_window.styleMask()
            | AppKit.NSWindowStyleMaskFullSizeContentView)
        # Keep the traffic-light/title region on the native window material.
        # A clear NSWindow background makes that entire strip show the desktop
        # through it on macOS 27, which is not the intended Liquid Glass layer.
        native_window.setTitlebarAppearsTransparent_(False)
        native_window.setToolbarStyle_(AppKit.NSWindowToolbarStyleUnified)
        native_window.setOpaque_(True)
        native_window.setBackgroundColor_(AppKit.NSColor.windowBackgroundColor())

        window._macos_material_views = []
        window.setProperty("macLiquidGlassActive", True)
        return True
    except Exception:  # noqa: BLE001 - native bridge must always fail closed
        # The Qt fallback stylesheet remains usable on unsupported hosts and in
        # the offscreen test platform.
        window.setProperty("macLiquidGlassActive", False)
        return False


# Imported lazily above in configure_application's module to keep this helper
# harmless on platforms whose Qt plugins expose a smaller set of UI effects.
from PySide6.QtCore import Qt  # noqa: E402  (intentional late import)
