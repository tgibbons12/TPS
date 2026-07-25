"""
ENGINEFAILPROC.py — STUB / PLACEHOLDER

Not the real module — see SPEEDOTHER.py's docstring for context. This stub
exists only to let takeoff_perf_core.py import and run end-to-end.

Confirmed call site (takeoff_perf_core.py, generate_tps):
    get_airport_specific_altitudes(origin_icao, max_elevation)
Confirmed usage of the result — every one of the four call sites checks
`if airport_altitudes` or uses `.get(...)` with a default before touching
it, never bare indexing. Returning None here is safe: it will just skip
the "AIRPORT NOTES" EFP section and E/O ACCEL lines in the generated TPS
rather than crash.

Expected dict keys when present, inferred from usage: 'EFP', 'eo_acc'
"""


def get_airport_specific_altitudes(icao, elevation):
    return None
