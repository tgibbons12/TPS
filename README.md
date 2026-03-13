# TAKEOFF PERF — Web App

iOS-style takeoff performance calculator. Prefills from SimBrief OFP data and saves output files directly on the server.

## Project Structure

```
tps_app/
├── server.py           ← Flask backend (API + static serving)
├── TAKEOFF_PERF.py     ← Core computation script (your original)
├── SPEEDOTHER.py       ← (add your supporting modules here)
├── TRIMSETTING.py
├── ENGINEFAILPROC.py
├── requirements.txt
├── Procfile
├── railway.json
├── outputs/            ← Generated TPS files saved here
└── static/
    └── index.html      ← iOS-style frontend
```

## Local Development

```bash
pip install -r requirements.txt
python server.py
# Open http://localhost:5000
```

Set `FLASK_DEBUG=1` for auto-reload.

## Deploy on Railway

1. Push this folder to a GitHub repo
2. Create a new Railway project → "Deploy from GitHub"
3. Railway auto-detects Python and uses the Procfile
4. Set any needed env vars in Railway dashboard (none required by default)
5. Your app URL will be something like `https://your-app.up.railway.app`

## Environment Variables (optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 5000 | Set automatically by Railway |
| `FLASK_DEBUG` | 0 | Set to 1 for local dev |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Frontend app |
| GET | `/api/simbrief?username=X` | Proxy SimBrief fetch, returns parsed JSON |
| POST | `/api/generate` | Run TAKEOFF_PERF.py, returns file contents + saves to disk |
| GET | `/api/download/<filename>` | Download a generated file from outputs/ |

## Output Folder

Files are saved to `OUTPUTS_DIR` on the server (default: `./outputs/`).  
Set a custom path in the app's Generate tab → "Save To" field.  
On Railway, files are ephemeral — download them immediately or mount a volume.

## Supporting Modules

Make sure these files from your original project are in the same folder as `server.py`:
- `SPEEDOTHER.py`
- `TRIMSETTING.py`  
- `ENGINEFAILPROC.py`
- `takeoff_perf_revisions.json` (created automatically)
