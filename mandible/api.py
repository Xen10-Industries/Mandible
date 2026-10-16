"""Lightweight local REST API for Mandible.
Allows Elgato Stream Deck, OBS Studio, webhooks, and scripts to control chains,
soundboard, mute, and mic check over HTTP (localhost:38420).
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Core


class MandibleApiHandler(BaseHTTPRequestHandler):
    server: MandibleApiServer  # type hint

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def _send_json(self, status_code: int, data: dict):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0:
                return {}
            data = self.rfile.read(length)
            return json.loads(data.decode("utf-8"))
        except Exception:
            return {}

    def log_message(self, format, *args):
        # Suppress noisy standard HTTP logs in production
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        core = self.server.core

        if path == "/api/status":
            target = core.target()
            target_chain = core.chain_by_id(target) if target else None
            aud_state, aud_cur, aud_tot = core.get_audition_status()
            self._send_json(200, {
                "status": "ok",
                "running": core.engine.running,
                "active_chain_id": target,
                "active_chain_name": target_chain.name if target_chain else ("Clean" if target == "dry" else "Muted"),
                "muted": core.engine.ptt_muted,
                "audition": {
                    "state": aud_state,
                    "current_s": round(aud_cur, 2),
                    "total_s": round(aud_tot, 2),
                },
                "soundboard_playing": core.engine.soundboard.is_any_playing(),
            })

        elif path == "/api/chains":
            target = core.target()
            items = []
            for c in core.cfg.chains:
                items.append({
                    "id": c.id,
                    "name": c.name,
                    "hotkey": c.hotkey.label if c.hotkey else "",
                    "active": (c.id == target),
                    "gain_db": c.gain_db,
                    "plugin_count": len(c.plugins),
                })
            self._send_json(200, {"status": "ok", "chains": items})

        elif path == "/api/soundboard":
            items = []
            for s in core.cfg.soundboard:
                items.append({
                    "id": s.id,
                    "name": s.name,
                    "playing": core.engine.soundboard.is_playing(s.id),
                    "volume_db": s.volume_db,
                    "hotkey": s.hotkey.label if s.hotkey else "",
                })
            self._send_json(200, {"status": "ok", "clips": items})

        else:
            self._send_json(404, {"error": "Not found", "path": path})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        core = self.server.core
        data = self._read_json_body()

        if path == "/api/chains/select":
            cid = data.get("id")
            name = data.get("name")
            target_chain = None
            if cid:
                target_chain = core.chain_by_id(cid)
            elif name:
                target_chain = next((c for c in core.cfg.chains if c.name.lower() == str(name).lower()), None)

            if target_chain:
                core.press(target_chain.id)
                self._send_json(200, {"status": "ok", "selected_chain": target_chain.name, "id": target_chain.id})
            elif cid == "dry" or name == "clean":
                core.press("dry")
                self._send_json(200, {"status": "ok", "selected_chain": "Clean", "id": "dry"})
            else:
                self._send_json(400, {"error": "Chain not found", "id": cid, "name": name})

        elif path == "/api/panic" or path == "/api/all_off":
            core.panic()
            self._send_json(200, {"status": "ok", "message": "All effects bypassed, soundboard stopped."})

        elif path == "/api/mute":
            # Optional explicit boolean 'muted': true/false, or toggle if not provided
            if "muted" in data:
                core.engine.ptt_muted = bool(data["muted"])
            else:
                core.engine.ptt_muted = not core.engine.ptt_muted
            core._sync_overlay()
            self._send_json(200, {"status": "ok", "muted": core.engine.ptt_muted})

        elif path == "/api/soundboard/play":
            cid = data.get("id")
            name = data.get("name")
            clip = None
            if cid:
                clip = next((s for s in core.cfg.soundboard if s.id == cid), None)
            elif name:
                clip = next((s for s in core.cfg.soundboard if s.name.lower() == str(name).lower()), None)

            if clip:
                core.play_soundboard(clip)
                self._send_json(200, {"status": "ok", "playing": clip.name, "id": clip.id})
            else:
                self._send_json(400, {"error": "Soundboard clip not found", "id": cid, "name": name})

        elif path == "/api/soundboard/stop":
            cid = data.get("id")
            if data.get("stop_all", False) or not cid:
                core.stop_all_soundboard()
                self._send_json(200, {"status": "ok", "message": "All soundboard clips stopped."})
            else:
                core.stop_soundboard(cid)
                self._send_json(200, {"status": "ok", "stopped": cid})

        elif path == "/api/audition/start":
            dur = float(data.get("duration_s", 5.0))
            core.start_mic_audition(dur)
            self._send_json(200, {"status": "ok", "audition": "started", "duration_s": dur})

        elif path == "/api/audition/stop":
            core.stop_mic_audition()
            self._send_json(200, {"status": "ok", "audition": "stopped"})

        else:
            self._send_json(404, {"error": "Not found", "path": path})


class MandibleApiServer(ThreadingHTTPServer):
    def __init__(self, core: Core, host: str = "127.0.0.1", port: int = 38420):
        super().__init__((host, port), MandibleApiHandler)
        self.core = core
        self.daemon_threads = True


class ApiManager:
    """Manages the background HTTP API thread."""

    def __init__(self, core: Core):
        self.core = core
        self.server: MandibleApiServer | None = None
        self.thread: threading.Thread | None = None

    def start(self, port: int = 38420, host: str = "127.0.0.1") -> bool:
        self.stop()
        try:
            self.server = MandibleApiServer(self.core, host=host, port=port)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="Mandible-API")
            self.thread.start()
            print(f"[Mandible API] listening on http://{host}:{port}/api/status")
            return True
        except Exception as exc:
            print(f"[Mandible API] could not start on {host}:{port}: {exc}")
            self.server = None
            self.thread = None
            return False

    def stop(self):
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
            self.server = None
            self.thread = None

    @property
    def is_running(self) -> bool:
        return self.server is not None
