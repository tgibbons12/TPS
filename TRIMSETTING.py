"""
TRIMSETTING.py — STUB / PLACEHOLDER

Not the real module — see SPEEDOTHER.py's docstring for context. This stub
exists only to let takeoff_perf_core.py import and run end-to-end.

Confirmed call site (takeoff_perf_core.py, both generate_tps and
generate_closeout): get_trim_setting(icaocode, cg_percent)
Confirmed usage of the result: trim_data['trim'] if trim_data else ''
  — only one indexing site in the whole file, and it's already guarded,
  so returning None here is safe. It will leave STAB blank in the
  generated closeout/TPS output rather than crash.
"""


def get_trim_setting(icaocode, cg_percent):
    return None
