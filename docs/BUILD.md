# 🛠️ Build Your Own Minnie

Everything you need to replicate Minnie — the animated cat-eye face, the synced RGB case, and her voice — on real hardware. This is the exact stack Minnie runs on: a **Raspberry Pi 5** inside a **SunFounder Pironman 5 Pro Max** case running Hermes Agent + this plugin.

If you only want the face, you don't need any of this — open the face in a browser on any Hermes box. This guide is for the full embodiment: case LEDs, the DSI touchscreen kiosk, and speakers.

---

## Bill of Materials

| Part | Notes |
|---|---|
| **Raspberry Pi 5** (8GB or 16GB) | The brain. 16GB if you also run models/extras locally. |
| **SunFounder Pironman 5 Pro Max** case w/ touchscreen | Her body — RGB **WS2812 LEDs**, 0.96" **OLED**, 4.3" **DSI touchscreen**, stereo **speakers**, 5MP **camera**, dual-**NVMe**. [SunFounder product page](https://www.sunfounder.com/products/pironman-5-pro-max-mini-pc-case-with-touch-screen-for-raspberry-pi-5) · [Where to buy (Amazon)](https://a.co/d/09DaQDy9) |
| **NVMe M.2 SSD** (e.g. Samsung 980 / 990 PRO) | OS / boot drive. Far faster + more reliable than SD for daily driving. |
| **27W USB-C PD power supply** | The Pironman needs the headroom — NVMe + screen + LEDs + accessories. Don't under-power it. |
| **microSD card** | For the initial OS flash (you'll migrate/boot to NVMe after). |
| USB microphone (e.g. Samson Go Mic) | *Optional* — for a future voice-in wave. |
| M5StickC Plus | *Optional* — a physical remote / companion device. |
| ElevenLabs API key | *Optional* — gives Minnie her voice. Without it, speech falls back to Hermes' configured TTS. |

## Software

- **Raspberry Pi OS (Bookworm)** — 64-bit, desktop (you need a display server for the kiosk).
- **SunFounder `pironman5` software** — drives the OLED, fans, and dashboard.
- **Hermes Agent** — the agent runtime.
- **`hermes-embodiment`** (this plugin).

---

## Build steps

### 1. Assemble the case
Build the Pironman 5 Pro Max with the Pi 5 and the NVMe drive following [SunFounder's assembly guide](https://www.sunfounder.com/products/pironman-5-pro-max-mini-pc-case-with-touch-screen-for-raspberry-pi-5).

> **Seat the HAT firmly on the 40-pin header.** The LEDs, OLED, and touchscreen all ride that connection — a loose seat means dark peripherals. If something doesn't light up later, re-seat the HAT first.

### 2. Flash and boot the OS
Flash **Raspberry Pi OS (Bookworm, 64-bit)** to the microSD with Raspberry Pi Imager, boot, finish first-run setup, then update:

```bash
sudo apt update && sudo apt full-upgrade -y
```

(Optionally migrate the OS to the NVMe and boot from it — recommended for daily use.)

### 3. Install the SunFounder `pironman5` software
Install per SunFounder's instructions so the OLED, fans, and dashboard come up. Confirm the OLED shows stats and the fans spin.

### 4. Install Hermes Agent
Install **Hermes Agent** and point it at your model/provider. Confirm the gateway runs and you can talk to the agent before adding embodiment.

### 5. Install this plugin + activate the Minnie persona
```bash
hermes plugins install webdevtodayjason/hermes-embodiment --enable
```

Then make Minnie the active persona — copy the showcase config over the plugin's active config:

```bash
cp ~/.hermes/plugins/embody/examples/minnie/config.yaml \
   ~/.hermes/plugins/embody/config.yaml
```

(Or, for a dev checkout: `./install.sh --minnie`.) Restart the gateway. Her face is now live at <http://localhost:8830/>.

### 6. Kiosk on the DSI touchscreen
Point a fullscreen Chromium kiosk at the face URL on the 4.3" screen, and autostart it on boot:

```bash
chromium-browser --kiosk --app=http://localhost:8830/
```

Add that to your desktop autostart (e.g. an autostart `.desktop` entry or a systemd user service) so Minnie comes up on boot. The plugin can also launch the kiosk for you — set `face.kiosk.enabled: true` in `config.yaml`.

### 7. Case LEDs — hand them over from pironman5
The plugin drives the WS2812 strip **directly over SPI** so the case reacts to agent state instantly. Two processes can't share the SPI bus, so pironman5 must release it:

- Remove `"ws2812"` from the **Pro Max variant's `PERIPHERALS`** list so pironman5's own `WS2812Addon` never opens `/dev/spidev0.0`, then restart pironman5. (OLED, fans, and dashboard are unaffected.)
- Make sure your user is in the `spi` group so the plugin can write `/dev/spidev0.0` without sudo.

> **⚠️ A `pironman5` package upgrade reinstates that list** and takes the LEDs back. After any pironman5 upgrade, **re-apply the one-line `"ws2812"` removal**. See the [Hardware notes in the README](../README.md#hardware).

### 8. Audio — let her speak
Route HDMI0 audio to the Pironman speakers: flip the Pironman **SPEAKER jumper to ON** (or connect your monitor to **HDMI1** so HDMI0 is free for audio). Then pin the audio device in `config.yaml` (`audio.device`), as the Minnie example does for HDMI. Set `ELEVENLABS_API_KEY` for her ElevenLabs voice, or leave it unset to fall back to Hermes' TTS.

---

## Verify

- **Face:** <http://localhost:8830/> shows the cat-eye face; the wordmark reads "MINNIE" when idle.
- **State:** run `/embody test` in Hermes (or hit a tool) — the face changes expression and the wordmark shows the activity ("searching the web…").
- **LEDs:** the case color tracks state (idle → blue, thinking → amber, working → purple, speaking → green).
- **Voice:** the agent speaks its replies through the case speakers.

That's Minnie — a full body for your Hermes agent. Swap the values in `config.yaml` to give her your own name, voice, theme, and LED palette.
