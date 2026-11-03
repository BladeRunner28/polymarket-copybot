#!/usr/bin/env python3
"""Negative control for fee_exit.self_test(): restore the OLD defect and prove it FAILS.

The bug was `exit fee := entry fee`. Here every law call is pinned to the entry price,
which is exactly that defect. If self_test() still returns 0, the self-test cannot detect
the class it exists for and the sibling test fails.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import lib.fee_exit as m  # noqa: E402

m.LAWS["pp"] = lambda price: m.pp(0.57)   # every fee priced as if at the entry price
raise SystemExit(m.self_test())
