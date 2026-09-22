#!/usr/bin/env python3
"""Open OmaCards when enabled, with the original menus as a fallback."""
import os
import subprocess
import sys

from workflow import main as menu_main


def main():
    arguments = sys.argv[1:]
    if '--legacy' in arguments:
        sys.argv.remove('--legacy')
        return menu_main()
    page = 'edit' if arguments == ['--cards'] else 'library' if arguments == ['--launch'] else None
    if page:
        try:
            result = subprocess.run(['omarchy-shell', 'omacards', 'open', page], capture_output=True,
                                    text=True, timeout=3, env=os.environ | {'OMARCHY_SHELL_IPC_TIMEOUT': '2s'})
            if result.returncode == 0 and result.stdout.strip() == 'ok':
                return 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    return menu_main()


if __name__ == '__main__':
    raise SystemExit(main())
