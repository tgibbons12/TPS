"""
SPEEDOTHER.py — STUB / PLACEHOLDER

This is NOT the real module. The actual SPEEDOTHER.py (with real N1/EPR
performance tables) was not available during the Flask migration and must
be copied in from the original TAKEOFF_PERF.py project before this app
produces correct thrust/speed data.

This stub exists only so takeoff_perf_core.py can be imported and its
control flow exercised end-to-end (e.g. to test the Flask routes). Every
call site of get_speed_other() and get_reduced_thrust_n1() in
takeoff_perf_core.py already handles a falsy/None return defensively
(confirmed by reading each usage — they check `if speed_other_data`,
`.get(...)` with defaults, etc.), so returning None here is safe: it will
NOT crash generate_tps(), it will just leave N1/EPR fields as "XXX"
placeholders in the generated output.

Real signatures required, inferred from call sites in takeoff_perf_core.py:
    get_speed_other(icaocode, oat=None, altitude=None, weight=None,
                     assumed_temp=None, thrust_rating=None) -> dict | None
        Expected dict keys when present: 'n1', 'n1_pack_off', 'epr'
    get_reduced_thrust_n1(icaocode, thrust_rating, assumed_temp, altitude) -> dict | None
        Expected dict keys when present: 'n1'
"""


def get_speed_other(icaocode, oat=None, altitude=None, weight=None,
                     assumed_temp=None, thrust_rating=None):
    return None


def get_reduced_thrust_n1(icaocode, thrust_rating, assumed_temp, altitude):
    return None
