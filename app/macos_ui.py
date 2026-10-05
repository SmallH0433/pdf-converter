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


def configure_liquid_glass_window(window, sidebar) -> bool:
    """Attach system-managed macOS material behind the Qt sidebar.

    ``NSVisualEffectMaterialSidebar`` adopts Liquid Glass on macOS 27 and also
    follows accessibility settings such as Reduce Transparency.  Keeping this
    in a guarded helper makes tests and non-macOS builds independent of PyObjC.
    """
    if not IS_MACOS:
        return False

    try:
        import AppKit
        import objc

        native_window_view = objc.objc_object(
            c_void_p=ctypes.c_void_p(int(window.winId())))
        native_sidebar_view = objc.objc_object(
            c_void_p=ctypes.c_void_p(int(sidebar.winId())))
        native_window = native_window_view.window()
        if native_window is None:
            return False

        native_window.setStyleMask_(
            native_window.styleMask()
            | AppKit.NSWindowStyleMaskFullSizeContentView)
        native_window.setTitlebarAppearsTransparent_(True)
        native_window.setToolbarStyle_(AppKit.NSWindowToolbarStyleUnified)
        native_window.setOpaque_(False)
        native_window.setBackgroundColor_(AppKit.NSColor.clearColor())

        effect = AppKit.NSVisualEffectView.alloc().initWithFrame_(
            native_sidebar_view.bounds())
        effect.setMaterial_(AppKit.NSVisualEffectMaterialSidebar)
        effect.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        effect.setState_(AppKit.NSVisualEffectStateFollowsWindowActiveState)
        effect.setAutoresizingMask_(
            AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        native_sidebar_view.addSubview_positioned_relativeTo_(
            effect, AppKit.NSWindowBelow, None)

        # PyObjC normally retains subviews through AppKit.  Keep an explicit
        # Python reference too so this stays reliable in a frozen application.
        window._macos_material_views = [effect]
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
