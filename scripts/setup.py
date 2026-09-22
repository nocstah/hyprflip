#!/usr/bin/env python3
"""Prefer OmaCards when enabled; otherwise use the detected card menu."""
import os
import subprocess
import sys

from workflow import main as menu_main, omarchy_running


def main():
    arguments = sys.argv[1:]
    if '--legacy' in arguments:
        sys.argv.remove('--legacy')
        return menu_main()
    page = 'edit' if arguments == ['--cards'] else 'library' if arguments == ['--launch'] else None
    if page and os.environ.get('HYPRFLIP_MENU', 'auto').strip().lower() in ('', 'auto'):
        available = omarchy_running()
        if not available:
            return menu_main(omarchy_available=False)
        try:
            result = subprocess.run(['omarchy-shell', 'omacards', 'open', page], capture_output=True,
                                    text=True, timeout=3, env=os.environ | {'OMARCHY_SHELL_IPC_TIMEOUT': '2s'})
            if result.returncode == 0 and result.stdout.strip() == 'ok':
                return 0
        except (OSError, subprocess.TimeoutExpired):
            pass
        return menu_main(omarchy_available=True)
    return menu_main()


if __name__ == '__main__':
    raise SystemExit(main())
