#!/usr/bin/env python3
"""Openpilot Process Manager entrypoint for Carrot HA services."""
from __future__ import annotations

import threading


def main():
  try:
    from openpilot.selfdrive.carrot.ha.collector import main as collector_main
    from openpilot.selfdrive.carrot.ha.terminal import run_in_thread as terminal_main
  except (ImportError, ValueError):
    from collector import main as collector_main
    from terminal import run_in_thread as terminal_main

  threading.Thread(target=terminal_main, daemon=True, name="CarrotHATerminal").start()
  collector_main()


if __name__ == "__main__":
  main()
