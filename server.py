"""
server.py — TAKEOFF PERF Flask backend
Runs TAKEOFF_PERF.py logic in-process, returns output files as JSON.
Deploy on Railway: set PORT env var (Railway sets it automatically).
"""

import os
import sys
import json
import traceback
import subprocess
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, send_file

app = Flask(__name__, static_folder="static")

# ── CORS (manual, no extra deps) ──────────────────────────────────────────────
@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

@app.route("/api/<path:p>", methods=["OPTIONS"])
def options_handler(p):
    return "", 204


# ── Serve frontend ────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ── SimBrief proxy (avoids CORS issues from browser) ─────────────────────────
@app.route("/api/simbrief")
def simbrief_proxy():
    username = request.args.get("username", "").strip()
    if not username:
        return jsonify({"error": "username required"}), 400

    import urllib.request, urllib.error, ssl, xml.etree.ElementTree as ET

    url = f"https://www.simbrief.com/api/xml.fetcher.php?username={username}"
    def _make_ctx():
        try:
            import certifi
            return ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
        import platform
        if platform.system() == "Darwin":
            mac = "/etc/ssl/cert.pem"
            if os.path.exists(mac):
                return ssl.create_default_context(cafile=mac)
        return ssl.create_default_context()
    ctx = _make_ctx()
    try:
        with urllib.request.urlopen(url, context=ctx, timeout=15) as r:
            xml_bytes = r.read()
    except urllib.error.URLError as e:
        return jsonify({"error": str(e)}), 502

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        return jsonify({"error": f"XML parse: {e}"}), 502

    # Parse into a dict the frontend can use
    def g(parent, tag, default=""):
        el = parent.find(tag) if parent is not None else None
        return (el.text or "").strip() if el is not None else default

    general  = root.find("general")
    fuel     = root.find("fuel")
    weights  = root.find("weights")
    origin   = root.find("origin")
    dest     = root.find("destination")
    aircraft = root.find("aircraft")
    conds    = root.find("conditions")
    alternate = root.find("alternate")
    crew_el  = root.find("crew")

    crew_count = 0
    if crew_el is not None:
        for tag in ["cpt", "fo", "fa"]:
            crew_count += len(crew_el.findall(tag))
    if crew_count == 0:
        crew_count = 6

    runways = []
    for rwy in root.findall(".//tlr/takeoff//runway"):
        rv = lambda t, d="": (rwy.find(t).text or "").strip() if rwy.find(t) is not None else d
        try:
            mw = float(rv("max_weight", "0"))
        except ValueError:
            continue
        if not mw:
            continue
        try:
            hd = float(rv("headwind_component", "0"))
        except ValueError:
            hd = 0.0
        runways.append({
            "id":         rv("identifier", "XX"),
            "flaps":      rv("flap_setting"),
            "v1":         rv("speeds_v1"),
            "vr":         rv("speeds_vr"),
            "v2":         rv("speeds_v2"),
            "thr":        rv("thrust_setting"),
            "flex":       rv("flex_temperature"),
            "length":     rv("length"),
            "bleed":      rv("bleed_setting", "ON"),
            "max_weight": f"{mw/1000:.1f}",
            "elevation":  float(rv("elevation", "0") or "0"),
            "limit_code": rv("limit_code"),
            "HD":         hd,
            "slope":      rv("gradient"),
            "anti_ice":   rv("anti_ice_setting"),
        })

    data = {
        "fltnum":       g(general, "flight_number"),
        "origin_icao":  g(origin, "icao_code"),
        "origin_iata":  g(origin, "iata_code"),
        "dest_icao":    g(dest, "icao_code"),
        "dest_iata":    g(dest, "iata_code"),
        "altn_icao":    g(alternate, "icao_code"),
        "acname":       g(aircraft, "name"),
        "registration": g(aircraft, "registration"),
        "icaocode":     g(aircraft, "icaocode"),
        "fin":          g(aircraft, "fin"),
        "ofp":          g(general, "release"),
        "pax_count":    g(weights, "pax_count", "0"),
        "pax_weight":   int(g(weights, "pax_weight", "180") or 180),
        "cargo":        g(weights, "cargo", "0"),
        "plan_ramp":    g(fuel, "plan_ramp", "0"),
        "taxi_fuel":    g(fuel, "taxi", "0"),
        "oew":          g(weights, "oew", "0"),
        "max_zfw":      g(weights, "max_zfw", "0"),
        "max_tow":      g(weights, "max_tow", "0"),
        "max_tow_struct": g(weights, "max_tow_struct", "0"),
        "max_ldw":      g(weights, "max_ldw", "0"),
        "est_zfw":      g(weights, "est_zfw", "0"),
        "est_tow":      g(weights, "est_tow", "0"),
        "enroute_burn": g(fuel, "enroute_burn", "0"),
        "plan_takeoff": g(fuel, "plan_takeoff", "0"),
        "min_takeoff":  g(fuel, "min_takeoff", "0"),
        "alternate_burn": g(fuel, "alternate_burn", "0"),
        "reserve":      g(fuel, "reserve", "0"),
        "costindex":    g(general, "costindex", "0"),
        "cruise_fl":    str(int(g(general, "initial_altitude", "0") or 0) // 100),
        "temp":         g(conds, "temperature", "0"),
        "qnh":          g(conds, "altimeter", "29.92"),
        "surface":      g(conds, "surface_condition", "dry"),
        "wind":         f"{g(conds,'wind_direction','0')}/{g(conds,'wind_speed','0')}",
        "crew_count":   crew_count,
        "runways":      runways,
    }
    return jsonify(data)



# ── PDF folder matching (same algorithm as Aviobook) ─────────────────────────
@app.route("/api/match-pdfs", methods=["POST"])
def match_pdfs():
    """
    Client sends: { filenames: [...], orig: "KLAX", dest: "YSSY", flight: "AAL1" }
    Returns:      { matches: [{name, score, doc_type}] } sorted best-first
    """
    try:
        req        = request.get_json(force=True)
        filenames  = req.get("filenames", [])
        orig_icao  = (req.get("orig") or "").strip().upper()
        dest_icao  = (req.get("dest") or "").strip().upper()
        flight_num = (req.get("flight") or "").strip().upper().replace(" ", "")

        def score_and_type(name):
            stem = name.upper().replace(".PDF", "")
            doc_type = ""
            for suffix in ("-RLS", "-WB", "-OFP", "-RELEASE", "-WEIGHTBALANCE",
                           "-TAKEOFF", "-PERF", "-NOTOC", "-LOADSHEET"):
                if stem.endswith(suffix):
                    doc_type = suffix.lstrip("-")
                    stem = stem[: -len(suffix)]
                    break
            core = stem.replace("-", "").replace("_", "").replace(" ", "")
            pair = orig_icao + dest_icao
            s = 0
            if pair and pair in core:               s += 100
            if flight_num and flight_num in core:   s += 60
            elif orig_icao and orig_icao in core:   s += 20
            if dest_icao and dest_icao in core:     s += 20
            if doc_type in ("RLS", "WB", "TAKEOFF", "PERF", "NOTOC", "LOADSHEET"):
                s += 10
            return s, doc_type

        results = []
        for fname in filenames:
            if not fname.upper().endswith(".PDF"):
                continue
            s, doc_type = score_and_type(fname)
            if s > 0:
                results.append({"name": fname, "score": s, "doc_type": doc_type})

        results.sort(key=lambda x: x["score"], reverse=True)
        return jsonify({"matches": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Generate TPS ──────────────────────────────────────────────────────────────
@app.route("/api/generate", methods=["POST"])
def generate():
    body = request.get_json(force=True)

    # Build env for the subprocess
    env = os.environ.copy()
    env.update({
        "SIMBRIEF_USER":    body.get("SIMBRIEF_USER", ""),
        "PAX_COUNT":        str(body.get("PAX_COUNT", "")),
        "CARGO":            str(body.get("CARGO", "")),
        "PLAN_RAMP":        str(body.get("PLAN_RAMP", "")),
        "CG_PERCENT":       str(body.get("CG_PERCENT", "25.0")),
        "ZFW_OVERRIDE":     str(body.get("ZFW_OVERRIDE", "")),
        "AIRCRAFT_TYPE":    body.get("AIRCRAFT_TYPE", "B738"),
        "RUNWAY_ID":        body.get("RUNWAY_ID", ""),
        "RWY_FLAPS":        str(body.get("RWY_FLAPS", "")),
        "RWY_V1":           str(body.get("RWY_V1", "")),
        "RWY_VR":           str(body.get("RWY_VR", "")),
        "RWY_V2":           str(body.get("RWY_V2", "")),
        "RWY_THR":          str(body.get("RWY_THR", "")),
        "RWY_FLEX":         str(body.get("RWY_FLEX", "")),
        "RWY_LENGTH":       str(body.get("RWY_LENGTH", "")),
        "RWY_BLEED":        str(body.get("RWY_BLEED", "")),
        "RWY_MAX_WEIGHT":   str(body.get("RWY_MAX_WEIGHT", "")),
        "RWY_LIMIT_CODE":   str(body.get("RWY_LIMIT_CODE", "")),
        "RWY_ASDR":         str(body.get("RWY_ASDR", "")),
        "RWY_HD":           str(body.get("RWY_HD", "")),
        "OUTPUTS_DIR":      body.get("OUTPUTS_DIR", "outputs"),
        "OUTPUT_SUBFOLDER": body.get("OUTPUT_SUBFOLDER", ""),
    })

    # Run TAKEOFF_PERF.py in its own directory
    script_dir = Path(__file__).parent
    result = subprocess.run(
        [sys.executable, "TAKEOFF_PERF.py"],
        cwd=str(script_dir),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )

    stdout = result.stdout
    stderr = result.stderr

    if result.returncode != 0:
        return jsonify({
            "success": False,
            "error": stderr or stdout or "Script exited non-zero",
            "stdout": stdout,
        }), 500

    # Find generated file paths from stdout
    takeoff_path = closeout_path = None
    takeoff_content = closeout_content = ""

    for line in stdout.splitlines():
        if "_TAKEOFF.txt" in line and ("✓" in line or "Takeoff:" in line):
            parts = line.split()
            for p in parts:
                if "_TAKEOFF.txt" in p:
                    takeoff_path = p if os.path.isabs(p) else str(script_dir / p)
        if "_CLOSEOUT.txt" in line and ("✓" in line or "Closeout:" in line):
            parts = line.split()
            for p in parts:
                if "_CLOSEOUT.txt" in p:
                    closeout_path = p if os.path.isabs(p) else str(script_dir / p)

    # Also scan for /outputs/ lines
    for line in stdout.splitlines():
        if "Takeoff: " in line:
            path_candidate = line.split("Takeoff: ")[-1].strip()
            candidate = path_candidate if os.path.isabs(path_candidate) else str(script_dir / path_candidate)
            if os.path.exists(candidate):
                takeoff_path = candidate
        if "Closeout: " in line:
            path_candidate = line.split("Closeout: ")[-1].strip()
            candidate = path_candidate if os.path.isabs(path_candidate) else str(script_dir / path_candidate)
            if os.path.exists(candidate):
                closeout_path = candidate

    if takeoff_path and os.path.exists(takeoff_path):
        with open(takeoff_path) as f:
            takeoff_content = f.read()
    if closeout_path and os.path.exists(closeout_path):
        with open(closeout_path) as f:
            closeout_content = f.read()

    # Build download filenames
    base = f"{body.get('SIMBRIEF_USER','')}"
    if takeoff_path:
        base = Path(takeoff_path).stem.replace("_TAKEOFF", "")
    elif closeout_path:
        base = Path(closeout_path).stem.replace("_CLOSEOUT", "")

    return jsonify({
        "success": True,
        "stdout": stdout,
        "takeoff": takeoff_content,
        "closeout": closeout_content,
        "takeoff_filename": f"{base}_TAKEOFF.txt",
        "closeout_filename": f"{base}_CLOSEOUT.txt",
        "saved_to": str(script_dir / env["OUTPUTS_DIR"]),
    })


# ── Download saved file ───────────────────────────────────────────────────────
@app.route("/api/download/<path:filename>")
def download_file(filename):
    script_dir = Path(__file__).parent
    outputs_dir = script_dir / "outputs"
    return send_from_directory(str(outputs_dir), filename, as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"🚀 TAKEOFF PERF server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
