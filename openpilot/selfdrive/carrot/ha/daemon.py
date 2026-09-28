#!/usr/bin/env python3
"""Openpilot Process Manager entrypoint for Carrot HA daemon."""
from __future__ import annotations
import os
import signal
import sys
import time


def main():
    try:
        from openpilot.selfdrive.carrot.ha.collector import main as collector_main
    except (ImportError, ValueError):
        from collector import main as collector_main

    collector_main()


if __name__ == '__main__':
    main()
