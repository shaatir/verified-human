#!/usr/bin/env python3
"""Verified-Human Local Web server launcher.

Uses standard Python libraries to host the interactive glassmorphism dashboard
locally at http://localhost:8000 with zero external dependencies.
"""

import os
import sys
import http.server
import socketserver

# Configurations
PORT = 8000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    """Custom request handler that serves files from the designated 'web' directory."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def log_message(self, format, *args):
        """Silences verbose terminal connection logging for cleaner CLI experience."""
        # Clean request auditing logs instead of dumping spam
        sys.stdout.write(f"  [Server Request] {format % args}\n")

def main():
    print("╓────────────────────────────────────────────────────────╖")
    print("║ 🛡️  VERIFIED-HUMAN DETECTOR - INTERACTIVE WEB SERVER    ║")
    print("╙────────────────────────────────────────────────────────╜")
    print(f"  📂 Local Path: {WEB_DIR}")
    
    if not os.path.exists(WEB_DIR) or not os.path.exists(os.path.join(WEB_DIR, "index.html")):
        print(f"  ❌ Error: Web folder or index.html missing at: {WEB_DIR}")
        sys.exit(1)

    # Bind TCPServer
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("", PORT), CustomHandler) as httpd:
            print(f"  🚀 Live Server Status: {CustomHandler.protocol_version}")
            print(f"  🔗 Local URL: \033[96m\033[1mhttp://localhost:{PORT}\033[0m")
            print("  🛑 Press Ctrl+C to terminate server at any time.")
            print("─" * 58)
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n  🛡️  Server terminated gracefully. Exiting...")
    except Exception as e:
        print(f"\n  ❌ Server execution error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
