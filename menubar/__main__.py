"""Menu bar process: ``python -m menubar PID PORT STATUS_PATH [--app]``, token on stdin.

``--app``: the session was started from Wiretrace.app; see :func:`menubar.render`.

The token is the first line of stdin and is not in argv or the environment.
Exits 2, with one line on stderr, when AppKit is missing or there is no window
server (an SSH session). ``--check`` does only that and exits.
"""

from __future__ import annotations

import os
import signal
import sys
import time
import webbrowser
from pathlib import Path

from menubar import (
    CHECK_ARGV, ICON_HEIGHT_PT, ICON_PATH, LIVE, read_status, render, row_text, stop_effect, window_url,
)

APP_ARGV = "--app"
USAGE = "usage: python -m menubar PID PORT STATUS_PATH [--app]"
PYOBJC_MISSING = "PyObjC not installed (run scripts/setup-mac.sh)"
NO_WINDOW_SERVER = "no window server"


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(2)


def load_appkit():
    try:
        import AppKit
        from PyObjCTools import AppHelper
    except ImportError:
        fail(PYOBJC_MISSING)
    return AppKit, AppHelper


def window_server(appkit) -> bool:
    try:
        app = appkit.NSApplication.sharedApplication()
        app.setActivationPolicy_(appkit.NSApplicationActivationPolicyAccessory)
        appkit.NSStatusBar.systemStatusBar()
    except Exception:
        return False
    return True


def check() -> int:
    appkit, _helper = load_appkit()
    if not window_server(appkit):
        fail(NO_WINDOW_SERVER)
    return 0


def load_icon(appkit):
    """The Wiretrace icon as a template image, so macOS tints it for a light or dark menu bar. None if missing."""
    image = appkit.NSImage.alloc().initWithContentsOfFile_(str(ICON_PATH))
    if image is None:
        return None
    size = image.size()
    if size.height <= 0:
        return None
    image.setSize_((size.width * ICON_HEIGHT_PT / size.height, ICON_HEIGHT_PT))
    image.setTemplate_(True)
    image.setAccessibilityDescription_("Wiretrace")
    return image


def read_token() -> str:
    token = sys.stdin.readline().rstrip("\n")
    try:
        sys.stdin.close()
    except OSError:
        pass
    return token


class Bar:
    """The status item. Plain Python: PyObjC would treat its methods as Objective-C."""

    def __init__(self, appkit, helper, controller, launcher: int, port: int, path: Path, token: str,
                 app: bool = False) -> None:
        self.appkit = appkit
        self.helper = helper
        self.controller = controller
        self.launcher = launcher
        self.port = port
        self.path = path
        self.token = token
        self.app = app
        self.signalled = False
        self.stopping = False
        self.seen = False
        self.menu_open = False
        self.view = render(None, time.time(), False, app=app)
        bar = appkit.NSStatusBar.systemStatusBar()
        self.item = bar.statusItemWithLength_(appkit.NSVariableStatusItemLength)
        button = self.item.button()
        icon = load_icon(appkit)
        self.has_icon = button is not None and icon is not None
        if self.has_icon:
            button.setImage_(icon)
            button.setImagePosition_(appkit.NSImageLeft)
            button.setToolTip_("Wiretrace")
        self.menu = None
        self.apply(rebuild=True)

    def tick(self) -> None:
        if os.getppid() != self.launcher:
            self.helper.stopEventLoop()
            return
        self.refresh(rebuild=not self.menu_open)

    def open_window(self, flow_id: str | None) -> None:
        if os.getppid() != self.launcher:
            self.helper.stopEventLoop()
            return
        # new=2 asks for a new tab. The macOS opener writes the URL to
        # osascript's stdin, so the token is not on a command line.
        webbrowser.open(window_url(self.port, self.token, flow_id), new=2)

    def show_last_error(self) -> None:
        if not any(row.action == "last_error" and row.enabled for row in self.view.rows):
            return
        self.open_window(self.view.last_error)

    def stop_session(self) -> None:
        effect = stop_effect(os.getppid(), self.launcher, self.signalled)
        if effect == "exit":
            self.helper.stopEventLoop()
            return
        if effect != "signal":
            return
        self.signalled = True
        self.stopping = True
        self.refresh(rebuild=True)
        try:
            os.kill(self.launcher, signal.SIGINT)
        except OSError:
            self.helper.stopEventLoop()

    def quit(self) -> None:
        self.helper.stopEventLoop()

    def refresh(self, rebuild: bool) -> None:
        status = read_status(self.path)
        if status is not None:
            self.seen = True
        self.view = render(status, time.time(), self.stopping, seen=self.seen, app=self.app)
        self.apply(rebuild=rebuild)

    def apply(self, rebuild: bool) -> None:
        button = self.item.button()
        if button is not None:
            button.setTitle_(self.view.badge if self.has_icon else self.view.title)
            # Dimmed unless recording: the icon looks the same while starting.
            button.setAppearsDisabled_(self.view.state != LIVE)
        if not rebuild:
            return
        menu = self.appkit.NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)
        menu.setDelegate_(self.controller)
        actions = {
            "open": "openWindow:",
            "last_error": "showLastError:",
            "stop": "stopSession:",
            "quit": "quitItem:",
        }
        for row in self.view.rows:
            if row.kind == "separator":
                menu.addItem_(self.appkit.NSMenuItem.separatorItem())
                continue
            selector = actions.get(row.action)
            item = self.appkit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                row_text(row), selector, row.shortcut if selector else "")
            if selector:
                item.setTarget_(self.controller)
                item.setEnabled_(row.enabled)
            if row.alert:
                red = self.appkit.NSAttributedString.alloc().initWithString_attributes_(
                    row_text(row),
                    {self.appkit.NSForegroundColorAttributeName: self.appkit.NSColor.systemRedColor()},
                )
                item.setAttributedTitle_(red)
            menu.addItem_(item)
        self.menu = menu
        self.item.setMenu_(menu)


def _define_controller(appkit):
    import objc

    class Controller(appkit.NSObject):
        def init(self):
            self = objc.super(Controller, self).init()
            if self is None:
                return None
            self.bar = None
            return self

        def tick_(self, _timer) -> None:
            self.bar.tick()

        def openWindow_(self, _sender) -> None:
            self.bar.open_window(None)

        def showLastError_(self, _sender) -> None:
            self.bar.show_last_error()

        def stopSession_(self, _sender) -> None:
            self.bar.stop_session()

        def quitItem_(self, _sender) -> None:
            self.bar.quit()

        def menuWillOpen_(self, _menu) -> None:
            self.bar.menu_open = True

        def menuDidClose_(self, _menu) -> None:
            self.bar.menu_open = False
            self.bar.refresh(rebuild=True)

    return Controller


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == [CHECK_ARGV]:
        return check()
    app = args[3:] == [APP_ARGV]
    if app:
        args = args[:3]
    if len(args) != 3:
        fail(USAGE)
    try:
        launcher_pid, port = int(args[0]), int(args[1])
    except ValueError:
        fail(USAGE)
    status_path = Path(args[2])
    token = read_token()
    appkit, app_helper = load_appkit()
    if not window_server(appkit):
        fail(NO_WINDOW_SERVER)
    controller = _define_controller(appkit).alloc().init()
    controller.bar = Bar(appkit, app_helper, controller, launcher_pid, port, status_path, token, app=app)
    appkit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        1.0, controller, "tick:", None, True)
    controller.tick_(None)
    app_helper.runEventLoop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
