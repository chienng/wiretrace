"""Replace oversized bodies before mitmproxy writes a HAR.

`mitmdump -n -r flows.mitm -s addons/har_guard.py --set hardump=…` replays each
saved flow through every addon hook. `-s` scripts run before mitmproxy's own
savehar (incident 2026-10-14), so these hooks trim the flow first and the HAR
is built from the trimmed copy.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cli.bodies import HAR_LIMIT, trim_oversized  # noqa: E402


class HarGuard:
    def response(self, flow) -> None:
        trim_oversized(flow, HAR_LIMIT)

    def error(self, flow) -> None:
        trim_oversized(flow, HAR_LIMIT)

    def websocket_end(self, flow) -> None:
        trim_oversized(flow, HAR_LIMIT)


addons = [HarGuard()]
