"""embody.core.wakeword — always-on local wake word → fire the embodied voice loop.

A STANDALONE daemon. It runs in the isolated ``~/.embody-stt`` venv (which has
faster-whisper + onnxruntime) and is deliberately NOT imported by the gateway. On
the wake phrase it runs the SAME path push-to-talk uses — record the command,
transcribe locally, POST it to the embody webhook — so Minnie/Evy answers with her
full face, mood, and voice. Push-to-talk stays a manual backup (PipeWire shares the
one mic, verified).

Detection re-implements the **okay-hermes-voice** approach (Apache-2.0 — H-Ali13381;
credited in README/NOTICE) natively: the tiny RepCNN ONNX model takes a RAW 3-second
waveform and returns a score; we require N consecutive windows over a threshold. The
mel frontend is baked into the model graph, so there is NO feature engineering here —
just feed float32 samples. ~15 ms/inference, so it never touches her 60fps face.

Run:  ~/.embody-stt/bin/python <plugin>/core/wakeword.py

Everything is best-effort: no mic / model missing / webhook disabled → it logs and
stays inert. Swap the stock "Okay Hermes" model for a forged "Hey Evy" model by
pointing ``wakeword.model_path`` at the new ONNX — nothing else changes.
"""
from __future__ import annotations

import collections
import hashlib
import hmac
import json
import logging
import math
import os
import subprocess
import sys
import time
import urllib.request

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [wakeword] %(message)s")
LOG = logging.getLogger("embody.wakeword")

_INSECURE_NO_AUTH = "INSECURE_NO_AUTH"
_DEFAULTS = {
    "enabled": True,
    "model_path": "~/.hermes/wakeword/okay-hermes-repcnn-onnx/wakeword.onnx",
    "phrase_label": "Okay Hermes",
    "threshold": 0.6973556280136108,
    "trigger_consecutive_windows": 2,
    "inference_interval_seconds": 0.25,
    "cooldown_seconds": 2.5,
    "sample_rate": 16000,
    "window_seconds": 3.0,
    "block_seconds": 0.1,
    # command capture (RMS VAD) after wake
    "speech_rms_threshold": 200.0,
    "speech_start_timeout_seconds": 8.0,
    "speech_silence_duration_seconds": 1.1,
    "max_command_seconds": 30.0,
    "min_command_seconds": 0.4,
    "stt_model": "base",
    "mic_source": "",
}


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    """Read the embody config.yaml; merge wakeword.* over defaults and pull the
    webhook + stt settings from the existing voice_input block."""
    path = os.path.expanduser(os.environ.get("EMBODY_CONFIG", "~/.hermes/plugins/embody/config.yaml"))
    raw = {}
    try:
        import yaml
        with open(path, encoding="utf-8-sig") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as exc:  # noqa: BLE001
        LOG.warning("config load failed (%s) — using defaults", exc)
    cfg = dict(_DEFAULTS)
    cfg.update({k: v for k, v in (raw.get("wakeword") or {}).items() if v is not None})
    vi = raw.get("voice_input") or {}
    cfg["webhook"] = vi.get("webhook") or {}
    # Share the SAME stable conversation as PTT so wake + push-to-talk turns
    # thread into one ongoing conversation (continuity). See voice_input._inject.
    cfg["conversation_id"] = cfg.get("conversation_id") or vi.get("conversation_id") or "evy-voice"
    cfg["stt_venv"] = vi.get("stt_venv") or "~/.embody-stt"
    cfg["stt_model"] = cfg.get("stt_model") or vi.get("stt_model") or "base"
    if not cfg.get("mic_source"):
        cfg["mic_source"] = vi.get("mic_source", "") or ""
    return cfg


# --------------------------------------------------------------------------- #
# Mic stream (parecord raw s16le → float32 blocks) — shares the mic via PipeWire
# --------------------------------------------------------------------------- #
def mic_blocks(cfg: dict):
    """Yield float32 mono blocks (~block_seconds each) from a continuous parecord
    stream. Raises on spawn failure (caller treats as inert)."""
    rate = int(cfg["sample_rate"])
    block_n = max(1, int(float(cfg["block_seconds"]) * rate))
    cmd = ["parecord", f"--rate={rate}", "--channels=1", "--format=s16le", "--raw"]
    src = (cfg.get("mic_source") or "").strip()
    if src:
        cmd += [f"--device={src}"]
    LOG.info("mic: %s", " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    nbytes = block_n * 2  # s16 = 2 bytes/sample
    try:
        while True:
            buf = proc.stdout.read(nbytes)
            if not buf or len(buf) < nbytes:
                break
            yield np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            proc.kill()


def _rms_int16(block_f32: np.ndarray) -> float:
    if block_f32.size == 0:
        return 0.0
    return float(math.sqrt(float(np.mean((block_f32 * 32768.0) ** 2))))


# --------------------------------------------------------------------------- #
# Wake daemon
# --------------------------------------------------------------------------- #
class Wake:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        import onnxruntime as ort
        model = os.path.expanduser(str(cfg["model_path"]))
        if not os.path.exists(model):
            raise FileNotFoundError(f"wakeword model not found: {model}")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1   # tiny model — keep the always-on listener cheap
        opts.inter_op_num_threads = 1
        self.session = ort.InferenceSession(model, sess_options=opts, providers=["CPUExecutionProvider"])
        self.in_name = self.session.get_inputs()[0].name
        self.out_name = self.session.get_outputs()[0].name
        LOG.info("loaded model %s (in=%s out=%s)", model, self.in_name, self.out_name)
        self._whisper = None  # lazy — only on the first wake

    def _score(self, waveform: np.ndarray) -> float:
        out = self.session.run([self.out_name], {self.in_name: waveform[None, :].astype(np.float32)})
        return float(np.asarray(out[0]).reshape(-1)[0])

    @property
    def whisper(self):
        if self._whisper is None:
            from faster_whisper import WhisperModel
            self._whisper = WhisperModel(str(self.cfg["stt_model"]), device="cpu", compute_type="int8")
        return self._whisper

    def run(self) -> None:
        cfg = self.cfg
        rate = int(cfg["sample_rate"])
        window_n = int(float(cfg["window_seconds"]) * rate)
        interval = float(cfg["inference_interval_seconds"])
        threshold = float(cfg["threshold"])
        consecutive = max(1, int(cfg["trigger_consecutive_windows"]))
        cooldown = float(cfg["cooldown_seconds"])

        rolling = collections.deque(maxlen=window_n)
        recent = collections.deque(maxlen=consecutive)
        last_infer = 0.0
        blocks = mic_blocks(cfg)
        LOG.info("listening for %r (threshold=%.4f, consecutive=%d)", cfg["phrase_label"], threshold, consecutive)
        for block in blocks:
            rolling.extend(block)
            if len(rolling) < window_n:
                continue
            now = time.monotonic()
            if now - last_infer < interval:
                continue
            last_infer = now
            score = self._score(np.fromiter(rolling, dtype=np.float32, count=window_n))
            recent.append(score)
            if score >= 0.25:   # verbose gate during tuning — shows your voice registering
                LOG.info("score %.4f", score)
            if len(recent) == consecutive and all(s >= threshold for s in recent):
                if self._evy_busy():
                    recent.clear()       # anti-feedback: don't wake while she's talking/thinking
                    continue
                LOG.info("WAKE — %r (scores=%s)", cfg["phrase_label"], [round(s, 4) for s in recent])
                recent.clear()
                rolling.clear()
                self._on_wake(blocks)
                time.sleep(cooldown)
                last_infer = time.monotonic()

    # ---- after wake: capture command (RMS VAD) → whisper → inject ----------
    def _evy_busy(self) -> bool:
        """True while Evy is thinking/working/speaking — so her own TTS coming back
        through the mic can't re-trigger the wake (feedback loop). Reads the embody
        state server; if unreachable, assume not busy (fail open). Best-effort."""
        try:
            with urllib.request.urlopen("http://127.0.0.1:8830/state.json", timeout=1) as r:
                st = json.loads(r.read().decode("utf-8")).get("state", "")
            return st in ("speaking", "thinking", "working")
        except Exception:
            return False

    def _play_beep(self) -> None:
        """Short audible chirp the instant the wake fires, so the user knows she
        heard them and it's time to speak the command. Best-effort; never raises."""
        try:
            import wave
            p = "/tmp/embody_wake_beep.wav"
            if not os.path.exists(p):
                sr = 16000; n = int(sr * 0.18); t = np.arange(n) / sr
                a = (0.4 * np.sin(2 * np.pi * 880 * t)).astype(np.float32)
                f = int(sr * 0.03); a[:f] *= np.linspace(0, 1, f); a[-f:] *= np.linspace(1, 0, f)
                with wave.open(p, "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
                    w.writeframes((a * 32767).astype(np.int16).tobytes())
            subprocess.Popen(["paplay", p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:  # noqa: BLE001
            LOG.debug("beep failed: %s", exc)

    def _on_wake(self, blocks) -> None:
        self._play_beep()
        time.sleep(0.35)          # let the chirp finish so it isn't captured as the command
        try:
            audio = self._record_command(blocks)
            if audio is None or audio.size == 0:
                LOG.info("no command after wake")
                return
            text = self._transcribe(audio)
            if text:
                LOG.info("command -> %r", text)
                self._inject(text)
            else:
                LOG.info("empty transcript")
        except Exception as exc:  # noqa: BLE001 — a bad turn must never kill the listener
            LOG.warning("on_wake failed: %s", exc)

    def _record_command(self, blocks) -> "np.ndarray | None":
        cfg = self.cfg
        rate = int(cfg["sample_rate"])
        rms_thresh = float(cfg["speech_rms_threshold"])
        start_timeout = float(cfg["speech_start_timeout_seconds"])
        silence_dur = float(cfg["speech_silence_duration_seconds"])
        max_s = float(cfg["max_command_seconds"])
        block_s = float(cfg["block_seconds"])
        chunks: list[np.ndarray] = []
        started = False
        t0 = time.monotonic()
        last_voice = t0
        for block in blocks:
            now = time.monotonic()
            voiced = _rms_int16(block) >= rms_thresh
            if not started:
                if voiced:
                    started = True
                    last_voice = now
                    chunks.append(block)
                elif now - t0 > start_timeout:
                    return None  # nobody spoke
                continue
            chunks.append(block)
            if voiced:
                last_voice = now
            if now - last_voice > silence_dur:
                break  # trailing silence → end of command
            if now - t0 > max_s:
                break
        return np.concatenate(chunks) if chunks else None

    def _transcribe(self, audio: np.ndarray) -> str:
        if audio.size < int(float(self.cfg["min_command_seconds"]) * int(self.cfg["sample_rate"])):
            return ""
        segs, _ = self.whisper.transcribe(audio.astype(np.float32))
        return " ".join(s.text for s in segs).strip()

    def _inject(self, text: str) -> None:
        wh = self.cfg.get("webhook") or {}
        host = wh.get("host", "127.0.0.1")
        port = int(wh.get("port", 8644) or 8644)
        route = wh.get("route", "voice") or "voice"
        secret = str(wh.get("secret", "") or "")
        convo = str(self.cfg.get("conversation_id") or "evy-voice")
        body = json.dumps(
            {"transcript": text, "type": "voice", "conversation_id": convo}
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if secret and secret != _INSECURE_NO_AUTH:
            headers["X-Webhook-Signature"] = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        url = f"http://{host}:{port}/webhooks/{route}"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception as exc:  # noqa: BLE001
            LOG.warning("inject POST %s failed (webhook enabled?): %s", url, exc)


def main() -> int:
    cfg = load_config()
    if not cfg.get("enabled", True):
        LOG.info("wakeword disabled in config — exiting")
        return 0
    try:
        wake = Wake(cfg)
        LOG.info("pre-warming STT model so the first wake isn't slow…")
        _ = wake.whisper          # load faster-whisper now, not lazily on first wake
        LOG.info("STT ready")
    except Exception as exc:  # noqa: BLE001
        LOG.error("startup failed: %s", exc)
        return 1
    while True:
        try:
            wake.run()
            LOG.warning("mic stream ended — restarting in 2s")
            time.sleep(2)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:  # noqa: BLE001 — never die; restart the listen loop
            LOG.warning("run loop error: %s — restarting in 3s", exc)
            time.sleep(3)


if __name__ == "__main__":
    sys.exit(main())
