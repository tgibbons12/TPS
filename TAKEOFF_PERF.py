"""
TAKEOFF_PERF.py — Railway/headless version
All tkinter dialogs replaced with environment variable inputs.
Populated automatically by the PyLauncher web app launch dialog.

Flight data inputs (set by launch dialog):
  SIMBRIEF_USER     SimBrief username
  PAX_COUNT         Passenger count (int)
  CARGO             Cargo weight in lbs (int)
  PLAN_RAMP         Planned ramp fuel in lbs (int)
  CG_PERCENT        CG % MAC (float, e.g. 25.0)
  ZFW_OVERRIDE      (optional) Manual ZFW override in lbs (int)

Runway selection (set by launch dialog Runway tab):
  RUNWAY_ID         Runway identifier, e.g. "09" or "27"
  RWY_FLAPS         Flap/CONF setting
  RWY_V1            V1 speed
  RWY_VR            VR speed
  RWY_V2            V2 speed
  RWY_THR           Thrust setting / derate
  RWY_FLEX          Flex / assumed temperature
  RWY_LENGTH        Runway length in ft
  RWY_BLEED         Bleed/APU setting (ON/OFF)
  RWY_MAX_WEIGHT    Max takeoff weight (×1000 lbs)
  RWY_LIMIT_CODE    Performance limit code
  RWY_ASDR          Accelerate-stop distance required
  RWY_HD            Headwind component in knots

App config:
  OUTPUTS_DIR       Base output directory (default: ./outputs)
  OUTPUT_SUBFOLDER  Optional subfolder, e.g. "KEYW_0313" → outputs/KEYW_0313/
  AIRCRAFT_TYPE     ICAO aircraft type (default: B738)
"""

import xml.etree.ElementTree as ET
import json
import random
import pytz
import urllib.request
import urllib.error
import ssl
import os
import textwrap
from datetime import datetime

from SPEEDOTHER import get_speed_other, get_reduced_thrust_n1
from TRIMSETTING import get_trim_setting
from ENGINEFAILPROC import get_airport_specific_altitudes

# ── Config ────────────────────────────────────────────────────────────────────
REVISION_FILE = "takeoff_perf_revisions.json"
_base_outputs = os.environ.get("OUTPUTS_DIR", "outputs")
_subfolder    = os.environ.get("OUTPUT_SUBFOLDER", "").strip()
OUTPUTS_DIR   = os.path.join(_base_outputs, _subfolder) if _subfolder else _base_outputs
os.makedirs(OUTPUTS_DIR, exist_ok=True)
if _subfolder:
    print(f"✓ Output folder: {OUTPUTS_DIR}")


def safe_float(value, default=0.0):
    try:
        return float(value) if value else default
    except (ValueError, TypeError):
        return default


def safe_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def get_next_revision(flight_number, origin, date):
    flight_key = f"{flight_number}_{origin}_{date}"
    revisions = {}
    if os.path.exists(REVISION_FILE):
        try:
            with open(REVISION_FILE, 'r') as f:
                revisions = json.load(f)
        except Exception as e:
            print(f"Error reading revisions: {e}")
    current_revision = revisions.get(flight_key, 0)
    revisions[flight_key] = current_revision + 1
    try:
        with open(REVISION_FILE, 'w') as f:
            json.dump(revisions, f, indent=2)
    except Exception as e:
        print(f"Error saving revisions: {e}")
    return current_revision


def fetch_xml_from_api(username):
    url = f"https://www.simbrief.com/api/xml.fetcher.php?username={username}"
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(url, context=context) as response:
            return ET.parse(response)
    except urllib.error.URLError as e:
        print(f"Error fetching data: {e}")
        return None
    except ET.ParseError as e:
        print(f"Error parsing XML: {e}")
        return None


def is_valid_runway(runway):
    try:
        float(runway.findtext('max_weight', '0') or '0')
        return True
    except ValueError:
        return False


def calculate_cargo_distribution(total_cargo):
    cargo_per_section = round(total_cargo / 2 / 200) * 200
    fwd_cargo = cargo_per_section + random.choice([-200, 0, 200])
    aft_cargo = total_cargo - fwd_cargo
    return fwd_cargo, aft_cargo


def get_utc_time():
    return datetime.now(pytz.UTC).strftime('%H:%M UTC')


def extract_text(xml_root, tag, default=None):
    elem = xml_root.find(tag)
    if elem is not None and elem.text is not None:
        return elem.text.strip()
    return default


def get_text(parent, tag, default="XXX"):
    elem = parent.find(tag) if parent is not None else None
    return elem.text.strip() if elem is not None and elem.text else default


# ── Main parse ────────────────────────────────────────────────────────────────

def parse_all_flight_data_from_xml(xml_root, date, aircraft_type):

    def _get(parent, tag, default='0'):
        el = parent.find(tag) if parent is not None else None
        return el.text.strip() if el is not None and el.text else default

    general     = xml_root.find('general')
    fuel        = xml_root.find('fuel')
    weights     = xml_root.find('weights')
    destination = xml_root.find('destination')
    alternate   = xml_root.find('alternate')
    aircraft    = xml_root.find('aircraft')
    conditions  = xml_root.find('conditions')

    # SimBrief baseline values
    pax_count_actual = safe_int(_get(weights, 'pax_count'))
    pax_weight       = safe_int(_get(weights, 'pax_weight', '180'))
    cargo_actual     = safe_int(_get(weights, 'cargo'))
    plan_ramp_actual = safe_int(_get(fuel,    'plan_ramp'))
    taxi_fuel        = safe_int(_get(fuel,    'taxi'))
    oew              = safe_int(_get(weights, 'oew', '0'))
    enroute_burn     = safe_int(_get(fuel,    'enroute_burn'))
    max_zfw          = safe_int(_get(weights, 'max_zfw'))
    max_tow_struct   = safe_int(_get(weights, 'max_tow_struct'))

    # ── Read user inputs from env vars ────────────────────────────────────────
    pax_count  = safe_int(os.environ.get('PAX_COUNT',  str(pax_count_actual)))
    cargo      = safe_int(os.environ.get('CARGO',      str(cargo_actual)))
    plan_ramp  = safe_int(os.environ.get('PLAN_RAMP',  str(plan_ramp_actual)))
    cg_percent = safe_float(os.environ.get('CG_PERCENT', '25.0'))
    runway_id  = os.environ.get('RUNWAY_ID', '').strip()

    zfw_override_raw = os.environ.get('ZFW_OVERRIDE', '').strip()
    if zfw_override_raw:
        zfw = safe_int(zfw_override_raw)
        zfw_overridden = True
    else:
        zfw = oew + (pax_count * pax_weight) + cargo
        zfw_overridden = False

    print(f"PAX={pax_count}  CARGO={cargo}  RAMP={plan_ramp}  CG={cg_percent}")
    print(f"ZFW={zfw}{'  (OVERRIDE)' if zfw_overridden else ''}")

    # ── Engine anti-ice ───────────────────────────────────────────────────────
    acdata_parsed = xml_root.find('.//api_params/acdata_parsed')
    acdata = json.loads(acdata_parsed.text.strip()) if acdata_parsed is not None else {}
    engine_type = acdata.get('comments', 'UNKNOWN')

    first_runway = xml_root.find('.//tlr/takeoff//runway')
    anti_ice_setting = 'OFF'
    if first_runway is not None:
        ai_elem = first_runway.find('anti_ice_setting')
        if ai_elem is not None and ai_elem.text:
            anti_ice_setting = ai_elem.text.strip().upper()
    anti_ice_on = (anti_ice_setting not in ('OFF', ''))

    surface_condition = _get(conditions, 'surface_condition', 'dry').lower()

    # ── Runway extraction ─────────────────────────────────────────────────────
    valid_runways = []
    for runway in xml_root.findall('.//tlr/takeoff//runway'):
        if not is_valid_runway(runway):
            continue

        def get_val(tag, default='0'):
            elem = runway.find(tag)
            if elem is not None and elem.text is not None:
                return elem.text.strip()
            return default

        try:
            hd_value = float(get_val('headwind_component', '0'))
        except (ValueError, TypeError):
            hd_value = 0.0

        valid_runways.append({
            'id':            get_val('identifier', 'XX'),
            'slope':         get_val('gradient', '0'),
            'flaps':         get_val('flap_setting', ''),
            'v1':            get_val('speeds_v1', '0'),
            'vr':            get_val('speeds_vr', '0'),
            'v2':            get_val('speeds_v2', '0'),
            'thr':           get_val('thrust_setting', 'xxx'),
            'flex':          get_val('flex_temperature', 'XXX'),
            'length':        get_val('length', '0'),
            'bleed':         get_val('bleed_setting', 'ON'),
            'max_weight':    int(float(get_val('max_weight', '0')) / 1000),
            'max_tow_struct': max_tow_struct / 1000,
            'elevation':     float(get_val('elevation', '0')),
            'limit_code':    get_val('limit_code', ''),
            'HD':            hd_value,
        })
        print(f"✓ Runway: {get_val('identifier')}  HD={hd_value}")

    # ── Select runway by env var (or first) ───────────────────────────────────
    selected_runways = list(valid_runways)  # default: all, first is used
    if runway_id:
        match = [r for r in valid_runways if r['id'].upper() == runway_id.upper()]
        if match:
            selected_runways = match
            print(f"✓ Using runway: {runway_id}")
        else:
            print(f"⚠ RUNWAY_ID '{runway_id}' not found; using first available")

    # ── Apply user-edited runway field overrides from launch dialog ───────────
    # RWY_* env vars shadow whatever SimBrief returned, field by field.
    # Only applied to the first (selected) runway so the pilot's edits are used.
    RWY_ENV_MAP = {
        'RUNWAY_ID':      'id',
        'RWY_FLAPS':      'flaps',
        'RWY_V1':         'v1',
        'RWY_VR':         'vr',
        'RWY_V2':         'v2',
        'RWY_THR':        'thr',
        'RWY_FLEX':       'flex',
        'RWY_LENGTH':     'length',
        'RWY_BLEED':      'bleed',
        'RWY_MAX_WEIGHT': 'max_weight',
        'RWY_LIMIT_CODE': 'limit_code',
        'RWY_ASDR':       'asdr',
        'RWY_HD':         'HD',
    }
    if selected_runways:
        # Work on a copy so SimBrief originals are untouched
        edited_rwy = dict(selected_runways[0])
        overrides_applied = []
        for env_key, rwy_field in RWY_ENV_MAP.items():
            val = os.environ.get(env_key, '').strip()
            if not val:
                continue
            # Numeric fields get cast to appropriate type
            if rwy_field in ('v1', 'vr', 'v2', 'length', 'asdr'):
                try:
                    edited_rwy[rwy_field] = int(float(val))
                except (ValueError, TypeError):
                    edited_rwy[rwy_field] = val
            elif rwy_field == 'HD':
                try:
                    edited_rwy[rwy_field] = float(val)
                except (ValueError, TypeError):
                    edited_rwy[rwy_field] = 0.0
            elif rwy_field == 'max_weight':
                try:
                    edited_rwy[rwy_field] = float(val)
                except (ValueError, TypeError):
                    edited_rwy[rwy_field] = val
            else:
                edited_rwy[rwy_field] = val
            overrides_applied.append(f"{rwy_field}={edited_rwy[rwy_field]}")

        if overrides_applied:
            print(f"✓ Runway overrides applied: {', '.join(overrides_applied)}")

        # Replace first runway with edited version
        selected_runways = [edited_rwy] + list(selected_runways[1:])

    print(f"✓ Runways: {', '.join(r['id'] for r in selected_runways)}")

    # ── Weights ───────────────────────────────────────────────────────────────
    takeoff_fuel = plan_ramp - taxi_fuel
    tow = zfw + takeoff_fuel
    ldw = tow - enroute_burn

    max_tow = safe_int(_get(weights, 'max_tow'))
    max_ldw = safe_int(_get(weights, 'max_ldw'))

    zfw_avail = max_zfw - zfw
    tow_avail = max_tow - tow
    ldw_avail = max_ldw - ldw

    # Changes vs SimBrief plan
    zfw_actual = oew + (pax_count_actual * pax_weight) + cargo_actual
    tow_actual = zfw_actual + (plan_ramp_actual - taxi_fuel)

    lap_infants = random.randint(int(pax_count * 0.03), int(pax_count * 0.04))
    fwd_cargo, aft_cargo = calculate_cargo_distribution(cargo)

    crew_section = xml_root.find('crew')
    crew_count = 0
    if crew_section is not None:
        for tag in ['cpt', 'fo', 'fa']:
            crew_count += len(crew_section.findall(tag))
    if crew_count == 0:
        crew_count = 6

    print(f"\n=== CALCULATED WEIGHTS ===")
    print(f"ZFW: {zfw}  TOW: {tow}  LDW: {ldw}")
    print(f"=========================\n")

    origin_element      = xml_root.find('origin')
    destination_element = xml_root.find('destination')
    origin_icao  = _get(origin_element,      'icao_code', 'XXX')
    origin_iata  = _get(origin_element,      'iata_code', 'XXX')
    destination_iata = _get(destination_element, 'iata_code', 'XXX')
    alternate_burn = safe_int(_get(fuel, 'alternate_burn'))
    reserve        = safe_int(_get(fuel, 'reserve'))

    uplink_data = {
        "flight_number":  _get(general, 'flight_number', 'UNKNOWN'),
        "date":           date,
        "ofp_version":    _get(general, 'release', 'UNKNOWN'),
        "origin_icao":    origin_icao,
        "origin_iata":    origin_iata,
        "altn":           _get(alternate, 'icao_code', 'XXX'),
        "destination":    _get(destination_element, 'icao_code', 'XXX'),
        "AC_name":        _get(aircraft, 'name', 'XXX'),
        "coroute":        origin_icao + _get(destination_element, 'icao_code', 'XXX'),
        "aircraft_type":  aircraft_type,
        "registration":   _get(aircraft, 'registration'),
        "icaocode":       _get(aircraft, 'icaocode'),
        "cost_index":     safe_int(_get(general, 'costindex')),
        "cruise_fl":      safe_int(_get(general, 'initial_altitude')) // 100,
        "wind_dir":       safe_int(_get(general, 'avg_wind_dir')),
        "wind_spd":       safe_int(_get(general, 'avg_wind_spd')),
        "wind_component": safe_int(_get(general, 'avg_wind_comp')),
        "trip_distance":  safe_int(_get(general, 'route_distance')),
        "ats_route":      _get(general, 'route', ''),
        "tc_oat":         _get(general, 'avg_temp_dev', 'xx'),
        "taxi_fuel":      taxi_fuel,
        "trip_fuel":      safe_int(_get(fuel, 'enroute_burn')),
        "altn_fuel":      alternate_burn,
        "reserve_fuel":   alternate_burn + reserve,
        "final_reserve":  reserve,
        "block_fuel":     plan_ramp,
        "ptof":           safe_int(_get(fuel, 'plan_takeoff')),
        "mtof":           safe_int(_get(fuel, 'min_takeoff')),
        "ptow":           tow,
        "pzfw":           safe_int(_get(weights, 'est_zfw')),
        "pldw":           ldw,
        "airport":        _get(conditions, 'airport_iata', 'XXXX'),
        "engine":         engine_type,
        "temp":           _get(conditions, 'temperature', '0'),
        "qnh":            _get(conditions, 'altimeter', '0'),
        "wind":           f"{_get(conditions,'wind_direction')}/{_get(conditions,'wind_speed')}",
        "surface":        surface_condition,
    }

    loadsheet_data = {
        "Time Generated":   get_utc_time(),
        "Flight Number":    uplink_data["flight_number"],
        "Ship Number":      _get(aircraft, 'fin', 'UNKNOWN'),
        "origin":           origin_icao,
        "origin_iata":      origin_iata,
        "Destination":      uplink_data["destination"],
        "destination_iata": destination_iata,
        "TOW":              tow,
        "MAX TOW":          max_tow,
        "MAX TOW STRUCT":   max_tow_struct,
        "FOB":              plan_ramp,
        "ZFW":              zfw,
        "OEW":              oew,
        "Passengers":       pax_count,
        "LAP":              lap_infants,
        "FWD Cargo":        fwd_cargo,
        "AFT Cargo":        aft_cargo,
        "Total Cargo":      cargo,
        "ZFW AVAIL":        zfw_avail,
        "TOW AVAIL":        tow_avail,
        "LDW AVAIL":        ldw_avail,
        "PTOW":             safe_int(_get(weights, 'est_tow')),
        "ZFW Change":       zfw - zfw_actual,
        "MAX ZFW":          max_zfw,
        "TOW Change":       tow - tow_actual,
        "PAX Change":       pax_count - pax_count_actual,
        "FUEL Change":      plan_ramp - plan_ramp_actual,
        "CARGO Change":     cargo - cargo_actual,
        "LDW":              ldw,
        "MAX LDW":          max_ldw,
        "Enroute Burn":     enroute_burn,
        "Passenger Weight": pax_weight,
        "Crew Count":       crew_count,
    }

    return uplink_data, loadsheet_data, selected_runways, anti_ice_on, taxi_fuel, cg_percent


# ── Output generator ──────────────────────────────────────────────────────────

def generate_combined_output(loadsheet_data, uplink_data, valid_runways,
                              anti_ice_on, taxi_fuel, output_folder, cg_percent):

    def fmt_1000(val):
        try:
            return f"{val / 1000:.1f}"
        except Exception:
            return "0.0"

    def safe_weight(weight):
        try:
            return float(weight) / 1000.0
        except (ValueError, TypeError):
            return 0.0

    def _safe_int(val):
        try:
            if val is None or val == "":
                return 0
            return int(float(val))
        except Exception:
            return 0

    AIRCRAFT_UI_NAMES = {
        "N123NA": {"name": "A319 CFM",          "engine": "CFM56-5B5"},
        "N456NA": {"name": "A319 CFM SHARKLET",  "engine": "CFM56-5B5/P"},
        "N200NA": {"name": "A320 CFM",           "engine": "CFM56-5B4/P"},
        "N210NA": {"name": "A320 IAE",           "engine": "IAE V2527-A5"},
        "N300NA": {"name": "A320NEO",            "engine": "PW1127G-JM"},
        "N400NA": {"name": "A321 CFM",           "engine": "CFM56-5B3/P"},
        "N724NC": {"name": "A321",               "engine": "IAE SHARKLET"},
        "N500NA": {"name": "A321NEO",            "engine": "PW1133G-JM"},
        "N700NA": {"name": "B737-800",           "engine": "CFM56-7B27"},
        "N800NA": {"name": "B737 MAX 8",         "engine": "CFM LEAP-1B"},
        "N900NA": {"name": "E175",               "engine": "GE CF34-8E"},
    }

    tow     = loadsheet_data.get('TOW', 0)
    zfw     = loadsheet_data.get('ZFW', 0)
    ldw     = loadsheet_data.get('LDW', 0)
    max_tow = loadsheet_data.get('MAX TOW', 0)
    max_zfw = loadsheet_data.get('MAX ZFW', 0)
    max_ldw = loadsheet_data.get('MAX LDW', 0)
    tow_avail = max_tow - tow
    zfw_avail = max_zfw - zfw
    ldw_avail = max_ldw - ldw

    aircraft_reg = loadsheet_data.get('Ship Number', 'N/A')
    if aircraft_reg in AIRCRAFT_UI_NAMES:
        aircraft_display = AIRCRAFT_UI_NAMES[aircraft_reg]["name"]
        engine_type      = AIRCRAFT_UI_NAMES[aircraft_reg]["engine"]
    else:
        aircraft_display = uplink_data.get('AC_name', 'UNKNOWN')
        engine_type      = uplink_data.get('engine', 'UNKNOWN')

    base_filename = (f"{loadsheet_data['Flight Number']}_"
                     f"{uplink_data['origin_icao']}_"
                     f"{datetime.now().strftime('%Y%m%d')}")
    closeout_file = os.path.join(output_folder, f"{base_filename}_CLOSEOUT.txt")
    takeoff_file  = os.path.join(output_folder, f"{base_filename}_TAKEOFF.txt")

    icaocode  = uplink_data.get("icaocode", "XXXX")
    trim_data = get_trim_setting(icaocode, cg_percent)

    revision_number = get_next_revision(
        loadsheet_data['Flight Number'],
        uplink_data['origin_icao'],
        datetime.now().strftime('%Y%m%d')
    )
    print(f"📋 Revision: {revision_number:02d}")

    cg_display = f"{cg_percent:.1f}" if cg_percent is not None else ""

    # ── Fuel variance check ───────────────────────────────────────────────────
    try:
        fuel_change = abs(float(loadsheet_data.get('FUEL Change', 0)))
        if fuel_change > 2000:
            with open(takeoff_file, 'w') as f:
                f.write("**** THIS TPS DOES NOT SATISFY THE ****\n")
                f.write("*** REQUIREMENTS OF A LOAD CLOSEOUT ***\n\n")
                f.write("*** NOTIFICATION MESSAGE ***\n")
                f.write("TAKEOFF DATA REJECTED BY FMC, ACTUAL FUEL\n")
                f.write("ONBOARD DIFFERS FROM PLANNED AND EXCEEDS\n")
                f.write("TOLERANCES. REQUEST TAKEOFF DATA WHEN\n")
                f.write("FUELING IS COMPLETE\n")
                f.write("AUTOMATED FLT OPS MESSAGE\n\n")
            print(f"⚠ FUEL VARIANCE {fuel_change:.0f} LBS — takeoff data rejected")
            return takeoff_file, None
    except (ValueError, TypeError) as e:
        print(f"[DEBUG] Fuel variance check skipped: {e}")

    # ── Takeoff file ──────────────────────────────────────────────────────────
    with open(takeoff_file, 'w') as file:
        file.write("**** THIS TPS DOES NOT SATISFY THE ****\n")
        file.write("*** REQUIREMENTS OF A LOAD CLOSEOUT ***\n\n")

        # Weight margins
        tow_margin = tow_avail - 2000
        zfw_margin = zfw_avail - 1000
        ldw_margin = ldw_avail - 1000
        margins = {"MTOW-S": tow_margin, "MZFW": zfw_margin, "MLDW-L": ldw_margin}
        min_restriction = min(margins, key=margins.get)
        weight_restricted = margins[min_restriction] < 0

        if weight_restricted:
            file.write("****** WEIGHT RESTRICTED FLIGHT ********\n")
            file.write(f"  * LIMITING RESTRICTION -- {min_restriction} *\n")
            file.write("** PLEASE UPDATE ACTUAL FOB IMMEDIATELY**\n")
            file.write("**     AFTER FUELING VIA ACARS        **\n")
            file.write("**     OR CONTACT LOAD AGENT          **\n")
            file.write("****************************************\n\n")

        sta      = uplink_data.get('origin_iata', 'XXXX')
        flt_dte  = uplink_data.get('flight_number', 'ERR')
        airpl    = loadsheet_data.get('Ship Number', 'ERR')
        dte_time = loadsheet_data.get('Time Generated', 'ERR')
        surface  = uplink_data.get('surface', 'dry').upper()
        temp     = uplink_data.get('temp', 'XX')
        alt      = valid_runways[0].get('elevation', 0) if valid_runways else 0

        try:
            qnh = float(uplink_data.get('qnh', 29.92))
        except (ValueError, TypeError):
            qnh = 29.92
        pressure_alt = int(alt + (29.92 - qnh) * 1000)

        date_str   = datetime.now().strftime("%d")
        time_parts = dte_time.replace(' UTC', '').replace(':', '')

        file.write(f"STA  PRES ALT   FLT/DTE   AIRPL   DTE/TIME\n")
        file.write(f"{sta:<4} {pressure_alt:<10} {flt_dte}/{date_str:<6} {airpl:<5}  {date_str}/{time_parts}Z\n\n")

        weight = loadsheet_data.get("TOW", 0)

        # Thrust/speed variable init
        speed_other_data = None
        n1_pack_on = n1_pack_off = reduced_n1 = reduced_n1_pack_off = "XXX"
        epr_max = epr_takeoff = "XXX"
        thrust_label = "N/A"
        reduced_n1_valid = False

        alt_val = 0
        if valid_runways:
            try:
                alt_val = float(valid_runways[0].get('elevation', 0))
            except (ValueError, TypeError):
                alt_val = 0

        is_737_ng    = icaocode in ['B736', 'B737', 'B738', 'B739']
        is_737_max   = icaocode == 'B38M'
        is_boeing_737 = is_737_ng or is_737_max
        is_md83      = icaocode == 'MD83'

        pack_off_adj = 0.8 if alt_val <= 8000 else (0.9 if alt_val <= 9000 else 1.0)

        rwy = valid_runways[0] if valid_runways else {}
        derate_label = rwy.get('thr', '').upper().strip()

        THRUST_TABLE = {
            "B736": {"D-TO": 22, "D-TO1": 20, "D-TO2": 18},
            "B737": {"D-TO": 24, "D-TO1": 22, "D-TO2": 20},
            "B738": {"D-TO": 26, "D-TO1": 24, "D-TO2": 22},
            "B739": {"D-TO": 27, "D-TO1": 25, "D-TO2": 23},
            "B38M": {"TO": 26, "TO1": 24, "TO2": 22},
        }

        if is_boeing_737 and icaocode in THRUST_TABLE:
            key = derate_label.replace("D-", "") if is_737_max else derate_label
            effective_thrust = THRUST_TABLE[icaocode].get(key)
            if effective_thrust is None:
                effective_thrust = list(THRUST_TABLE[icaocode].values())[0]
            thrust_label = key if is_737_max else f"{effective_thrust}K"
        else:
            effective_thrust = None

        if is_md83:
            epr_max_data = get_speed_other(icaocode, oat=temp, altitude=alt_val)
            if epr_max_data and 'epr' in epr_max_data:
                epr_max = epr_max_data['epr']
            flex_temp = rwy.get('flex')
            if flex_temp and str(flex_temp).strip() not in ['', 'XX', 'XXX']:
                try:
                    epr_takeoff_data = get_speed_other(icaocode, oat=temp,
                                                        altitude=alt_val,
                                                        assumed_temp=int(flex_temp))
                    epr_takeoff = epr_takeoff_data.get('epr', epr_max) if epr_takeoff_data else epr_max
                except (ValueError, TypeError):
                    epr_takeoff = epr_max
            else:
                epr_takeoff = epr_max
            speed_other_data = get_speed_other(icaocode, weight=weight)

        elif is_boeing_737:
            speed_other_data = get_speed_other(icaocode, oat=temp,
                                                altitude=alt_val, weight=weight)
            n1_pack_on = speed_other_data.get('n1', 'XXX') if speed_other_data else "XXX"
            if n1_pack_on != "XXX":
                try:
                    n1_pack_off = round(float(n1_pack_on) + pack_off_adj, 1)
                except (ValueError, TypeError):
                    n1_pack_off = "XXX"
            flex_temp = rwy.get('flex')
            if flex_temp and str(flex_temp).strip() not in ['', 'XX', 'XXX']:
                try:
                    rd = get_reduced_thrust_n1(icaocode, effective_thrust,
                                               int(flex_temp), alt_val)
                    if rd and 'n1' in rd:
                        reduced_n1 = rd['n1']
                        reduced_n1_pack_off = round(float(reduced_n1) - pack_off_adj, 1)
                        reduced_n1_valid = True
                    else:
                        reduced_n1, reduced_n1_pack_off = n1_pack_on, n1_pack_off
                except (ValueError, TypeError):
                    reduced_n1, reduced_n1_pack_off = n1_pack_on, n1_pack_off
        else:
            speed_other_data = get_speed_other(icaocode, weight=weight)

        if is_boeing_737:
            engine_display = f"{engine_type} {thrust_label}"
        else:
            engine_display = engine_type

        line = f"*** {engine_display} {surface} ***"
        file.write(f"{line.center(40)}\n\n")

        est_tow      = safe_weight(loadsheet_data['PTOW'])
        pzfw         = safe_weight(uplink_data['pzfw'])
        plan_takeoff = safe_weight(uplink_data['ptof'])
        taxi_fuel_value = uplink_data.get('taxi_fuel', 0)
        try:
            taxi_fuel_thousands = float(taxi_fuel_value) / 1000.0
        except (ValueError, TypeError):
            taxi_fuel_thousands = 0.0

        PTOW_raw = est_tow + 2.0
        mtow_k = safe_weight(loadsheet_data.get('MAX TOW', 0))
        if mtow_k > 0 and PTOW_raw > mtow_k:
            PTOW_raw = mtow_k

        file.write(f"TEMP   PTOW    ATOW    ZFW     FUEL\n")
        file.write(f"{temp}C    {est_tow:.1f}   {PTOW_raw:.1f}   {pzfw:.1f}   {plan_takeoff:.1f}P\n")
        file.write(f"TXI FUEL\n{taxi_fuel_thousands:.1f}\n\n")

        file.write("*********** THRUST / V-SPEED **********\n")
        if anti_ice_on:
            file.write("  *****************\n")
            file.write("   * ANTI-ICE ON *\n")
            file.write("  *****************\n")
        file.write("\n")

        AIRBUS_TYPES = {'A318','A319','A320','A20N','A321','A21N','A332','A333','A339','A346'}
        is_airbus = icaocode.upper() in AIRBUS_TYPES

        if is_md83:
            if trim_data:
                file.write(f"         *MAX* EPR    TOW CG  STAB\n")
                epr_s = f"{epr_max:.2f}" if isinstance(epr_max, (int, float)) else epr_max
                file.write(f"      A/C ON  {epr_s}    {cg_display:<6}     {trim_data.get('trim','X.X')}\n")
                try:
                    ep = round(float(epr_max) + 0.02, 2)
                    file.write(f"      A/C OFF {ep:.2f}\n\n")
                except (ValueError, TypeError):
                    file.write(f"      A/C OFF XXX\n\n")
            else:
                epr_s = f"{epr_max:.2f}" if isinstance(epr_max, (int, float)) else epr_max
                file.write(f"         *MAX* EPR     TOW CG\n")
                file.write(f"      A/C ON  {epr_s}    {cg_display}\n")
                try:
                    ep = round(float(epr_max) + 0.02, 2)
                    file.write(f"      A/C OFF {ep:.2f}\n\n")
                except (ValueError, TypeError):
                    file.write(f"      A/C OFF XXX\n\n")
            if speed_other_data and isinstance(speed_other_data.get('speed'), dict):
                file.write(f"      O/RET   MM\n")
                file.write(f"      {speed_other_data['speed'].get('VsR','XXX'):<6} {speed_other_data['speed'].get('VMM','XXX')}\n\n")

        elif icaocode in ['A319','A320','A321','A21N'] and speed_other_data and isinstance(speed_other_data.get('speed'), dict):
            if trim_data:
                file.write(f"      TOW CG       STAB\n")
                file.write(f"       {cg_display:<10} {trim_data.get('trim','X.X')}\n")
            else:
                file.write(f"      TOW CG\n       {cg_display}\n")
            sp = speed_other_data['speed']
            file.write(f"       F     S    GRN DOT\n")
            file.write(f"      {sp.get('F','XXX'):<5} {sp.get('S','XXX'):<5} {sp.get('GRN DOT','XXX'):^8}\n\n")

        elif is_boeing_737:
            if trim_data:
                file.write(f"         *MAX* N1      TOW CG  STAB\n")
                file.write(f"      BLD ON  {n1_pack_on}    {cg_display:<6}  {trim_data.get('trim','X.X')}\n")
                file.write(f"      BLD OFF {n1_pack_off}\n\n")
            else:
                file.write(f"         *MAX* N1      TOW CG\n")
                file.write(f"      BLD ON  {n1_pack_on}    {cg_display}\n")
                file.write(f"      BLD OFF {n1_pack_off}\n\n")

        elif speed_other_data and 'name' in speed_other_data and 'speed' in speed_other_data:
            if trim_data:
                file.write(f"      {speed_other_data['name']} {speed_other_data['speed']}   TOW CG  STAB\n")
                file.write(f"                              {cg_display:<6}  {trim_data.get('trim','X.X')}\n\n")
            else:
                file.write(f"      {speed_other_data['name']} {speed_other_data['speed']}   TOW CG\n")
                file.write(f"                              {cg_display}\n")

        # ── Runway data ───────────────────────────────────────────────────────
        SPECIAL_AIRPORTS = {"SNA","SJO","EGE","JAC","GUC","DRO",
                            "JNU","WRG","PSG","TGU","SXM","STT","EYW","ASE"}

        flap_label = "CONF" if is_airbus else "FLAP"
        ac_label   = "APU"  if is_airbus else "BLD"

        if valid_runways:
            rwy = valid_runways[0]
            v1_str = str(_safe_int(rwy.get('v1'))) if _safe_int(rwy.get('v1')) > 0 else "XXX"
            vr_str = str(_safe_int(rwy.get('vr'))) if _safe_int(rwy.get('vr')) > 0 else "XXX"
            v2_str = str(_safe_int(rwy.get('v2'))) if _safe_int(rwy.get('v2')) > 0 else "XXX"

            try:
                HD_val = float(rwy.get('HD', 0))
            except Exception:
                HD_val = 0
            if abs(HD_val) >= 5:
                hd_text = (f"***** {int(round(HD_val))} KT HEADWIND APPLIED *****"
                           if HD_val > 0 else
                           f"***** {abs(int(round(HD_val)))} KT TAILWIND APPLIED *****")
                file.write(f"{hd_text}\n\n")

            mtow_val   = float(rwy.get('max_weight', 0))
            limit_code = rwy.get('limit_code', '')
            at_raw     = rwy.get('flex', '')
            at_override_occurred = False

            try:
                at_numeric = float(at_raw)
                if at_numeric < (float(temp) + 5) or at_numeric > 99:
                    at_numeric = None
            except Exception:
                at_numeric = None

            def resolve_at(aircraft_specific_check):
                nonlocal at_override_occurred
                if sta.upper() in SPECIAL_AIRPORTS:
                    at_override_occurred = True
                    return "MAX-SPCL"
                if aircraft_specific_check:
                    at_override_occurred = True
                    return "MAX-WT"
                if at_numeric is None:
                    at_override_occurred = True
                    return "MAX-TEMP"
                return f"{int(at_numeric)}C"

            if is_md83:
                at_display = resolve_at(epr_takeoff == "XXX" or epr_takeoff == epr_max)
            elif is_boeing_737:
                at_display = resolve_at(not reduced_n1_valid)
            else:
                at_display = resolve_at(False)

            bleed = rwy.get('bleed', 'ON')
            apu_status = ('OFF' if bleed.upper() == 'ON' else 'ON') if is_airbus else bleed

            if is_md83:
                thr_display = (f"{epr_max:.2f}" if isinstance(epr_max, (int, float)) else str(epr_max)) \
                              if at_override_occurred else \
                              (f"{epr_takeoff:.2f}" if isinstance(epr_takeoff, (int, float)) else str(epr_takeoff))
            elif is_boeing_737:
                thr_display = str(n1_pack_on) if at_override_occurred else str(reduced_n1)
            elif is_airbus:
                thr_display = "TOGA" if at_override_occurred else "FLEX"
            else:
                thr_display = rwy.get('thr', '') or "TOGA"

            thr_col = "EPR" if is_md83 else ("N1" if is_boeing_737 else "THR")

            file.write(f"RWY  {flap_label}  {ac_label}   {thr_col}   V1   VR   V2\n")
            file.write(f"{rwy['id']:<4} {rwy.get('flaps',''):<5} {apu_status:<4} {thr_display:<6}{v1_str:<4} {vr_str:<4} {v2_str:<4}\n\n")
            file.write(f"RWY  AT       MTOW\n")
            file.write(f"{rwy['id']:<4} {at_display:<8} {mtow_val:.1f}{limit_code}\n\n")

        origin_icao   = uplink_data.get('origin_icao', 'XXXX')
        max_elevation = max((r.get('elevation', 0) for r in valid_runways), default=0)
        airport_altitudes = get_airport_specific_altitudes(origin_icao, max_elevation)

        if airport_altitudes and airport_altitudes.get('EFP', '').strip():
            file.write("\n")
            file.write("************* AIRPORT NOTES *************\n")
            file.write(textwrap.fill(airport_altitudes['EFP'], width=34) + "\n\n")
            file.write("****** AIRPORT ANALYSIS DATA **********\n\n")

        if valid_runways:
            rwy = valid_runways[0]
            struct_wt = safe_weight(loadsheet_data.get('MAX TOW STRUCT', 0))
            file.write(f"  STRUCT WT LIMIT {struct_wt:.1f}\n\n")
            file.write(f"RWY  {flap_label}  {ac_label}   LIMIT\n")
            file.write(f"{rwy['id']:<4} {rwy.get('flaps',''):<5} {apu_status:<5} {mtow_val:.1f}{limit_code}\n")
            file.write(f"HDWND ADD / KT 0\n")
            file.write(f"TLWND SUB / KT 600\n")
            file.write("- - - - - - - - - - - - -\n")

            if airport_altitudes:
                eo_acc_afl = airport_altitudes.get('eo_acc', '0')
                elev       = float(rwy.get('elevation', max_elevation))
                eo_acc_msl = int(elev + float(eo_acc_afl))
                file.write(f"E/O ACCEL  /AFL/ FT  {eo_acc_afl}\n")
                file.write(f"           /MSL/ FT  {eo_acc_msl}\n")
                file.write("-------------------------\n")

            length_val = _safe_int(rwy.get('length', 0))
            slope_val  = rwy.get('slope', rwy.get('gradient', None))
            slope_str  = ".0"
            try:
                if slope_val is not None and str(slope_val).strip():
                    sf = float(slope_val)
                    if sf != 0.0:
                        slope_str = f"{sf:.1f}"
            except Exception:
                slope_str = "x.x"

            file.write(f"LENGTH - FT  {length_val}\n")
            file.write(f"SLOPE - PCT  {slope_str}\n")
            file.write("-------------------------\n")

            try:
                est_tow_val = safe_weight(loadsheet_data['PTOW'])
                ai_val      = round(est_tow_val * 0.0015, 2) if isinstance(est_tow_val, float) else 0.0
            except Exception:
                ai_val = 0.0
            ai_fmt = f"{ai_val:.1f}".lstrip('0') or '0.0'
            file.write(f"A/I ON SUB FROM CLB {ai_fmt} RWY {ai_fmt}\n")
            file.write("-------------------------\n")

    print(f"✓ Takeoff data: {takeoff_file}")

    # ── Closeout file ─────────────────────────────────────────────────────────
    with open(closeout_file, 'w') as file:
        sections = [
            ("HEADER", [
                f"LOAD CLOSEOUT RVSN {revision_number:02d} {loadsheet_data['Time Generated']}",
                f"{loadsheet_data['Flight Number']} {loadsheet_data['origin_iata']}-{loadsheet_data['destination_iata']} N{loadsheet_data['Ship Number']}",
                "",
            ]),
            ("WEIGHTS", [
                f"TOW {loadsheet_data['TOW']}",
                f"FOB {loadsheet_data['FOB']}A",
                f"ZFW {loadsheet_data['ZFW']}",
                f"STAB {trim_data['trim'] if trim_data else ''}",
                "R/A F-NO M-NO A-NO",
                "L/A F-1 M-0 A-0",
                f"TOW CG {cg_display}",
                f"PSGR {loadsheet_data['Passengers']} W0 X0",
                f"LAP {loadsheet_data['LAP']}",
                f"CREW {loadsheet_data['Crew Count']}",
                "---------",
                f"TSOB {int(loadsheet_data['Passengers']) + int(loadsheet_data['LAP']) + int(loadsheet_data['Crew Count'])}",
                f"PSGR WGT {int(loadsheet_data['Passengers']) * int(loadsheet_data['Passenger Weight'])}",
                f"CGO WGT {loadsheet_data['Total Cargo']}",
                f"EOW {loadsheet_data['OEW']}",
                "SECOK\n",
            ]),
        ]
        for _, lines in sections:
            for line in lines:
                file.write(f"{line}\n")

    print(f"✓ Closeout data: {closeout_file}")
    return takeoff_file, closeout_file


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    username = os.environ.get('SIMBRIEF_USER', 'tgibbons').strip()
    print(f"Fetching SimBrief data for '{username}'…")
    tree = fetch_xml_from_api(username)
    if not tree:
        print("✗ Failed to fetch SimBrief data.")
        return

    print("✓ SimBrief data received")
    xml_root     = tree.getroot()
    date         = datetime.now().strftime("%Y-%m-%d")
    aircraft_type = os.environ.get('AIRCRAFT_TYPE', 'B738').strip()

    uplink_data, loadsheet_data, valid_runways, anti_ice_on, taxi_fuel, cg_percent = \
        parse_all_flight_data_from_xml(xml_root, date, aircraft_type)

    if not valid_runways:
        print("✗ No valid runway data found.")
        return

    takeoff_file, closeout_file = generate_combined_output(
        loadsheet_data, uplink_data, valid_runways,
        anti_ice_on, taxi_fuel, OUTPUTS_DIR, cg_percent
    )

    if closeout_file is None:
        print("\n✗ Only rejection message generated — closeout skipped (fuel variance).")
    else:
        print(f"\n✓ Files generated successfully!")
        # Print paths relative to outputs/ so the web app can serve them
        to_name = os.path.basename(takeoff_file)
        co_name = os.path.basename(closeout_file)
        print(f"  Takeoff:  {takeoff_file}")
        print(f"  Closeout: {closeout_file}")
        print(f"\nDownload: /outputs/{to_name}")
        print(f"Download: /outputs/{co_name}")


if __name__ == "__main__":
    main()
