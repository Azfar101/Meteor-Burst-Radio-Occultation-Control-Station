"""
MBC Ground Control System — launcher.

    python run.py            # starts the server and opens the browser
    python run.py --no-open  # just start the server

Requires: fastapi, uvicorn, numpy, netCDF4, python-multipart
(install with: pip install fastapi uvicorn numpy netCDF4 python-multipart)
"""

import sys
import threading
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = 8600


def open_browser():
    webbrowser.open(f"http://{HOST}:{PORT}")


if __name__ == "__main__":
    if "--no-open" not in sys.argv:
        threading.Timer(1.5, open_browser).start()
    print(f"\n  MBC Ground Control System  ->  http://{HOST}:{PORT}\n")
    uvicorn.run("backend.app:app", host=HOST, port=PORT, log_level="info")
