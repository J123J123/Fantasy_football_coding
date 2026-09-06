"""Shared numerical conventions; unavailable inputs remain unavailable."""
import math
import pandas as pd
from .processor import records, complete_sum

NAN = float('nan')


def ratio(a, b):
    return a / b if pd.notna(a) and pd.notna(b) and b != 0 else NAN


def win(a, b):
    if pd.isna(a) or pd.isna(b): return NAN
    return 1. if a > b else .5 if a == b else 0.


def total(values):
    return complete_sum(pd.Series(list(values), dtype=float))


def section(table, description, **extra):
    return {'description': description, 'rows': records(table), **extra}


def ranked(frame, column, ascending=False):
    frame['rank'] = frame[column].rank(method='min', ascending=ascending)
    return frame
