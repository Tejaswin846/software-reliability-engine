from __future__ import annotations

import json
import os
import platform
import sys
import urllib.error
import urllib.request


def main() -> None:
    api_url = os.getenv("SOFTWARE_API_URL", "http://127.0.0.1:8300").rstrip("/")
    payload = {
        "source": "sdk_install_ping",
        "sdk_version": "0.1.0",
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "project_name": os.getenv("SOFTWARE_PROJECT_NAME"),
        "metadata": {
            "executable": sys.executable,
        },
    }
    request = urllib.request.Request(
        f"{api_url}/api/analytics/sdk-installation",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error:
        raise SystemExit(f"Software SDK installation ping failed: {error}") from error
    if not body.get("ok"):
        raise SystemExit(f"Software SDK installation ping rejected: {body}")
    print("Software SDK installation recorded.")


if __name__ == "__main__":
    main()
