# -*- coding: utf-8 -*-
"""Rewrite test/fixtures/format_dialect_golden.txt from the current evaluator.

Only run this when a dialect change is intended. The golden file is the
compatibility contract for format strings; regenerating it to make a test
pass would erase the thing the test is for.

    python -m test.regen_format_golden
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'src'))

from test.test_format_dialect import CASES, GOLDEN, _cases, _render  # noqa: E402

if __name__ == '__main__':
    lines = [f'{fmt}\n  -> {_render(fmt)}' for fmt in _cases()]
    with open(GOLDEN, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')
    print(f'{len(lines)} cases written to {os.path.relpath(GOLDEN)}')
