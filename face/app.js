/**
 * ==========================================================================
 * MINNIE AI KIOSK ENGINE (app.js)
 * High-performance, hardware-accelerated SVG face & Canvas particle system.
 * Governs 16 states including core system states and complex emotional expressions.
 * ==========================================================================
 */

// --- Global configuration ---
const CONFIG = {
  maxParticles: 420,
  baseParticleSpeed: 0.85
};

// The embody state server (SSE) emits these five states; map them onto Minnie's
// expressions. 'working' has no native expression -> use the focused 'thinking'.
// The other 11 expressions stay reachable via setState (future mood layer).
const EMBODY_STATE_MAP = {
  idle: 'idle',
  listening: 'listening',
  thinking: 'thinking',
  speaking: 'speaking',
  working: 'thinking'
};

// Friendly "what she's doing" labels for the wordmark/status line when the SSE
// message carries no explicit `status` text. Keyed by the RAW embody state so
// 'working' still reads "working…" even though it renders the thinking look.
const STATE_LABEL = {
  thinking: 'thinking…',
  working: 'working…',
  speaking: 'speaking…',
  listening: 'listening…'
};

// Supported States
const STATES = {
  // Core System States
  IDLE: 'idle',
  LISTENING: 'listening',
  THINKING: 'thinking',
  SPEAKING: 'speaking',
  ALERT: 'alert',
  SLEEPING: 'sleeping',
  
  // Emotional Expressions
  SAD: 'sad',
  HAPPY: 'happy',
  LOVING: 'loving',
  SHOCKED: 'shocked',
  ANGRY: 'angry',
  MAD: 'mad',
  FRUSTRATED: 'frustrated',
  SILLY: 'silly',
  GOOFY: 'goofy',
  EXASPERATED: 'exasperated'
};

// SVG Path Shapes for Eyebrows & Mouth (centered around left X=345, right X=655)
const SVG_PATHS = {
  eyebrows: {
    // Core States
    idle: {
      left: 'M 290 160 Q 345 125 400 160',
      right: 'M 600 160 Q 655 125 710 160'
    },
    listening: {
      left: 'M 290 155 Q 345 130 400 155',
      right: 'M 600 155 Q 655 130 710 155'
    },
    thinking: {
      left: 'M 290 145 Q 345 120 400 150',
      right: 'M 600 145 Q 655 120 710 150'
    },
    speaking: {
      left: 'M 290 150 Q 345 115 400 150',
      right: 'M 600 150 Q 655 115 710 150'
    },
    alert: {
      left: 'M 290 170 Q 345 145 400 175',
      right: 'M 600 170 Q 655 145 710 175'
    },
    sleeping: {
      left: 'M 290 165 Q 345 140 400 165',
      right: 'M 600 165 Q 655 140 710 165'
    },
    // Emotional States (Exaggerated)
    sad: {
      left: 'M 285 185 Q 340 130 395 145', // high worried slanting up-inward
      right: 'M 605 145 Q 660 130 715 185'
    },
    happy: {
      left: 'M 285 142 Q 345 105 400 142', // high happy arches
      right: 'M 600 142 Q 655 105 715 142'
    },
    loving: {
      left: 'M 290 148 Q 345 112 400 148',
      right: 'M 600 148 Q 655 112 710 148'
    },
    shocked: {
      left: 'M 285 110 Q 345 70 400 110', // extremely high raise
      right: 'M 600 110 Q 655 70 715 110'
    },
    angry: {
      left: 'M 285 162 Q 355 174 415 204', // slanted down-inward (furrowed)
      right: 'M 715 162 Q 645 174 585 204'
    },
    mad: {
      left: 'M 285 175 Q 360 178 418 214', // aggressively furrowed
      right: 'M 715 175 Q 640 178 582 214'
    },
    frustrated: {
      left: 'M 285 182 Q 350 162 400 185', // uneven/asymmetrical
      right: 'M 600 138 Q 655 122 710 155'
    },
    silly: {
      left: 'M 285 138 Q 345 105 400 138', // uneven arches
      right: 'M 600 182 Q 655 165 710 182'
    },
    goofy: {
      left: 'M 290 182 Q 355 158 395 182', // playful tilted flares
      right: 'M 605 182 Q 645 158 710 182'
    },
    exasperated: {
      left: 'M 290 170 Q 345 165 400 170', // drop flat over eyes
      right: 'M 600 170 Q 655 165 710 170'
    }
  }
};

const MOUTH_SHAPES = {
  idle: {
    closed: 'M 475 440 Q 500 458 525 440 Q 500 458 475 440 Z',
    open: (vol) => `M 475 440 Q 500 458 525 440 Q 500 ${458 + vol * 32} 475 440 Z`
  },
  listening: {
    closed: 'M 475 448 L 525 448 M 525 448 L 475 448 Z',
    open: (vol) => `M 475 448 Q 500 448 525 448 Q 500 ${448 + vol * 24} 475 448 Z`
  },
  thinking: {
    closed: 'M 488 448 C 488 456, 512 456, 512 448 C 512 440, 488 440, 488 448 Z',
    open: (vol) => {
      const rx = 12 - vol * 2;
      const ry = 8 + vol * 10;
      return `M ${500 - rx} 448 C ${500 - rx} ${448 + ry}, ${500 + rx} ${448 + ry}, ${500 + rx} 448 C ${500 + rx} ${448 - ry}, ${500 - rx} ${448 - ry}, ${500 - rx} 448 Z`;
    }
  },
  speaking: {
    closed: 'M 475 440 Q 500 458 525 440 Q 500 458 475 440 Z',
    open: (vol) => `M 475 440 Q 500 458 525 440 Q 500 ${458 + vol * 32} 475 440 Z`
  },
  alert: {
    closed: 'M 472 448 Q 500 458 528 448 Q 500 458 472 448 Z',
    open: (vol) => `M 472 448 Q 500 458 528 448 Q 500 ${458 + vol * 26} 472 448 Z`
  },
  sleeping: {
    closed: 'M 475 448 Q 500 452 525 448 Q 500 452 475 448 Z',
    open: (vol) => `M 475 448 Q 500 452 525 448 Q 500 ${452 + vol * 12} 475 448 Z`
  },
  sad: {
    closed: 'M 465 460 Q 500 435 535 460 Q 500 435 465 460 Z',
    open: (vol) => `M 465 460 Q 500 435 535 460 Q 500 ${435 + vol * 45} 465 460 Z`
  },
  happy: {
    closed: 'M 455 435 Q 500 482 545 435 Q 500 482 455 435 Z',
    open: (vol) => `M 455 435 Q 500 482 545 435 Q 500 ${482 + vol * 45} 455 435 Z`
  },
  loving: {
    closed: 'M 462 438 Q 500 472 538 438 Q 500 472 462 438 Z',
    open: (vol) => `M 462 438 Q 500 472 538 438 Q 500 ${472 + vol * 38} 462 438 Z`
  },
  shocked: {
    closed: 'M 475 440 C 475 470, 525 470, 525 440 C 525 410, 475 410, 475 440 Z',
    open: (vol) => {
      const r = 25 + vol * 12;
      return `M ${500 - r} 440 C ${500 - r} ${440 + r}, ${500 + r} ${440 + r}, ${500 + r} 440 C ${500 + r} ${440 - r}, ${500 - r} ${440 - r}, ${500 - r} 440 Z`;
    }
  },
  angry: {
    closed: 'M 472 452 Q 500 445 528 452 Q 500 445 472 452 Z',
    open: (vol) => `M 472 452 Q 500 445 528 452 Q 500 ${445 + vol * 22} 472 452 Z`
  },
  mad: {
    closed: 'M 460 464 Q 500 432 540 464 Q 500 432 460 464 Z',
    open: (vol) => `M 460 464 Q 500 432 540 464 Q 500 ${432 + vol * 40} 460 464 Z`
  },
  frustrated: {
    closed: 'M 470 448 Q 485 438, 500 448 Q 515 458, 530 448 Q 515 458, 500 448 Q 485 438, 470 448 Z',
    open: (vol) => `M 470 448 Q 485 438, 500 448 Q 515 458, 530 448 Q 500 ${458 + vol * 26} 470 448 Z`
  },
  silly: {
    closed: 'M 475 442 Q 508 464 522 434 Q 508 464 475 442 Z',
    open: (vol) => `M 475 442 Q 508 464 522 434 Q 500 ${464 + vol * 30} 475 442 Z`
  },
  goofy: {
    closed: 'M 468 432 Q 500 476 532 432 C 526 422, 474 422, 468 432 Z',
    open: (vol) => `M 468 432 Q 500 ${476 + vol * 30} 532 432 C 526 422, 474 422, 468 432 Z`
  },
  exasperated: {
    closed: 'M 480 445 C 480 458, 520 458, 520 445 C 520 435, 480 435, 480 445 Z',
    open: (vol) => {
      const sY = 1 + vol * 0.4;
      return `M 480 445 C 480 ${445 + 13 * sY}, 520 ${445 + 13 * sY}, 520 445 C 520 435, 480 435, 480 445 Z`;
    }
  }
};

// ==========================================================================
// MOOD LAYER  (rides ON TOP of the activity STATE — they are orthogonal)
// --------------------------------------------------------------------------
// STATE = what she's DOING (idle/listening/thinking/speaking/working).
// MOOD  = how she FEELS — the LOCKED 9-mood contract shared with core/mood.py
//         and the LED MOOD_COLORS. Mood is an INDEPENDENT dimension: it drives
//         the EMOTIONAL baseline (eyebrows, eye shape, pupils, mouth shape,
//         particle theme, accent glow + a one-shot spring impulse), while STATE
//         keeps driving the activity overlay + the speaking mouth's VOLUME.
//         Unknown/empty mood -> neutral, never an error.
// These reuse the EXISTING Antigravity expression tables (SVG_PATHS /
// MOUTH_SHAPES / the applyStateVisuals branches) — no new art, no animations.
// ==========================================================================
const MOODS = ['neutral', 'happy', 'excited', 'loving', 'playful', 'curious', 'sad', 'surprised', 'concerned'];
const DEFAULT_MOOD = 'neutral';

// Each contract mood -> the EXISTING expression whose tables it borrows (`expr`,
// one of the STATES looks; 'idle' = her native neutral look), plus light tuning
// the borrowed look doesn't already carry. `accent` echoes the LED mood color
// (deliverable #5 — shifts her neon hue, keeps the gradient glasses/irises so
// she's still HER). `impulse` is a one-shot spring kick on mood change; `shock`
// fires the radial particle blast (surprised).
//
// ACCENT HUES are synced to mood-core's LED palette (DEFAULT_MOOD_COLORS) so her
// face glow ≈ the case-LED hue per mood ("one being" parity). Raw LED hex is used
// verbatim EXCEPT two readability nudges (per team-lead):
//   • neutral: LED 1E3A5F (dark navy) washes out at the faint 0.08 aura alpha,
//     so neutral keeps her NATIVE purple-ish idle glow (also what the features
//     restore to) — recognizably HER.
//   • surprised: LED EAEAEA (near-white) glows as a colorless wash and loses the
//     mood signal -> nudged to a readable COOL ICY tint (#CFE8FF), same family.
const MOOD_MAP = {
  neutral:   { expr: 'idle',        accent: '#bd00ff' },                           // native idle (LED navy 1E3A5F too dark to glow)
  happy:     { expr: 'happy',       accent: '#ffc107', eyeScale: 1.05, pupilScale: 1.05 }, // LED FFC107
  excited:   { expr: 'happy',       accent: '#ff6d00', eyeScale: 1.22, pupilScale: 1.20, impulse: { nod: -18, glasses: -0.14 } }, // LED FF6D00
  loving:    { expr: 'loving',      accent: '#ff2d78' },                           // LED FF2D78
  playful:   { expr: 'silly',       accent: '#00e5ff', impulse: { tilt: 9 } },     // LED 00E5FF
  curious:   { expr: 'thinking',    accent: '#7c4dff', impulse: { tilt: 7 } },     // LED 7C4DFF
  sad:       { expr: 'sad',         accent: '#2962ff' },                           // LED 2962FF
  surprised: { expr: 'shocked',     accent: '#cfe8ff', impulse: { nod: -30, glasses: -0.24 }, shock: true }, // LED EAEAEA -> cool icy tint
  concerned: { expr: 'sad',         accent: '#ff7043', pupilScale: 0.95 }          // LED FF7043
};

// Moods that bring their OWN particle theme/motion (overrides the state's
// activity particles). Moods ABSENT here let the STATE's activity particles
// show through — so e.g. "speaking + happy" still pulses, while "speaking +
// loving" rises hearts. Values are existing particle-state names.
const MOOD_PARTICLE = {
  loving: 'loving',     // rising hearts
  sad: 'sad',           // falling teardrops
  playful: 'silly',     // floating bubbles
  curious: 'thinking'   // orbiting data digits
};

class MinnieController {
  constructor() {
    this.currentState = STATES.IDLE;
    this.currentMood = DEFAULT_MOOD; // emotional dimension, INDEPENDENT of state
    this.reduceMotion = false;       // set in init() from prefers-reduced-motion
    this.volume = 0.0;
    this.smoothedVol = 0.0; // low-passed volume that drives the mouth (anti-flicker)
    
    // Eye roll & winking state
    this.isRollingEyes = false;
    this.eyeRollStart = 0;
    this.eyeRollDuration = 800; // ms
    
    // DOM Elements
    this.faceGroup = document.getElementById('face-group');
    this.leftEye = document.getElementById('left-eye-container');
    this.rightEye = document.getElementById('right-eye-container');
    this.leftPupil = document.getElementById('left-pupil');
    this.rightPupil = document.getElementById('right-pupil');
    this.leftEyebrow = document.getElementById('left-eyebrow');
    this.rightEyebrow = document.getElementById('right-eyebrow');
    this.mouth = document.getElementById('mouth');
    
    // Double outline glasses selectors
    this.glassesBridgeGlow = document.getElementById('glasses-bridge-glow');
    this.glassesBridgeCore = document.getElementById('glasses-bridge-core');
    this.leftLensGlow = document.getElementById('left-lens-glow');
    this.leftLensCore = document.getElementById('left-lens-core');
    this.rightLensGlow = document.getElementById('right-lens-glow');
    this.rightLensCore = document.getElementById('right-lens-core');
    
    this.leftIris = document.getElementById('left-iris');
    this.rightIris = document.getElementById('right-iris');
    this.leftEyelidArch = document.getElementById('left-eyelid-arch');
    this.rightEyelidArch = document.getElementById('right-eyelid-arch');
    this.leftEyelashWing = document.getElementById('left-eyelash-wing');
    this.rightEyelashWing = document.getElementById('right-eyelash-wing');
    
    this.volumeSliderContainer = document.getElementById('volume-test-panel');
    this.volumeSlider = document.getElementById('volume-slider');
    this.volumeValText = document.getElementById('volume-val');

    // Particle Engine Canvas
    this.canvas = document.getElementById('particle-canvas');
    this.ctx = this.canvas.getContext('2d');
    this.particles = [];
    
    // Offscreen Canvases for fast glow rendering (Pi 60fps optimization)
    this.glowCanvasNormal = null;
    this.glowCanvasAmber = null;
    this.glowCanvasRed = null;
    this.glowCanvasPink = null;
    this.glowCanvasBlue = null;
    this.glowCanvasBubble = null;
    this.glowCanvasThinking0 = null;
    this.glowCanvasThinking1 = null;

    // Glasses group selector for secondary squash transform
    this.glassesGroup = document.getElementById('glasses');

    // Pupil position & scale states (Supports Asymmetric crossed-eyes / dilation)
    this.pupils = {
      left: {
        current: { x: 0, y: 0 },
        target: { x: 0, y: 0 },
        currentScale: 1.0,
        targetScale: 1.0
      },
      right: {
        current: { x: 0, y: 0 },
        target: { x: 0, y: 0 },
        currentScale: 1.0,
        targetScale: 1.0
      }
    };
    
    // Spring physics configuration for organic wobbling head sways & jolts
    this.headSpring = {
      tilt: 0,
      tiltVel: 0,
      targetTilt: 0,
      nod: 0,
      nodVel: 0,
      targetNod: 0,
      sway: 0,
      swayVel: 0,
      targetSway: 0,
      k: 0.08,      // spring stiffness constant
      damping: 0.76  // spring damping factor (0.76 is a nice elastic wobble)
    };

    // Spring physics configuration for glasses squishing
    this.glassesSpring = {
      scaleY: 1.0,
      velY: 0.0,
      targetScaleY: 1.0,
      k: 0.12,
      damping: 0.72
    };

    // Scheduled Timers
    this.blinkTimer = null;
    this.lookTimer = null;
    this.headTimer = null;
    this.speakingMockInterval = null;

    this.init();
  }

  init() {
    // Live status wordmark state (driven by /config + SSE `status` field).
    this.wordmarkEl = document.getElementById('persona-name');
    this.personaName = 'MINNIE';
    this.lastStatus = '';

    // ?debug reveals the test control panels + volume slider; the kiosk hides them.
    try {
      if (new URLSearchParams(location.search).has('debug')) {
        document.body.classList.add('debug');
      }
    } catch (e) {}

    // Honor prefers-reduced-motion: skip the one-shot mood spring impulses (the
    // CSS already calms transitions/keyframes; the ambient rAF physics stay per
    // the byte-for-byte directive).
    try {
      this.reduceMotion = !!(window.matchMedia &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (e) { this.reduceMotion = false; }

    this.setupOffscreenCanvases();
    this.setupCanvasSize();
    window.addEventListener('resize', () => this.setupCanvasSize());

    this.initParticles();
    this.bindEvents();
    this.startLoop();

    // Set initial state
    this.transitionToState(STATES.IDLE);

    // Offline dev preview: ?state=speaking (also accepts embody names).
    try {
      const forced = new URLSearchParams(location.search).get('state');
      if (forced) this.transitionToState(EMBODY_STATE_MAP[forced] || forced);
    } catch (e) {}

    // Offline dev preview: ?mood=loving (independent of ?state). Unknown -> neutral.
    try {
      const forcedMood = new URLSearchParams(location.search).get('mood');
      if (forcedMood !== null) this.setMood(forcedMood);
    } catch (e) {}

    // Live wiring to the embody plugin's state server.
    this.loadConfig();
    this.connectSSE();

    // Reconnect promptly when the kiosk tab regains visibility.
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && (!this.es || this.es.readyState === 2)) {
        this.sseBackoff = 1000;
        this.connectSSE();
      }
    });

    // Re-measure the face once layout/fonts have settled so the aura locks on.
    requestAnimationFrame(() => this.updateFaceMetrics());
    window.addEventListener('load', () => this.updateFaceMetrics());
  }

  setupOffscreenCanvases() {
    // 1. Normal (Glowing cyan/purple digital crosshairs)
    this.glowCanvasNormal = document.createElement('canvas');
    this.glowCanvasNormal.width = 32;
    this.glowCanvasNormal.height = 32;
    const ctxNormal = this.glowCanvasNormal.getContext('2d');
    ctxNormal.strokeStyle = 'rgba(189, 0, 255, 0.5)';
    ctxNormal.lineWidth = 1;
    ctxNormal.beginPath();
    ctxNormal.moveTo(16, 4); ctxNormal.lineTo(16, 28);
    ctxNormal.moveTo(4, 16); ctxNormal.lineTo(28, 16);
    ctxNormal.stroke();
    
    let gradN = ctxNormal.createRadialGradient(16, 16, 0, 16, 16, 14);
    gradN.addColorStop(0, 'rgba(255, 255, 255, 1)');
    gradN.addColorStop(0.3, 'rgba(0, 240, 255, 0.85)');
    gradN.addColorStop(0.7, 'rgba(189, 0, 255, 0.25)');
    gradN.addColorStop(1, 'rgba(189, 0, 255, 0)');
    ctxNormal.fillStyle = gradN;
    ctxNormal.beginPath();
    ctxNormal.arc(16, 16, 14, 0, Math.PI * 2);
    ctxNormal.fill();

    // 2. Amber (Alert state - warning triangles)
    this.glowCanvasAmber = document.createElement('canvas');
    this.glowCanvasAmber.width = 32;
    this.glowCanvasAmber.height = 32;
    const ctxAmber = this.glowCanvasAmber.getContext('2d');
    ctxAmber.fillStyle = 'rgba(255, 170, 0, 0.9)';
    ctxAmber.shadowColor = 'rgba(255, 170, 0, 0.7)';
    ctxAmber.shadowBlur = 5;
    ctxAmber.beginPath();
    ctxAmber.moveTo(16, 4);
    ctxAmber.lineTo(28, 26);
    ctxAmber.lineTo(4, 26);
    ctxAmber.closePath();
    ctxAmber.fill();

    // 3. Hot Red (Angry/Mad states - sharp vertical flame sparks)
    this.glowCanvasRed = document.createElement('canvas');
    this.glowCanvasRed.width = 32;
    this.glowCanvasRed.height = 32;
    const ctxRed = this.glowCanvasRed.getContext('2d');
    ctxRed.fillStyle = 'rgba(255, 0, 60, 0.95)';
    ctxRed.shadowColor = 'rgba(255, 0, 60, 0.8)';
    ctxRed.shadowBlur = 5;
    ctxRed.beginPath();
    ctxRed.moveTo(16, 2);
    ctxRed.lineTo(22, 16);
    ctxRed.lineTo(16, 30);
    ctxRed.lineTo(10, 16);
    ctxRed.closePath();
    ctxRed.fill();

    // 4. Soft Pink (Loving state - glowing hearts)
    this.glowCanvasPink = document.createElement('canvas');
    this.glowCanvasPink.width = 32;
    this.glowCanvasPink.height = 32;
    const ctxPink = this.glowCanvasPink.getContext('2d');
    ctxPink.fillStyle = 'rgba(255, 42, 133, 0.95)';
    ctxPink.shadowColor = 'rgba(255, 42, 133, 0.7)';
    ctxPink.shadowBlur = 4;
    ctxPink.beginPath();
    ctxPink.moveTo(16, 11);
    ctxPink.bezierCurveTo(16, 7, 10, 5, 10, 11);
    ctxPink.bezierCurveTo(10, 17, 16, 23, 16, 27);
    ctxPink.bezierCurveTo(16, 23, 22, 17, 22, 11);
    ctxPink.bezierCurveTo(22, 5, 16, 7, 16, 11);
    ctxPink.fill();

    // 5. Deep Blue (Sad state - falling teardrops)
    this.glowCanvasBlue = document.createElement('canvas');
    this.glowCanvasBlue.width = 32;
    this.glowCanvasBlue.height = 32;
    const ctxBlue = this.glowCanvasBlue.getContext('2d');
    ctxBlue.fillStyle = 'rgba(0, 102, 255, 0.9)';
    ctxBlue.shadowColor = 'rgba(0, 102, 255, 0.7)';
    ctxBlue.shadowBlur = 4;
    ctxBlue.beginPath();
    ctxBlue.moveTo(16, 4);
    ctxBlue.bezierCurveTo(10, 15, 10, 23, 16, 27);
    ctxBlue.bezierCurveTo(22, 23, 22, 15, 16, 4);
    ctxBlue.closePath();
    ctxBlue.fill();

    // 6. Cyan Bubbles (Goofy/Silly states - outline rings with a glint)
    this.glowCanvasBubble = document.createElement('canvas');
    this.glowCanvasBubble.width = 32;
    this.glowCanvasBubble.height = 32;
    const ctxBubble = this.glowCanvasBubble.getContext('2d');
    ctxBubble.strokeStyle = 'rgba(0, 240, 255, 0.85)';
    ctxBubble.shadowColor = 'rgba(0, 240, 255, 0.5)';
    ctxBubble.shadowBlur = 4;
    ctxBubble.lineWidth = 1.5;
    ctxBubble.beginPath();
    ctxBubble.arc(16, 16, 9, 0, Math.PI * 2);
    ctxBubble.stroke();
    ctxBubble.fillStyle = 'rgba(255, 255, 255, 0.9)';
    ctxBubble.beginPath();
    ctxBubble.arc(12, 12, 2.5, 0, Math.PI * 2);
    ctxBubble.fill();

    // 7. Thinking Data 0 (Binary zero)
    this.glowCanvasThinking0 = document.createElement('canvas');
    this.glowCanvasThinking0.width = 32;
    this.glowCanvasThinking0.height = 32;
    const ctxT0 = this.glowCanvasThinking0.getContext('2d');
    ctxT0.fillStyle = 'rgba(0, 240, 255, 0.95)';
    ctxT0.shadowColor = 'rgba(0, 240, 255, 0.8)';
    ctxT0.shadowBlur = 4;
    ctxT0.font = 'bold 20px monospace';
    ctxT0.textAlign = 'center';
    ctxT0.textBaseline = 'middle';
    ctxT0.fillText('0', 16, 16);

    // 8. Thinking Data 1 (Binary one)
    this.glowCanvasThinking1 = document.createElement('canvas');
    this.glowCanvasThinking1.width = 32;
    this.glowCanvasThinking1.height = 32;
    const ctxT1 = this.glowCanvasThinking1.getContext('2d');
    ctxT1.fillStyle = 'rgba(0, 240, 255, 0.95)';
    ctxT1.shadowColor = 'rgba(0, 240, 255, 0.8)';
    ctxT1.shadowBlur = 4;
    ctxT1.font = 'bold 20px monospace';
    ctxT1.textAlign = 'center';
    ctxT1.textBaseline = 'middle';
    ctxT1.fillText('1', 16, 16);
  }

  setupCanvasSize() {
    this.canvas.width = window.innerWidth;
    this.canvas.height = window.innerHeight;
    this.updateFaceMetrics();
  }

  // Anchor the particle aura + emitters to the ACTUAL on-screen face, so the
  // glow stays centred on her at any size/aspect (replaces the hard-pinned
  // innerWidth/2, innerHeight*0.40 and the fixed svgScale). The viewBox face
  // centre (500, 290) is exactly the SVG box centre, so we read its rect.
  updateFaceMetrics() {
    let r = null;
    try {
      const svg = document.getElementById('face-svg');
      r = svg && svg.getBoundingClientRect();
    } catch (e) {}
    if (r && r.width > 1 && r.height > 1) {
      this.faceCx = r.left + r.width * 0.5;
      this.faceCy = r.top + r.height * 0.5;
      this.faceScale = r.width / 1000; // viewBox is 1000 units wide
    } else {
      this.faceCx = window.innerWidth * 0.5;
      this.faceCy = window.innerHeight * 0.4;
      this.faceScale = (window.innerWidth / 1000) * 0.5 || 0.45;
    }
  }

  bindEvents() {
    this.volumeSlider.addEventListener('input', (e) => {
      const val = parseFloat(e.target.value);
      this.volumeValText.textContent = val.toFixed(2);
      this.setVolume(val);
    });
  }

  // --- Particle Aura System ---
  initParticles() {
    this.particles = [];
    const cx = this.faceCx;
    const cy = this.faceCy;

    for (let i = 0; i < CONFIG.maxParticles; i++) {
      const angle = Math.random() * Math.PI * 2;
      const dist = 90 + Math.random() * 260;
      this.particles.push({
        x: cx + Math.cos(angle) * dist,
        y: cy + Math.sin(angle) * dist,
        baseX: cx,
        baseY: cy,
        angle: angle,
        orbitRadius: dist,
        orbitSpeed: (0.0006 + Math.random() * 0.001) * (Math.random() > 0.5 ? 1 : -1),
        vx: (Math.random() - 0.5) * CONFIG.baseParticleSpeed,
        vy: (Math.random() - 0.5) * CONFIG.baseParticleSpeed,
        size: 0.8 + Math.random() * 3.5, // elegant fine stardust
        alpha: 0.1 + Math.random() * 0.65,
        baseAlpha: 0.1 + Math.random() * 0.65,
        phase: Math.random() * Math.PI * 2
      });
    }
  }

  updateParticles() {
    const cx = this.faceCx;
    const cy = this.faceCy;
    
    // Particle theme/motion follows particleExpr(): a mood's signature theme when
    // it has one (hearts/tears/bubbles/orbit), else the activity state — so the
    // speaking/listening auras still play under non-signature moods. At
    // mood=neutral this === currentState, i.e. unchanged from before.
    const pexpr = this.particleExpr();
    const isAlert = pexpr === STATES.ALERT;
    const isThinking = pexpr === STATES.THINKING;
    const isListening = pexpr === STATES.LISTENING;
    const isSpeaking = pexpr === STATES.SPEAKING;
    const isSleeping = pexpr === STATES.SLEEPING;
    const isSad = pexpr === STATES.SAD;
    const isLoving = pexpr === STATES.LOVING;
    const isAngry = pexpr === STATES.ANGRY || pexpr === STATES.MAD;
    const isShocked = pexpr === STATES.SHOCKED;
    const isGoofy = pexpr === STATES.GOOFY;
    const isSilly = pexpr === STATES.SILLY;

    for (let i = 0; i < this.particles.length; i++) {
      const p = this.particles[i];
      p.baseX = cx;
      p.baseY = cy;
      p.phase += 0.025;

      // Select glowing particle canvas based on state colors
      let img = this.glowCanvasNormal;
      if (isAlert) img = this.glowCanvasAmber;
      else if (isAngry) img = this.glowCanvasRed;
      else if (isLoving) img = this.glowCanvasPink;
      else if (isSad) img = this.glowCanvasBlue;
      else if (isThinking) {
        img = (i % 2 === 0) ? this.glowCanvasThinking0 : this.glowCanvasThinking1;
      } else if (isGoofy || isSilly) {
        img = this.glowCanvasBubble;
      }

      if (isSleeping) {
        // Slow float, lower opacity
        p.x += p.vx * 0.15;
        p.y += p.vy * 0.15;
        p.alpha = p.baseAlpha * 0.22;
        
        if (p.x < 0 || p.x > this.canvas.width) p.vx *= -1;
        if (p.y < 0 || p.y > this.canvas.height) p.vy *= -1;
        
      } else if (isSad) {
        // Falling tears / rain mode physics (dripping from eyes!)
        p.vy += 0.08; // gravity downward drift
        p.vx *= 0.95; // drag horizontal
        p.vy = Math.min(p.vy, 3.5); // terminal velocity
        
        p.x += p.vx * 0.70;
        p.y += p.vy * 0.70;
        p.alpha -= 0.0035; // fade as it falls
        
        // Recycle at the eye coordinates
        if (p.y > this.canvas.height || p.alpha <= 0) {
          const svgScale = this.faceScale;
          const fromLeftEye = Math.random() > 0.5;
          p.x = (fromLeftEye ? cx - 155 * svgScale : cx + 155 * svgScale) + (Math.random() - 0.5) * 16;
          p.y = cy + 5 * svgScale + (Math.random() - 0.5) * 6;
          p.vy = 0.3 + Math.random() * 0.7;
          p.vx = (Math.random() - 0.5) * 0.3;
          p.alpha = p.baseAlpha * 0.8;
        }

      } else if (isAngry) {
        // Sparks / embers flying upward from the glasses frames
        p.vy -= 0.09; // upward lift
        p.vx += (Math.random() - 0.5) * 0.4; // horizontal drift
        p.vx *= 0.92; // drag
        p.vy = Math.max(p.vy, -3.5); // max upward velocity
        
        p.x += p.vx * 0.75;
        p.y += p.vy * 0.75;
        p.alpha -= 0.006; // quick fadeout
        
        if (p.y < 0 || p.alpha <= 0) {
          const svgScale = this.faceScale;
          const glassesWidth = 560 * svgScale;
          p.x = cx + (Math.random() - 0.5) * glassesWidth;
          p.y = cy + (Math.random() - 0.5) * 35;
          p.vy = -0.4 - Math.random() * 1.5;
          p.vx = (Math.random() - 0.5) * 0.8;
          p.alpha = p.baseAlpha * 1.25;
        }

      } else if (isLoving) {
        // Slow rising hearts with horizontal drift sways
        p.vy = -0.5 - Math.random() * 0.5; // slow upward drift
        p.angle += 0.025;
        p.x = p.baseX + Math.sin(p.angle) * p.orbitRadius * 1.2; // drift sway
        
        p.y += p.vy * 0.7;
        p.alpha -= 0.0016; // gradual fadeout
        
        if (p.y < 0 || p.alpha <= 0) {
          p.y = this.canvas.height * 0.95;
          p.x = cx + (Math.random() - 0.5) * 380;
          p.angle = Math.random() * Math.PI * 2;
          p.alpha = p.baseAlpha;
        }

      } else if (isGoofy || isSilly) {
        // Floating wobbly bubbles
        p.vx += (Math.random() - 0.5) * 0.16;
        p.vy -= 0.012; // slow rise
        p.vx *= 0.96;
        p.vy *= 0.96;
        p.x += p.vx + Math.sin(p.phase * 0.18) * 0.45;
        p.y += p.vy - 0.45;
        
        if (p.y < -30) {
          p.y = this.canvas.height + 30;
          p.x = Math.random() * this.canvas.width;
          p.vx = (Math.random() - 0.5) * 0.9;
          p.vy = -0.4 - Math.random() * 0.9;
        }

      } else if (isThinking) {
        // Orbit mode around face center (Binary digits revolving)
        p.angle += p.orbitSpeed * 1.75;
        const targetX = cx + Math.cos(p.angle) * p.orbitRadius;
        const targetY = cy + Math.sin(p.angle) * p.orbitRadius;
        
        p.x += (targetX - p.x) * 0.065;
        p.y += (targetY - p.y) * 0.065;
        p.alpha = p.baseAlpha * (0.8 + Math.sin(p.phase) * 0.2);
        
      } else if (isListening) {
        // Gravity inward mode
        const dx = cx - p.x;
        const dy = cy - p.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        
        const pull = 0.18;
        p.vx += (dx / dist) * pull;
        p.vy += (dy / dist) * pull;
        
        p.vx *= 0.88;
        p.vy *= 0.88;
        p.x += p.vx;
        p.y += p.vy;
        
        p.alpha = p.baseAlpha * (0.9 + Math.sin(p.phase) * 0.1);
        
        // Recycle far out if too close to face
        if (dist < 75) {
          const angle = Math.random() * Math.PI * 2;
          const r = 360 + Math.random() * 90;
          p.x = cx + Math.cos(angle) * r;
          p.y = cy + Math.sin(angle) * r;
          p.vx = (Math.random() - 0.5) * CONFIG.baseParticleSpeed;
          p.vy = (Math.random() - 0.5) * CONFIG.baseParticleSpeed;
        }

      } else if (isAlert) {
        // Tight, fast orbits
        p.angle += p.orbitSpeed * 3.4;
        const targetX = cx + Math.cos(p.angle) * (p.orbitRadius * 0.72);
        const targetY = cy + Math.sin(p.angle) * (p.orbitRadius * 0.72);
        
        p.x += (targetX - p.x) * 0.14;
        p.y += (targetY - p.y) * 0.14;
        p.alpha = p.baseAlpha * (0.95 + Math.sin(p.phase * 2) * 0.05);

      } else if (isSpeaking) {
        // Pulse speed and size with volume
        p.x += p.vx * (1 + this.volume * 2.4);
        p.y += p.vy * (1 + this.volume * 2.4);
        
        p.alpha = Math.min(1.0, p.baseAlpha * (1.0 + this.volume * 1.6));
        
        if (p.x < 0 || p.x > this.canvas.width) p.vx *= -1;
        if (p.y < 0 || p.y > this.canvas.height) p.vy *= -1;

      } else {
        // IDLE & Normal float states (Friction decay for shockwave blasts)
        p.vx += ((Math.random() - 0.5) * CONFIG.baseParticleSpeed - p.vx) * 0.05;
        p.vy += ((Math.random() - 0.5) * CONFIG.baseParticleSpeed - p.vy) * 0.05;
        p.x += p.vx;
        p.y += p.vy;
        
        p.alpha = p.baseAlpha * (0.6 + Math.sin(p.phase * 0.55) * 0.4);
        
        if (p.x < 0 || p.x > this.canvas.width) p.vx *= -1;
        if (p.y < 0 || p.y > this.canvas.height) p.vy *= -1;
      }

      // Draw particle
      const drawSize = p.size * (isSpeaking ? (1 + this.volume * 0.8) : 1);
      this.ctx.globalAlpha = p.alpha;
      this.ctx.drawImage(img, p.x - drawSize/2, p.y - drawSize/2, drawSize, drawSize);
    }
  }

  // --- WebSocket Connection ---
  // --- Live state stream: Server-Sent Events from the embody plugin ---
  // GET /events -> messages `data: {"state":"<name>", "status":"<optional>"}`.
  // Auto-reconnect with capped exponential backoff; visibility reconnect in init().
  connectSSE() {
    if (this.sseRetry) { clearTimeout(this.sseRetry); this.sseRetry = null; }
    if (!window.EventSource) return; // ancient browser: stay idle, no errors
    if (this.es) { try { this.es.close(); } catch (e) {} this.es = null; }
    if (this.sseBackoff == null) this.sseBackoff = 1000;

    try {
      this.es = new EventSource('/events');
    } catch (e) {
      this.scheduleSSEReconnect();
      return;
    }

    this.es.onopen = () => { this.sseBackoff = 1000; };

    this.es.onmessage = (event) => {
      if (!event || !event.data) return;
      let raw, status = '', moodPresent = false, moodVal = null;
      try {
        const data = JSON.parse(event.data);
        raw = (typeof data.state === 'string') ? data.state.toLowerCase() : null;
        if (typeof data.status === 'string') status = data.status.trim();
        if (data.volume !== undefined && data.volume !== null) {
          this.setVolume(parseFloat(data.volume));
        }
        // MOOD layer: independent of state. Apply ONLY when the field is present
        // (old frames omit `mood` -> leave the current mood untouched). Empty or
        // unknown -> neutral inside setMood. The connect-sync snapshot frame
        // carries mood too, so it lands here as well.
        if (Object.prototype.hasOwnProperty.call(data, 'mood')) {
          moodPresent = true;
          moodVal = data.mood;
        }
      } catch (err) {
        raw = String(event.data).trim().toLowerCase(); // tolerate a bare token
      }
      // Mood is orthogonal to state — apply it even on a mood-only frame.
      if (moodPresent) this.setMood(moodVal);
      if (!raw) return;
      this.transitionToState(EMBODY_STATE_MAP[raw] || raw);
      // wordmark uses the RAW embody state (so 'working' reads "working…")
      this.applyWordmark(raw, status);
    };

    this.es.onerror = () => {
      if (this.es) { try { this.es.close(); } catch (e) {} this.es = null; }
      this.scheduleSSEReconnect();
    };
  }

  scheduleSSEReconnect() {
    if (this.sseRetry) clearTimeout(this.sseRetry);
    const delay = this.sseBackoff || 1000;
    this.sseRetry = setTimeout(() => this.connectSSE(), delay);
    this.sseBackoff = Math.min(delay * 2, 10000);
  }

  // --- Persona name from /config (graceful 404 -> keep MINNIE) ---
  loadConfig() {
    if (!window.fetch) return;
    fetch('/config', { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : null))
      .then((cfg) => {
        if (!cfg || !cfg.persona) return;
        const name = cfg.persona.name;
        // ignore the server's generic default so we never regress to "ASSISTANT"
        if (!name || String(name).trim().toLowerCase() === 'assistant') return;
        this.personaName = String(name).toUpperCase();
        if (this.currentState === STATES.IDLE) this.applyWordmark('idle', '');
      })
      .catch(() => { /* no server — keep MINNIE, stay idle */ });
  }

  // --- Live status wordmark: idle -> name, active -> status / state label ---
  applyWordmark(stateForLabel, status) {
    this.lastStatus = status || '';
    let text;
    if (stateForLabel === 'idle' || stateForLabel === 'sleeping') {
      text = this.personaName;
    } else if (this.lastStatus) {
      text = this.lastStatus;
    } else {
      text = STATE_LABEL[stateForLabel] || this.personaName;
    }
    this.setWordmarkText(text);
  }

  setWordmarkText(text) {
    const el = this.wordmarkEl;
    if (!el || el.textContent === text) return;
    el.style.opacity = '0';
    if (this._wmTimer) clearTimeout(this._wmTimer);
    this._wmTimer = setTimeout(() => {
      el.textContent = text;
      el.style.opacity = '1';
    }, 170);
  }

  // --- State Machine transitions ---
  transitionToState(state) {
    if (!Object.values(STATES).includes(state)) {
      console.warn(`Minnie: Invalid state "${state}"`);
      return;
    }

    console.log(`Minnie state transition: ${this.currentState} -> ${state}`);
    this.currentState = state;

    // Reset indicator buttons styles
    document.querySelectorAll('.status-btn').forEach(btn => btn.classList.remove('active'));
    const activeBtn = document.getElementById(`btn-${state}`);
    if (activeBtn) activeBtn.classList.add('active');

    // Start or stop automatic speaking simulation (volume slider is always visible in CSS)
    if (state === STATES.SPEAKING) {
      this.startSpeakingSimulation();
    } else {
      this.stopSpeakingSimulation();
      // fromMock: reset volume to 0 WITHOUT writing the slider, so it stays at
      // its "0.5" default and the speaking mock's gate keeps working next time.
      this.setVolume(0.0, true);
    }

    // Physical Mood Transition Jolt / Startle Reaction using spring velocities
    if (state === STATES.SHOCKED) {
      this.headSpring.nodVel = -36;    // rapid upward startle jolt
      this.headSpring.tiltVel = (Math.random() - 0.5) * 18;
      this.headSpring.swayVel = (Math.random() - 0.5) * 12;
      this.glassesSpring.velY = -0.28; // extreme glasses jolt
    } else if (state === STATES.MAD || state === STATES.ALERT) {
      this.headSpring.nodVel = -22;
      this.headSpring.tiltVel = (Math.random() - 0.5) * 10;
      this.glassesSpring.velY = -0.16;
    } else if (state === STATES.ANGRY) {
      this.headSpring.nodVel = -14;
      this.headSpring.tiltVel = (Math.random() - 0.5) * 8;
    } else if (state === STATES.SAD || state === STATES.EXASPERATED) {
      this.headSpring.nodVel = 26;     // heavy downward energy drop
      this.headSpring.tiltVel = (Math.random() - 0.5) * 6;
    } else if (state !== STATES.SLEEPING) {
      this.headSpring.nodVel = (Math.random() - 0.5) * 8;
      this.headSpring.tiltVel = (Math.random() - 0.5) * 6;
    }

    // Shockwave Particle Explosion for SHOCKED State
    if (state === STATES.SHOCKED) {
      const cx = this.faceCx;
      const cy = this.faceCy;
      this.particles.forEach(p => {
        const dx = p.x - cx;
        const dy = p.y - cy;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        // Radial blast velocity vector
        p.vx = (dx / dist) * (6 + Math.random() * 8);
        p.vy = (dy / dist) * (6 + Math.random() * 8);
      });
    }

    // Reset eyelid blink transitions
    this.leftEye.classList.remove('blink-active', 'wink-left');
    this.rightEye.classList.remove('blink-active', 'wink-right');

    // Update visuals
    this.applyStateVisuals();

    // Re-schedule look arounds and winks
    this.rescheduleTimers();

    // Wordmark/status line for manual + dev-hook transitions (no SSE status).
    // The SSE handler calls applyWordmark() again afterward with the raw embody
    // state + status text, which wins.
    if (this.wordmarkEl) this.applyWordmark(state, '');
  }

  applyStateVisuals() {
    // Render the EMOTIONAL baseline by the EFFECTIVE expression: the active
    // mood's mapped look when a mood is set, else the raw activity state. With
    // mood=neutral, effExpr() === currentState, so this is byte-identical to the
    // pre-mood behavior. STATE still owns the activity overlay (particles motion,
    // speaking-mouth volume, timers, breathing/hover) — see particleExpr()/loop.
    const expr = this.effExpr();
    const isAlert = expr === STATES.ALERT;
    const isSleeping = expr === STATES.SLEEPING;
    const isThinking = expr === STATES.THINKING;
    const isListening = expr === STATES.LISTENING;
    const isSad = expr === STATES.SAD;
    const isLoving = expr === STATES.LOVING;
    const isAngry = expr === STATES.ANGRY || expr === STATES.MAD;
    const isShocked = expr === STATES.SHOCKED;
    const isGoofy = expr === STATES.GOOFY;
    const isSilly = expr === STATES.SILLY;

    // Apply path shapes for Eyebrows & Mouth (guarded: unknown -> idle)
    const eyebrows = SVG_PATHS.eyebrows[expr] || SVG_PATHS.eyebrows.idle;
    const mouthShape = MOUTH_SHAPES[expr] || MOUTH_SHAPES.idle;
    this.leftEyebrow.setAttribute('d', eyebrows.left);
    this.rightEyebrow.setAttribute('d', eyebrows.right);
    this.mouth.setAttribute('d', mouthShape.open(this.volume));

    // Reset default pupil scale properties
    this.pupils.left.targetScale = 1.0;
    this.pupils.right.targetScale = 1.0;

    // Apply color changes & shapes
    if (isAlert) {
      // Amber mode
      this.glassesBridgeGlow.setAttribute('stroke', 'url(#glasses-gradient-alert-glow)');
      this.glassesBridgeGlow.setAttribute('filter', 'url(#neon-glow-amber)');
      this.glassesBridgeCore.setAttribute('stroke', 'url(#glasses-gradient-alert-core)');
      this.glassesBridgeCore.setAttribute('filter', 'url(#neon-glow-cyan)');

      this.leftLensGlow.setAttribute('stroke', 'url(#glasses-gradient-alert-glow)');
      this.leftLensGlow.setAttribute('filter', 'url(#neon-glow-amber)');
      this.leftLensCore.setAttribute('stroke', 'url(#glasses-gradient-alert-core)');
      this.leftLensCore.setAttribute('filter', 'url(#neon-glow-cyan)');
      
      this.rightLensGlow.setAttribute('stroke', 'url(#glasses-gradient-alert-glow)');
      this.rightLensGlow.setAttribute('filter', 'url(#neon-glow-amber)');
      this.rightLensCore.setAttribute('stroke', 'url(#glasses-gradient-alert-core)');
      this.rightLensCore.setAttribute('filter', 'url(#neon-glow-cyan)');
      
      this.leftEyebrow.setAttribute('stroke', '#ffaa00');
      this.leftEyebrow.setAttribute('filter', 'url(#neon-glow-amber)');
      this.rightEyebrow.setAttribute('stroke', '#ffaa00');
      this.rightEyebrow.setAttribute('filter', 'url(#neon-glow-amber)');
      
      this.leftIris.setAttribute('fill', 'url(#iris-gradient-alert)');
      this.rightIris.setAttribute('fill', 'url(#iris-gradient-alert)');

      this.leftEyelidArch.setAttribute('stroke', '#ffaa00');
      this.leftEyelidArch.setAttribute('filter', 'url(#neon-glow-amber)');
      this.rightEyelidArch.setAttribute('stroke', '#ffaa00');
      this.rightEyelidArch.setAttribute('filter', 'url(#neon-glow-amber)');

      this.leftEyelashWing.setAttribute('fill', '#ffaa00');
      this.leftEyelashWing.setAttribute('filter', 'url(#neon-glow-amber)');
      this.rightEyelashWing.setAttribute('fill', '#ffaa00');
      this.rightEyelashWing.setAttribute('filter', 'url(#neon-glow-amber)');

      // Narrowed eyes
      this.leftEye.style.transform = 'scaleY(0.72) rotate(3deg)';
      this.rightEye.style.transform = 'scaleY(0.72) rotate(-3deg)';
      this.headSpring.targetTilt = 0;
      this.headSpring.targetNod = 5;
      this.headSpring.targetSway = 0;
      this.pupils.left.targetScale = 0.85;
      this.pupils.right.targetScale = 0.85;

    } else if (isAngry) {
      // Hot red anger/mad mode
      this.glassesBridgeGlow.setAttribute('stroke', 'url(#glasses-gradient-red-glow)');
      this.glassesBridgeGlow.setAttribute('filter', 'url(#neon-glow-red)');
      this.glassesBridgeCore.setAttribute('stroke', 'url(#glasses-gradient-red-core)');
      this.glassesBridgeCore.setAttribute('filter', 'url(#neon-glow-cyan)');

      this.leftLensGlow.setAttribute('stroke', 'url(#glasses-gradient-red-glow)');
      this.leftLensGlow.setAttribute('filter', 'url(#neon-glow-red)');
      this.leftLensCore.setAttribute('stroke', 'url(#glasses-gradient-red-core)');
      this.leftLensCore.setAttribute('filter', 'url(#neon-glow-cyan)');
      
      this.rightLensGlow.setAttribute('stroke', 'url(#glasses-gradient-red-glow)');
      this.rightLensGlow.setAttribute('filter', 'url(#neon-glow-red)');
      this.rightLensCore.setAttribute('stroke', 'url(#glasses-gradient-red-core)');
      this.rightLensCore.setAttribute('filter', 'url(#neon-glow-cyan)');
      
      this.leftEyebrow.setAttribute('stroke', '#ff0055');
      this.leftEyebrow.setAttribute('filter', 'url(#neon-glow-red)');
      this.rightEyebrow.setAttribute('stroke', '#ff0055');
      this.rightEyebrow.setAttribute('filter', 'url(#neon-glow-red)');
      
      this.leftIris.setAttribute('fill', 'url(#iris-gradient-red)');
      this.rightIris.setAttribute('fill', 'url(#iris-gradient-red)');

      this.leftEyelidArch.setAttribute('stroke', '#ff0055');
      this.leftEyelidArch.setAttribute('filter', 'url(#neon-glow-red)');
      this.rightEyelidArch.setAttribute('stroke', '#ff0055');
      this.rightEyelidArch.setAttribute('filter', 'url(#neon-glow-red)');

      this.leftEyelashWing.setAttribute('fill', '#ff0055');
      this.leftEyelashWing.setAttribute('filter', 'url(#neon-glow-red)');
      this.rightEyelashWing.setAttribute('fill', '#ff0055');
      this.rightEyelashWing.setAttribute('filter', 'url(#neon-glow-red)');

      // Furrowed narrowed eyes
      const isMad = this.effExpr() === STATES.MAD;
      const eyeNarrow = isMad ? 0.52 : 0.68;
      const rot = isMad ? 7 : 5;
      this.leftEye.style.transform = `scaleY(${eyeNarrow}) rotate(${rot}deg)`;
      this.rightEye.style.transform = `scaleY(${eyeNarrow}) rotate(${-rot}deg)`;
      
      this.headSpring.targetTilt = isMad ? -4 : 0;
      this.headSpring.targetNod = isMad ? 7 : 5;
      this.headSpring.targetSway = isMad ? -6 : 0;
      
      this.pupils.left.targetScale = isMad ? 0.72 : 0.82;
      this.pupils.right.targetScale = isMad ? 0.72 : 0.82;

    } else if (isSad) {
      // Deep blue worried mode
      this.glassesBridgeGlow.setAttribute('stroke', 'url(#glasses-gradient-glow)');
      this.glassesBridgeGlow.setAttribute('filter', 'url(#neon-glow-purple)');
      this.glassesBridgeCore.setAttribute('stroke', 'url(#glasses-gradient-core)');
      this.glassesBridgeCore.setAttribute('filter', 'url(#neon-glow-cyan)');

      this.leftLensGlow.setAttribute('stroke', 'url(#glasses-gradient-glow)');
      this.leftLensGlow.setAttribute('filter', 'url(#neon-glow-purple)');
      this.leftLensCore.setAttribute('stroke', 'url(#glasses-gradient-core)');
      this.leftLensCore.setAttribute('filter', 'url(#neon-glow-cyan)');
      
      this.rightLensGlow.setAttribute('stroke', 'url(#glasses-gradient-glow)');
      this.rightLensGlow.setAttribute('filter', 'url(#neon-glow-purple)');
      this.rightLensCore.setAttribute('stroke', 'url(#glasses-gradient-core)');
      this.rightLensCore.setAttribute('filter', 'url(#neon-glow-cyan)');
      
      this.leftEyebrow.setAttribute('stroke', '#0066ff');
      this.leftEyebrow.setAttribute('filter', 'url(#neon-glow-cyan)');
      this.rightEyebrow.setAttribute('stroke', '#0066ff');
      this.rightEyebrow.setAttribute('filter', 'url(#neon-glow-cyan)');
      
      this.leftIris.setAttribute('fill', 'url(#iris-gradient-left)');
      this.rightIris.setAttribute('fill', 'url(#iris-gradient-right)');

      this.leftEyelidArch.setAttribute('stroke', '#0066ff');
      this.leftEyelidArch.setAttribute('filter', 'url(#neon-glow-cyan)');
      this.rightEyelidArch.setAttribute('stroke', '#0066ff');
      this.rightEyelidArch.setAttribute('filter', 'url(#neon-glow-cyan)');

      this.leftEyelashWing.setAttribute('fill', '#0066ff');
      this.leftEyelashWing.setAttribute('filter', 'url(#neon-glow-cyan)');
      this.rightEyelashWing.setAttribute('fill', '#0066ff');
      this.rightEyelashWing.setAttribute('filter', 'url(#neon-glow-cyan)');

      // Drooping eyes rotating outwards for pleading look, tilt downwards
      this.leftEye.style.transform = 'scaleY(0.85) rotate(-9deg)';
      this.rightEye.style.transform = 'scaleY(0.85) rotate(9deg)';
      this.headSpring.targetTilt = -3;
      this.headSpring.targetNod = 13;
      this.headSpring.targetSway = -4;
      
      this.pupils.left.targetScale = 1.05;
      this.pupils.right.targetScale = 1.05;

    } else if (isLoving) {
      // Soft pink/magenta mode
      this.glassesBridgeGlow.setAttribute('stroke', 'url(#glasses-gradient-glow)');
      this.glassesBridgeGlow.setAttribute('filter', 'url(#neon-glow-purple)');
      this.glassesBridgeCore.setAttribute('stroke', 'url(#glasses-gradient-core)');
      this.glassesBridgeCore.setAttribute('filter', 'url(#neon-glow-cyan)');

      this.leftLensGlow.setAttribute('stroke', 'url(#glasses-gradient-glow)');
      this.leftLensGlow.setAttribute('filter', 'url(#neon-glow-purple)');
      this.leftLensCore.setAttribute('stroke', 'url(#glasses-gradient-core)');
      this.leftLensCore.setAttribute('filter', 'url(#neon-glow-cyan)');
      
      this.rightLensGlow.setAttribute('stroke', 'url(#glasses-gradient-glow)');
      this.rightLensGlow.setAttribute('filter', 'url(#neon-glow-purple)');
      this.rightLensCore.setAttribute('stroke', 'url(#glasses-gradient-core)');
      this.rightLensCore.setAttribute('filter', 'url(#neon-glow-cyan)');
      
      this.leftEyebrow.setAttribute('stroke', '#ff2a85');
      this.leftEyebrow.setAttribute('filter', 'url(#neon-glow-purple)');
      this.rightEyebrow.setAttribute('stroke', '#ff2a85');
      this.rightEyebrow.setAttribute('filter', 'url(#neon-glow-purple)');
      
      this.leftIris.setAttribute('fill', 'url(#iris-gradient-left)');
      this.rightIris.setAttribute('fill', 'url(#iris-gradient-right)');

      this.leftEyelidArch.setAttribute('stroke', '#ff2a85');
      this.leftEyelidArch.setAttribute('filter', 'url(#neon-glow-purple)');
      this.rightEyelidArch.setAttribute('stroke', '#ff2a85');
      this.rightEyelidArch.setAttribute('filter', 'url(#neon-glow-purple)');

      this.leftEyelashWing.setAttribute('fill', '#ff2a85');
      this.leftEyelashWing.setAttribute('filter', 'url(#neon-glow-purple)');
      this.rightEyelashWing.setAttribute('fill', '#ff2a85');
      this.rightEyelashWing.setAttribute('filter', 'url(#neon-glow-purple)');

      this.leftEye.style.transform = 'scale(1.05)';
      this.rightEye.style.transform = 'scale(1.05)';
      this.headSpring.targetTilt = 5;
      this.headSpring.targetNod = 2;
      this.headSpring.targetSway = 3;
      
      this.pupils.left.targetScale = 1.25; // dilated loving pupils
      this.pupils.right.targetScale = 1.25;

    } else if (isSleeping) {
      // Closed/Dimmed mode
      this.glassesBridgeGlow.setAttribute('stroke', 'url(#glasses-gradient-glow)');
      this.glassesBridgeGlow.setAttribute('filter', 'url(#neon-glow-purple)');
      this.glassesBridgeCore.setAttribute('stroke', 'url(#glasses-gradient-core)');
      this.glassesBridgeCore.setAttribute('filter', 'url(#neon-glow-cyan)');

      this.leftLensGlow.setAttribute('stroke', 'url(#glasses-gradient-glow)');
      this.leftLensGlow.setAttribute('filter', 'url(#neon-glow-purple)');
      this.leftLensCore.setAttribute('stroke', 'url(#glasses-gradient-core)');
      this.leftLensCore.setAttribute('filter', 'url(#neon-glow-cyan)');
      
      this.rightLensGlow.setAttribute('stroke', 'url(#glasses-gradient-glow)');
      this.rightLensGlow.setAttribute('filter', 'url(#neon-glow-purple)');
      this.rightLensCore.setAttribute('stroke', 'url(#glasses-gradient-core)');
      this.rightLensCore.setAttribute('filter', 'url(#neon-glow-cyan)');
      
      this.leftEyebrow.setAttribute('stroke', '#bd00ff');
      this.leftEyebrow.setAttribute('filter', 'url(#neon-glow-purple)');
      this.rightEyebrow.setAttribute('stroke', '#bd00ff');
      this.rightEyebrow.setAttribute('filter', 'url(#neon-glow-purple)');
      
      this.leftIris.setAttribute('fill', 'url(#iris-gradient-left)');
      this.rightIris.setAttribute('fill', 'url(#iris-gradient-right)');

      this.leftEyelidArch.setAttribute('stroke', '#bd00ff');
      this.leftEyelidArch.setAttribute('filter', 'url(#neon-glow-purple)');
      this.rightEyelidArch.setAttribute('stroke', '#bd00ff');
      this.rightEyelidArch.setAttribute('filter', 'url(#neon-glow-purple)');

      this.leftEyelashWing.setAttribute('fill', '#bd00ff');
      this.leftEyelashWing.setAttribute('filter', 'url(#neon-glow-purple)');
      this.rightEyelashWing.setAttribute('fill', '#bd00ff');
      this.rightEyelashWing.setAttribute('filter', 'url(#neon-glow-purple)');

      this.leftEye.style.transform = 'scaleY(0.04)';
      this.rightEye.style.transform = 'scaleY(0.04)';
      
      this.headSpring.targetTilt = -3;
      this.headSpring.targetNod = 16;
      this.headSpring.targetSway = 0;
      
      this.pupils.left.targetScale = 0.8;
      this.pupils.right.targetScale = 0.8;

    } else {
      // Normal Cyan/Purple Mode
      this.glassesBridgeGlow.setAttribute('stroke', 'url(#glasses-gradient-glow)');
      this.glassesBridgeGlow.setAttribute('filter', 'url(#neon-glow-purple)');
      this.glassesBridgeCore.setAttribute('stroke', 'url(#glasses-gradient-core)');
      this.glassesBridgeCore.setAttribute('filter', 'url(#neon-glow-cyan)');

      this.leftLensGlow.setAttribute('stroke', 'url(#glasses-gradient-glow)');
      this.leftLensGlow.setAttribute('filter', 'url(#neon-glow-purple)');
      this.leftLensCore.setAttribute('stroke', 'url(#glasses-gradient-core)');
      this.leftLensCore.setAttribute('filter', 'url(#neon-glow-cyan)');
      
      this.rightLensGlow.setAttribute('stroke', 'url(#glasses-gradient-glow)');
      this.rightLensGlow.setAttribute('filter', 'url(#neon-glow-purple)');
      this.rightLensCore.setAttribute('stroke', 'url(#glasses-gradient-core)');
      this.rightLensCore.setAttribute('filter', 'url(#neon-glow-cyan)');
      
      this.leftEyebrow.setAttribute('stroke', '#bd00ff');
      this.leftEyebrow.setAttribute('filter', 'url(#neon-glow-purple)');
      this.rightEyebrow.setAttribute('stroke', '#bd00ff');
      this.rightEyebrow.setAttribute('filter', 'url(#neon-glow-purple)');
      
      this.leftIris.setAttribute('fill', 'url(#iris-gradient-left)');
      this.rightIris.setAttribute('fill', 'url(#iris-gradient-right)');

      this.leftEyelidArch.setAttribute('stroke', '#bd00ff');
      this.leftEyelidArch.setAttribute('filter', 'url(#neon-glow-purple)');
      this.rightEyelidArch.setAttribute('stroke', '#bd00ff');
      this.rightEyelidArch.setAttribute('filter', 'url(#neon-glow-purple)');

      this.leftEyelashWing.setAttribute('fill', '#bd00ff');
      this.leftEyelashWing.setAttribute('filter', 'url(#neon-glow-purple)');
      this.rightEyelashWing.setAttribute('fill', '#bd00ff');
      this.rightEyelashWing.setAttribute('filter', 'url(#neon-glow-purple)');

      // Apply specific state scale bounds
      if (isListening) {
        this.leftEye.style.transform = 'scale(1.15)';
        this.rightEye.style.transform = 'scale(1.15)';
        this.headSpring.targetTilt = 5.5;
        this.headSpring.targetNod = -2;
        this.headSpring.targetSway = 4;
        this.pupils.left.targetScale = 1.15;
        this.pupils.right.targetScale = 1.15;
      } else if (isThinking) {
        this.leftEye.style.transform = 'scaleY(0.96)';
        this.rightEye.style.transform = 'scaleY(0.96)';
        this.headSpring.targetTilt = -4;
        this.headSpring.targetNod = -6;
        this.headSpring.targetSway = -4;
        this.pupils.left.targetScale = 0.95;
        this.pupils.right.targetScale = 0.95;
      } else if (isShocked) {
        this.leftEye.style.transform = 'scale(1.26)';
        this.rightEye.style.transform = 'scale(1.26)';
        this.pupils.left.targetScale = 0.32; // pupil contraction in shock
        this.pupils.right.targetScale = 0.32;
        this.headSpring.targetTilt = 0;
        this.headSpring.targetNod = -12;
        this.headSpring.targetSway = 0;
      } else if (isSilly) {
        this.leftEye.style.transform = 'scale(1.05)';
        this.rightEye.style.transform = 'scaleY(0.24) rotate(4deg)'; // pronounced half-wink eye
        this.headSpring.targetTilt = 4.5;
        this.headSpring.targetNod = 1;
        this.headSpring.targetSway = 3;
        this.pupils.left.targetScale = 1.1;
        this.pupils.right.targetScale = 0.85;
      } else if (isGoofy) {
        this.leftEye.style.transform = 'scale(1.1, 0.95) rotate(-3deg)';
        this.rightEye.style.transform = 'scale(0.9, 1.15) rotate(3deg)'; // wacky asymmetric shapes!
        this.headSpring.targetTilt = -3;
        this.headSpring.targetNod = 0;
        this.headSpring.targetSway = 0;
        this.pupils.left.targetScale = 1.45; // one huge pupil
        this.pupils.right.targetScale = 0.55; // one tiny pupil
      } else {
        // Normal scales
        this.leftEye.style.transform = 'scaleY(1)';
        this.rightEye.style.transform = 'scaleY(1)';
        this.headSpring.targetTilt = 0;
        this.headSpring.targetNod = 0;
        this.headSpring.targetSway = 0;
        this.pupils.left.targetScale = 1.0;
        this.pupils.right.targetScale = 1.0;
      }
    }

    // Set target pupil offsets
    this.updateTargetPupilDirection();

    // Overlay the mood accent hue + contained eye/pupil tuning (no-op at neutral)
    this.applyMoodAccentAndOverrides();
  }

  // --- Mood layer helpers ---------------------------------------------------

  // The expression that drives the EMOTIONAL render: the active mood's mapped
  // look, or the raw activity state when mood is neutral (-> zero regression).
  effExpr() {
    if (this.currentMood && this.currentMood !== DEFAULT_MOOD) {
      const desc = MOOD_MAP[this.currentMood];
      if (desc && desc.expr) return desc.expr;
    }
    return this.currentState;
  }

  // The state that drives the PARTICLE theme/motion: a mood-specific theme when
  // the mood defines one (hearts/tears/bubbles/orbit), else the activity state
  // (so speaking/listening/thinking auras still show through under moods that
  // have no signature particle, e.g. happy/surprised/concerned/neutral).
  particleExpr() {
    return MOOD_PARTICLE[this.currentMood] || this.currentState;
  }

  // Set the emotional mood (INDEPENDENT of state). Unknown/empty -> neutral.
  setMood(mood) {
    const m = (typeof mood === 'string') ? mood.trim().toLowerCase() : '';
    const next = MOODS.includes(m) ? m : DEFAULT_MOOD;
    if (next === this.currentMood) return; // no change -> skip re-impulse/flicker

    console.log(`Minnie mood: ${this.currentMood} -> ${next}`);
    this.currentMood = next;

    // Reflect on the debug mood buttons (if present in ?debug)
    document.querySelectorAll('.mood-btn').forEach(b => b.classList.remove('active'));
    const mb = document.getElementById(`mbtn-${next}`);
    if (mb) mb.classList.add('active');

    const desc = MOOD_MAP[next] || MOOD_MAP[DEFAULT_MOOD];

    // One-shot expressive spring impulse (skipped under reduced motion).
    if (!this.reduceMotion && desc.impulse) {
      if (desc.impulse.nod != null) this.headSpring.nodVel = desc.impulse.nod;
      if (desc.impulse.tilt != null) this.headSpring.tiltVel = desc.impulse.tilt;
      if (desc.impulse.glasses != null) this.glassesSpring.velY = desc.impulse.glasses;
    }
    // Surprised: radial particle blast (mirrors the SHOCKED state shockwave).
    if (!this.reduceMotion && desc.shock) {
      const cx = this.faceCx, cy = this.faceCy;
      this.particles.forEach(p => {
        const dx = p.x - cx, dy = p.y - cy;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        p.vx = (dx / dist) * (5 + Math.random() * 7);
        p.vy = (dy / dist) * (5 + Math.random() * 7);
      });
    }

    // Re-render the emotional baseline (eyebrows/eyes/pupils/mouth/colors) via
    // effExpr() + the accent overlay. Particles pick up particleExpr() next frame.
    this.applyStateVisuals();
  }

  // --- Touch-reaction helpers (additive; reuse the existing spring/particle
  //     systems). Called by FaceTouch on a face poke. Honor reduced motion via
  //     the caller; these just apply a one-shot kick. ---

  // One-shot spring impulse (nod/tilt/sway velocities + glasses squish kick).
  reactImpulse({ nod = 0, tilt = 0, sway = 0, glasses = 0 } = {}) {
    if (nod) this.headSpring.nodVel += nod;
    if (tilt) this.headSpring.tiltVel += tilt;
    if (sway) this.headSpring.swayVel += sway;
    if (glasses) this.glassesSpring.velY += glasses;
  }

  // A deliberate blink (or a one-sided wink) using the existing CSS blink anim.
  reactBlink(side) {
    if (this.currentState === STATES.SLEEPING) return;
    if (side === 'left' || side === 'right') {
      const eye = side === 'left' ? this.leftEye : this.rightEye;
      const cls = side === 'left' ? 'wink-left' : 'wink-right';
      eye.classList.add(cls);
      this.glassesSpring.velY += -0.09;
      this.headSpring.tiltVel += (side === 'left' ? 1.6 : -1.6);
      setTimeout(() => eye.classList.remove(cls), 160);
    } else {
      this.leftEye.classList.add('blink-active');
      this.rightEye.classList.add('blink-active');
      this.glassesSpring.velY += -0.16;
      this.headSpring.nodVel += 1.8;
      setTimeout(() => {
        this.leftEye.classList.remove('blink-active');
        this.rightEye.classList.remove('blink-active');
      }, 150);
    }
  }

  // A quick burst of rising heart sprites from near her cheeks (a "blush"),
  // independent of the loving particle THEME so it works under any mood.
  reactHeartBurst(side) {
    if (!this.particles || !this.particles.length) return;
    const cx = this.faceCx, cy = this.faceCy, s = this.faceScale || 0.5;
    const ox = (side === 'left' ? -150 : side === 'right' ? 150 : 0) * s;
    const n = Math.min(18, this.particles.length);
    for (let i = 0; i < n; i++) {
      const p = this.particles[i];
      p.x = cx + ox + (Math.random() - 0.5) * 70 * s;
      p.y = cy + 60 * s + (Math.random() - 0.5) * 30 * s;
      p.vy = -0.6 - Math.random() * 0.8;
      p.vx = (Math.random() - 0.5) * 0.5;
      p.alpha = 0.9;
    }
  }

  // hex -> rgba() string (for the CSS --mood-glow accent, no color-mix needed).
  rgba(hex, a) {
    let h = String(hex).replace('#', '');
    if (h.length === 3) h = h.split('').map(c => c + c).join('');
    const n = parseInt(h, 16) || 0;
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
  }

  // Per-mood accent: shift her soft neon facial features (brows/eyelids/lashes/
  // mouth) + the background aura to the mood hue, keeping the gradient glasses &
  // cyan irises intact so she stays recognizably HER. No-op color at neutral.
  applyMoodAccentAndOverrides() {
    const mood = this.currentMood || DEFAULT_MOOD;
    const desc = MOOD_MAP[mood] || MOOD_MAP[DEFAULT_MOOD];
    const accent = desc.accent || '#bd00ff';

    // Background aura glow echoes the LED mood color (neutral keeps the original).
    try {
      document.documentElement.style.setProperty(
        '--mood-glow', this.rgba(accent, mood === DEFAULT_MOOD ? 0.08 : 0.12));
    } catch (e) {}

    if (mood === DEFAULT_MOOD) {
      // Restore the mouth's native neon (the state branches don't set its stroke);
      // brows/eyes/pupils are already correct from the state branch above.
      this.mouth.setAttribute('stroke', '#bd00ff');
      return;
    }

    // Glow color follows the element's own stroke/fill, so tinting these tints
    // their neon halo too.
    this.leftEyebrow.setAttribute('stroke', accent);
    this.rightEyebrow.setAttribute('stroke', accent);
    this.leftEyelidArch.setAttribute('stroke', accent);
    this.rightEyelidArch.setAttribute('stroke', accent);
    this.leftEyelashWing.setAttribute('fill', accent);
    this.rightEyelashWing.setAttribute('fill', accent);
    this.mouth.setAttribute('stroke', accent);

    // Contained eye/pupil tuning the borrowed look doesn't already carry.
    if (desc.eyeScale != null) {
      this.leftEye.style.transform = `scale(${desc.eyeScale})`;
      this.rightEye.style.transform = `scale(${desc.eyeScale})`;
    }
    if (desc.pupilScale != null) {
      this.pupils.left.targetScale = desc.pupilScale;
      this.pupils.right.targetScale = desc.pupilScale;
    }
  }

  // Update target pupil look vectors based on the effective expression
  updateTargetPupilDirection() {
    if (this.isRollingEyes) return;

    const expr = this.effExpr();
    const isGoofy = expr === STATES.GOOFY;
    const isThinking = expr === STATES.THINKING;
    const isSad = expr === STATES.SAD;
    const isExasperated = expr === STATES.EXASPERATED;

    if (isGoofy) {
      // Crossed eyes!
      this.pupils.left.target.x = 16;
      this.pupils.left.target.y = 3;
      this.pupils.right.target.x = -16;
      this.pupils.right.target.y = 3;
    } else if (isThinking) {
      // Contemplative look up-right
      this.pupils.left.target.x = 8;
      this.pupils.left.target.y = -18;
      this.pupils.right.target.x = 8;
      this.pupils.right.target.y = -18;
    } else if (isSad) {
      // Look down
      this.pupils.left.target.x = 0;
      this.pupils.left.target.y = 12;
      this.pupils.right.target.x = 0;
      this.pupils.right.target.y = 12;
    } else if (isExasperated) {
      // Look straight up
      this.pupils.left.target.x = 0;
      this.pupils.left.target.y = -22;
      this.pupils.right.target.x = 0;
      this.pupils.right.target.y = -22;
    } else {
      // Default: Centered focus
      this.pupils.left.target.x = 0;
      this.pupils.left.target.y = 0;
      this.pupils.right.target.x = 0;
      this.pupils.right.target.y = 0;
    }
  }

  // --- Dynamic Timers / Random Actions ---
  rescheduleTimers() {
    clearTimeout(this.blinkTimer);
    clearTimeout(this.lookTimer);
    clearTimeout(this.headTimer);

    // Disable random blink/look triggers in sleep or hyper-focused states
    if (this.currentState === STATES.SLEEPING) {
      this.scheduleSleepyBlinks();
      return;
    }

    if (this.currentState === STATES.SHOCKED || this.currentState === STATES.MAD || this.currentState === STATES.GOOFY) {
      return; // static expression focus
    }

    this.scheduleBlinks();
    this.scheduleLookAround();
    this.scheduleHeadMicroMovements();
  }

  scheduleBlinks() {
    const nextBlink = 2500 + Math.random() * 5000;
    this.blinkTimer = setTimeout(() => {
      this.triggerBlink();
      this.scheduleBlinks();
    }, nextBlink);
  }

  triggerBlink() {
    if (this.currentState === STATES.SLEEPING || this.isRollingEyes) return;
    if (this.currentState === STATES.SILLY) return; // wink managed natively

    const rand = Math.random();
    if (rand < 0.80) {
      this.leftEye.classList.add('blink-active');
      this.rightEye.classList.add('blink-active');
      this.glassesSpring.velY = -0.16; // Squash glasses!
      this.headSpring.nodVel += 1.8;   // Head nod dip
      setTimeout(() => {
        this.leftEye.classList.remove('blink-active');
        this.rightEye.classList.remove('blink-active');
      }, 130);
    } else if (rand < 0.90) {
      this.leftEye.classList.add('blink-active');
      this.rightEye.classList.add('blink-active');
      this.glassesSpring.velY = -0.16;
      this.headSpring.nodVel += 1.8;
      setTimeout(() => {
        this.leftEye.classList.remove('blink-active');
        this.rightEye.classList.remove('blink-active');
        setTimeout(() => {
          this.leftEye.classList.add('blink-active');
          this.rightEye.classList.add('blink-active');
          this.glassesSpring.velY = -0.12;
          this.headSpring.nodVel += 1.2;
          setTimeout(() => {
            this.leftEye.classList.remove('blink-active');
            this.rightEye.classList.remove('blink-active');
          }, 120);
        }, 150);
      }, 130);
    } else if (rand < 0.95) {
      this.leftEye.classList.add('wink-left');
      this.glassesSpring.velY = -0.09;
      this.headSpring.tiltVel += 1.6;
      setTimeout(() => {
        this.leftEye.classList.remove('wink-left');
      }, 150);
    } else {
      this.rightEye.classList.add('wink-right');
      this.glassesSpring.velY = -0.09;
      this.headSpring.tiltVel -= 1.6;
      setTimeout(() => {
        this.rightEye.classList.remove('wink-right');
      }, 150);
    }
  }

  scheduleSleepyBlinks() {
    const nextSleepyBlink = 8000 + Math.random() * 12000;
    this.blinkTimer = setTimeout(() => {
      this.leftEye.style.transform = 'scaleY(0.2)';
      this.rightEye.style.transform = 'scaleY(0.2)';
      setTimeout(() => {
        if (this.currentState === STATES.SLEEPING) {
          this.leftEye.style.transform = 'scaleY(0.04)';
          this.rightEye.style.transform = 'scaleY(0.04)';
        }
      }, 500);
      this.scheduleSleepyBlinks();
    }, nextSleepyBlink);
  }

  scheduleLookAround() {
    if (this.currentState !== STATES.IDLE && this.currentState !== STATES.HAPPY && this.currentState !== STATES.LOVING) return;

    const nextLook = 1500 + Math.random() * 3500;
    this.lookTimer = setTimeout(() => {
      this.triggerLookAround();
      this.scheduleLookAround();
    }, nextLook);
  }

  triggerLookAround() {
    if (this.isRollingEyes) return;

    const rand = Math.random();
    if (rand < 0.08) {
      this.rollEyes();
    } else if (rand < 0.65) {
      const angles = [0, Math.PI/4, Math.PI/2, 3*Math.PI/4, Math.PI, 5*Math.PI/4, 3*Math.PI/2, 7*Math.PI/2];
      const selectedAngle = angles[Math.floor(Math.random() * angles.length)];
      const maxDistance = 11;
      
      const tx = Math.cos(selectedAngle) * maxDistance;
      const ty = Math.sin(selectedAngle) * (maxDistance * 0.8);
      
      this.pupils.left.target.x = tx;
      this.pupils.left.target.y = ty;
      this.pupils.right.target.x = tx;
      this.pupils.right.target.y = ty;
    } else {
      this.pupils.left.target.x = 0;
      this.pupils.left.target.y = 0;
      this.pupils.right.target.x = 0;
      this.pupils.right.target.y = 0;
    }
  }

  rollEyes() {
    this.isRollingEyes = true;
    this.eyeRollStart = performance.now();
    this.eyeRollDuration = 700 + Math.random() * 400;
  }

  scheduleHeadMicroMovements() {
    const nextMove = 2000 + Math.random() * 4000;
    this.headTimer = setTimeout(() => {
      if (this.currentState === STATES.IDLE || this.currentState === STATES.HAPPY || this.currentState === STATES.LOVING) {
        this.headSpring.targetTilt = (Math.random() - 0.5) * 4;
        this.headSpring.targetNod = (Math.random() - 0.5) * 3;
      } else if (this.currentState === STATES.LISTENING) {
        this.headSpring.targetTilt = 2 + (Math.random() * 3);
        this.headSpring.targetNod = (Math.random() - 0.5) * 2;
      } else if (this.currentState === STATES.SAD) {
        this.headSpring.targetTilt = (Math.random() - 0.5) * 2;
        this.headSpring.targetNod = 6 + (Math.random() * 3);
      }
      this.scheduleHeadMicroMovements();
    }, nextMove);
  }

  // --- Speaking Morph Simulator ---
  startSpeakingSimulation() {
    this.stopSpeakingSimulation();
    this.speakingMockInterval = setInterval(() => {
      // Pass fromMock so setVolume does NOT write the slider — otherwise the
      // slider leaves "0.5" after the first tick, the gate closes, and the
      // volume (and the per-frame MOUTH_SHAPES morph) freezes on one frame.
      if (this.volumeSlider.value == "0.5") {
        // Gentle, SLOW talking rhythm (no fast abs(sin) strobe). The per-frame
        // envelope below smooths it further so volume≈0 self-speech reads calm.
        const t = performance.now();
        const mockVol = 0.42 + 0.26 * Math.sin(t * 0.0055) + 0.12 * Math.sin(t * 0.0121);
        this.setVolume(mockVol, true);
      }
    }, 80);
  }

  stopSpeakingSimulation() {
    clearInterval(this.speakingMockInterval);
  }

  setVolume(vol, fromMock) {
    const prevVol = this.volume;
    this.volume = Math.max(0.0, Math.min(1.0, vol));

    // Only an EXTERNAL volume (real TTS stream / slider drag) writes back to the
    // slider; a real source thus moves it off "0.5" and takes over from the mock.
    if (!fromMock && document.activeElement !== this.volumeSlider) {
      this.volumeSlider.value = this.volume;
      this.volumeValText.textContent = this.volume.toFixed(2);
    }

    // (Removed the per-volume-change head/glasses spring impulse — rapid volume
    // shifts were kicking the springs every frame, making the eyes + glasses
    // STROBE during speech. Speaking now holds a steady head; the slow ambient
    // float-hover provides calm life, and the mouth uses a smoothed envelope.)
    void prevVol;
  }

  // --- Main Animation Loop (60 FPS requestAnimationFrame) ---
  startLoop() {
    const loop = (timestamp) => {
      this.updateStatePhysics(timestamp);
      this.draw();
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  updateStatePhysics(timestamp) {
    // 1. Asymmetric Pupil Eye Roll & targets interpolation
    if (this.isRollingEyes) {
      const elapsed = timestamp - this.eyeRollStart;
      if (elapsed >= this.eyeRollDuration) {
        this.isRollingEyes = false;
        this.pupils.left.target.x = 0;
        this.pupils.left.target.y = 0;
        this.pupils.right.target.x = 0;
        this.pupils.right.target.y = 0;
      } else {
        const progress = elapsed / this.eyeRollDuration;
        const angle = progress * Math.PI * 2;
        const rollRad = 13;
        
        const rx = Math.cos(angle) * rollRad;
        const ry = Math.sin(angle) * (rollRad * 0.7);
        
        this.pupils.left.target.x = rx;
        this.pupils.left.target.y = ry;
        this.pupils.right.target.x = rx;
        this.pupils.right.target.y = ry;
      }
    }

    // Interpolate pupil offsets (X/Y targets, smooth lerp)
    const pupilLerp = 0.11;
    this.pupils.left.current.x += (this.pupils.left.target.x - this.pupils.left.current.x) * pupilLerp;
    this.pupils.left.current.y += (this.pupils.left.target.y - this.pupils.left.current.y) * pupilLerp;
    
    this.pupils.right.current.x += (this.pupils.right.target.x - this.pupils.right.current.x) * pupilLerp;
    this.pupils.right.current.y += (this.pupils.right.target.y - this.pupils.right.current.y) * pupilLerp;

    // Interpolate pupil scale dilation/contraction (Asymmetric support)
    this.pupils.left.currentScale += (this.pupils.left.targetScale - this.pupils.left.currentScale) * pupilLerp;
    this.pupils.right.currentScale += (this.pupils.right.targetScale - this.pupils.right.currentScale) * pupilLerp;

    // Apply Pupil translations & scale bounds
    this.leftPupil.setAttribute('transform', `translate(${this.pupils.left.current.x}, ${this.pupils.left.current.y}) scale(${this.pupils.left.currentScale})`);
    this.rightPupil.setAttribute('transform', `translate(${this.pupils.right.current.x}, ${this.pupils.right.current.y}) scale(${this.pupils.right.currentScale})`);

    // Eyebrows muscle connection - eyebrows dynamically follow pupil Y coordinates
    const leftEyeShift = this.pupils.left.current.y * 0.50;
    const rightEyeShift = this.pupils.right.current.y * 0.50;
    this.leftEyebrow.style.transform = `translateY(${leftEyeShift}px)`;
    this.rightEyebrow.style.transform = `translateY(${rightEyeShift}px)`;

    // 2. Spring-Damper Head Dynamics Solver
    const nodForce = (this.headSpring.targetNod - this.headSpring.nod) * this.headSpring.k;
    this.headSpring.nodVel = (this.headSpring.nodVel + nodForce) * this.headSpring.damping;
    this.headSpring.nod += this.headSpring.nodVel;

    const tiltForce = (this.headSpring.targetTilt - this.headSpring.tilt) * this.headSpring.k;
    this.headSpring.tiltVel = (this.headSpring.tiltVel + tiltForce) * this.headSpring.damping;
    this.headSpring.tilt += this.headSpring.tiltVel;

    const swayForce = (this.headSpring.targetSway - this.headSpring.sway) * this.headSpring.k;
    this.headSpring.swayVel = (this.headSpring.swayVel + swayForce) * this.headSpring.damping;
    this.headSpring.sway += this.headSpring.swayVel;

    // Solver for glasses scale
    const glassesForce = (this.glassesSpring.targetScaleY - this.glassesSpring.scaleY) * this.glassesSpring.k;
    this.glassesSpring.velY = (this.glassesSpring.velY + glassesForce) * this.glassesSpring.damping;
    this.glassesSpring.scaleY += this.glassesSpring.velY;

    // Calculate breathing offsets
    let breatheOffset = 0;
    let breatheScale = 1;
    
    if (this.currentState === STATES.SLEEPING) {
      breatheOffset = Math.sin(timestamp * 0.001) * 7.5;
      breatheScale = 0.985 + Math.sin(timestamp * 0.001) * 0.0075;
    } else if (this.currentState === STATES.SAD) {
      // Slower sighing breath
      breatheOffset = Math.sin(timestamp * 0.0011) * 4.5;
      breatheScale = 0.995 + Math.sin(timestamp * 0.0011) * 0.004;
    } else if (this.currentState !== STATES.ALERT && this.currentState !== STATES.MAD && this.currentState !== STATES.SHOCKED && this.currentState !== STATES.FRUSTRATED) {
      // Normal breathing
      breatheOffset = Math.sin(timestamp * 0.0014) * 5.5;
      breatheScale = 1.0 + Math.sin(timestamp * 0.0014) * 0.0055;
    }

    // Micro sways and organic floating / hovering (multi-frequency synthesis)
    let floatX = 0;
    let floatY = 0;
    let floatTilt = 0;

    let hoverSpeed = 1.0;
    let hoverAmp = 1.0;

    if (this.currentState === STATES.SLEEPING) {
      hoverSpeed = 0.25;
      hoverAmp = 0.35;
    } else if (this.currentState === STATES.SAD) {
      hoverSpeed = 0.6;
      hoverAmp = 0.65;
    } else if (this.currentState === STATES.ANGRY || this.currentState === STATES.MAD) {
      hoverSpeed = 1.6;
      hoverAmp = 1.2;
    } else if (this.currentState === STATES.FRUSTRATED) {
      hoverSpeed = 2.0;
      hoverAmp = 1.35;
    } else if (this.currentState === STATES.SHOCKED) {
      hoverSpeed = 0.0;
      hoverAmp = 0.0;
    }

    if (hoverSpeed > 0) {
      const t = timestamp * 0.001 * hoverSpeed;
      floatX = (Math.sin(t * 0.9) * 10 + Math.cos(t * 1.5) * 4) * hoverAmp;
      floatY = (Math.cos(t * 0.7) * 7.5 + Math.sin(t * 1.3) * 3) * hoverAmp;
      floatTilt = (Math.sin(t * 0.55) * 1.8 + Math.cos(t * 1.1) * 0.7) * hoverAmp;
      
      // Jitter tremor effect for frustrated state
      if (this.currentState === STATES.FRUSTRATED) {
        floatX += (Math.random() - 0.5) * 2.2;
        floatY += (Math.random() - 0.5) * 2.2;
      }
    }

    const finalNod = this.headSpring.nod + breatheOffset + floatY;
    const finalSway = this.headSpring.sway + floatX;
    const finalTilt = this.headSpring.tilt + floatTilt;
    
    // Apply combined floating/hovering transforms
    this.faceGroup.style.transform = `translate(${finalSway}px, ${finalNod}px) rotate(${finalTilt}deg) scale(${breatheScale})`;

    // Apply glasses spring transform
    if (this.glassesGroup) {
      this.glassesGroup.style.transformOrigin = '500px 305px';
      this.glassesGroup.style.transform = `scaleY(${this.glassesSpring.scaleY})`;
    }

    // 3. Speaking mouth — driven by a SMOOTHED volume envelope (fast attack /
    //    slow release) so rapid volume changes shape words at a natural cadence
    //    instead of strobing. Works for the mock AND a real live TTS stream.
    const kVol = (this.volume > this.smoothedVol) ? 0.22 : 0.085;
    this.smoothedVol += (this.volume - this.smoothedVol) * kVol;
    // Mouth SHAPE comes from the effective expression (so she speaks "happy" /
    // "sad" / "loving"); openness is the smoothed VOLUME (state-driven, intact).
    const mouthShape = MOUTH_SHAPES[this.effExpr()] || MOUTH_SHAPES[this.currentState];
    if (mouthShape) {
      const sv = this.smoothedVol;
      this.mouth.setAttribute('d', mouthShape.open(sv));

      const scaleY = 1 + sv * 0.22;
      const scaleX = 1 - sv * 0.09;
      this.mouth.style.transform = `scale(${scaleX}, ${scaleY})`;
    }
  }

  draw() {
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    this.updateParticles();
  }
}

// Instantiate control layer
let minnie = null;
window.addEventListener('DOMContentLoaded', () => {
  minnie = new MinnieController();
});

// External Control API definitions
window.setState = function(state) {
  if (minnie) {
    minnie.transitionToState(state);
  }
};

window.setVolume = function(volume) {
  if (minnie) {
    minnie.setVolume(volume);
  }
};

// Embody-friendly aliases (the plugin/agent drives her through these). The mood
// seam is now LIVE: it drives the emotional layer on top of the activity state.
window.setMinnieState = window.setState;
window.setEmbodyState = window.setState;
window.setMinnieMood = function(mood) {
  if (minnie) {
    minnie.setMood(mood);
  }
};
window.setEmbodyMood = window.setMinnieMood;

// Read the current activity state (used by the control panel's PTT to restore
// her look after a press-and-hold). Returns null before init.
window.getEmbodyState = function() {
  return minnie ? minnie.currentState : null;
};

function changeState(state) {
  window.setState(state);
}

function changeMood(mood) {
  window.setEmbodyMood(mood);
}

// ==========================================================================
// TOUCH CONTROL PANEL  (pointer events: DSI ft5x06 touch + mouse)
// --------------------------------------------------------------------------
// A slide-in overlay (Brightness / Volume sliders + Push-to-Talk) layered ON
// TOP of the face — it never touches MinnieController's animation/mood loop. It
// talks to the same-origin embody server (embody.core.controls):
//   GET  /control/state            -> {brightness:0-100, volume:0-150, listening:bool}
//   POST /control/brightness {value:0-100}
//   POST /control/volume     {value:0-150}
//   POST /control/ptt        {action:"start"|"stop"}
// Every request is wrapped + timed out, so with no server (offline/file://) the
// panel still opens and drags — the POSTs just no-op. Pointer events mean one
// code path serves touch AND mouse.
// ==========================================================================
class ControlPanel {
  constructor() {
    this.handle = document.getElementById('cp-handle');
    this.backdrop = document.getElementById('cp-backdrop');
    this.panel = document.getElementById('cp-panel');
    this.closeBtn = document.getElementById('cp-close');
    this.ptt = document.getElementById('cp-ptt');
    this.rippleLayer = document.getElementById('cp-ripple-layer');
    if (!this.handle || !this.panel) return; // markup absent -> inert

    // Shutdown control elements
    this.powerBtn = document.getElementById('cp-power');
    this.shutdownModal = document.getElementById('cp-shutdown');
    this.shutdownBackdrop = document.getElementById('cp-shutdown-backdrop');
    this.shutdownYes = document.getElementById('cp-shutdown-yes');
    this.shutdownNo = document.getElementById('cp-shutdown-no');
    this.shuttingOverlay = document.getElementById('cp-shutting');
    this.toastEl = document.getElementById('cp-toast');
    this.shutdownOpen = false;
    this.shutdownPending = false; // guards against double-fire while awaiting

    this.isOpen = false;
    this.autoHideMs = 8000;     // auto-dismiss after ~8s idle
    this.autoHideTimer = null;
    this.pttActive = false;
    this.pttPrevState = null;

    try {
      this.reduceMotion = !!(window.matchMedia &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (e) { this.reduceMotion = false; }

    this.bright = this.setupSlider({
      root: 'cp-bright', fill: 'cp-bright-fill', thumb: 'cp-bright-thumb',
      val: 'cp-bright-val', min: 0, max: 100, suffix: '%', path: '/control/brightness'
    });
    this.vol = this.setupSlider({
      root: 'cp-vol', fill: 'cp-vol-fill', thumb: 'cp-vol-thumb',
      val: 'cp-vol-val', min: 0, max: 150, suffix: '%', path: '/control/volume'
    });

    this.bindOpener();
    this.bindDismiss();
    this.bindPTT();
    this.bindRipple();
    this.bindShutdown();
  }

  // --- tiny utilities ---
  debounce(fn, ms) {
    let t = null;
    return (...a) => { if (t) clearTimeout(t); t = setTimeout(() => { t = null; fn(...a); }, ms); };
  }

  async postCtl(path, body) {
    try {
      const c = new AbortController();
      const t = setTimeout(() => c.abort(), 1500);
      await fetch(path, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body), cache: 'no-store', signal: c.signal
      });
      clearTimeout(t);
    } catch (e) { /* offline / no server — controls are best-effort */ }
  }

  async getState() {
    try {
      const c = new AbortController();
      const t = setTimeout(() => c.abort(), 1500);
      const r = await fetch('/control/state', { cache: 'no-store', signal: c.signal });
      clearTimeout(t);
      if (r && r.ok) return await r.json();
    } catch (e) { /* offline — keep defaults */ }
    return null;
  }

  // --- big finger-friendly slider built on pointer events ---
  setupSlider(o) {
    const root = document.getElementById(o.root);
    const fill = document.getElementById(o.fill);
    const thumb = document.getElementById(o.thumb);
    const valEl = document.getElementById(o.val);
    if (!root) return { set() {}, get() { return o.min; } };

    let value = o.min;
    let dragging = false;
    const post = this.debounce((v) => this.postCtl(o.path, { value: v }), 120);
    const self = this;

    const valFromX = (clientX) => {
      const r = root.getBoundingClientRect();
      let p = (clientX - r.left) / (r.width || 1);
      p = Math.max(0, Math.min(1, p));
      return Math.round(o.min + p * (o.max - o.min));
    };
    const render = () => {
      const p = (value - o.min) / ((o.max - o.min) || 1);
      fill.style.width = (p * 100) + '%';
      thumb.style.left = (p * 100) + '%';
      if (valEl) valEl.textContent = value + (o.suffix || '');
      root.setAttribute('aria-valuenow', String(value));
    };

    root.addEventListener('pointerdown', (e) => {
      dragging = true;
      try { root.setPointerCapture(e.pointerId); } catch (_) {}
      value = valFromX(e.clientX); render(); post(value);
      self.armAutoHide();
      e.preventDefault();
    });
    root.addEventListener('pointermove', (e) => {
      if (!dragging) return;
      value = valFromX(e.clientX); render(); post(value);
      self.armAutoHide();
    });
    const end = (e) => {
      if (!dragging) return;
      dragging = false;
      try { root.releasePointerCapture(e.pointerId); } catch (_) {}
      self.postCtl(o.path, { value: value }); // immediate final commit
      self.armAutoHide();
    };
    root.addEventListener('pointerup', end);
    root.addEventListener('pointercancel', end);

    return {
      set: (v) => { value = Math.max(o.min, Math.min(o.max, Math.round(v))); render(); },
      get: () => value
    };
  }

  // --- open / close ---
  async openPanel() {
    if (this.isOpen) return;
    this.isOpen = true;
    this.backdrop.hidden = false;
    // next frame so the transition runs from the off-screen start
    requestAnimationFrame(() => {
      this.panel.classList.add('cp-visible');
      this.backdrop.classList.add('cp-visible');
    });
    this.panel.setAttribute('aria-hidden', 'false');
    this.handle.classList.add('cp-hidden');
    this.handle.setAttribute('aria-expanded', 'true');
    this.armAutoHide();

    const st = await this.getState();
    if (st) {
      if (typeof st.brightness === 'number') this.bright.set(st.brightness);
      if (typeof st.volume === 'number') this.vol.set(st.volume);
      if (st.listening) this.ptt.classList.add('cp-on');
      else if (!this.pttActive) this.ptt.classList.remove('cp-on');
    }
  }

  closePanel() {
    if (!this.isOpen) return;
    this.isOpen = false;
    if (this.pttActive) this.endPTT(null); // release a held PTT on dismiss
    this.panel.classList.remove('cp-visible');
    this.backdrop.classList.remove('cp-visible');
    this.panel.setAttribute('aria-hidden', 'true');
    this.handle.classList.remove('cp-hidden');
    this.handle.setAttribute('aria-expanded', 'false');
    if (this.autoHideTimer) { clearTimeout(this.autoHideTimer); this.autoHideTimer = null; }
    const bd = this.backdrop;
    setTimeout(() => { if (!this.isOpen) bd.hidden = true; }, this.reduceMotion ? 0 : 320);
  }

  armAutoHide() {
    if (!this.isOpen) return;
    if (this.autoHideTimer) clearTimeout(this.autoHideTimer);
    // Don't run the idle timer while the shutdown modal is up — the user is
    // mid-decision; the panel must stay put behind it.
    if (this.shutdownOpen) return;
    this.autoHideTimer = setTimeout(() => {
      if (this.isOpen && !this.pttActive && !this.shutdownOpen) this.closePanel();
    }, this.autoHideMs);
  }

  // --- opener: tap OR swipe-up on the handle ---
  bindOpener() {
    let startY = 0, pid = null, swiped = false;
    this.handle.addEventListener('pointerdown', (e) => {
      pid = e.pointerId; startY = e.clientY; swiped = false;
      try { this.handle.setPointerCapture(e.pointerId); } catch (_) {}
    });
    this.handle.addEventListener('pointermove', (e) => {
      if (pid == null) return;
      if (startY - e.clientY > 24) { swiped = true; pid = null; this.openPanel(); }
    });
    this.handle.addEventListener('pointerup', (e) => {
      if (pid == null) return;       // already opened via swipe
      pid = null;
      if (!swiped) this.openPanel();  // plain tap
    });
    this.handle.addEventListener('pointercancel', () => { pid = null; });
  }

  // --- dismiss: tap-away, close button, Escape; keep alive on interaction ---
  bindDismiss() {
    this.backdrop.addEventListener('pointerdown', () => this.closePanel());
    this.closeBtn.addEventListener('pointerdown', (e) => { e.preventDefault(); this.closePanel(); });
    this.panel.addEventListener('pointerdown', () => this.armAutoHide());
    this.panel.addEventListener('pointermove', () => this.armAutoHide());
    try {
      document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        // Escape closes the shutdown modal first (if open), else the panel.
        if (this.shutdownOpen) this.closeShutdown();
        else this.closePanel();
      });
    } catch (_) {}
  }

  // --- Push-to-Talk: press & hold ---
  bindPTT() {
    const start = (e) => {
      if (this.pttActive) return;
      this.pttActive = true;
      try { this.ptt.setPointerCapture(e.pointerId); } catch (_) {}
      this.ptt.classList.add('cp-on');
      this.postCtl('/control/ptt', { action: 'start' });
      // optimistic face feedback: go listening, remembering her prior look so we
      // can restore it on release (the backend PTT seam is inert for now).
      try {
        this.pttPrevState = (typeof window.getEmbodyState === 'function') ? window.getEmbodyState() : null;
        if (window.setEmbodyState) window.setEmbodyState('listening');
      } catch (_) {}
      this.armAutoHide();
      e.preventDefault();
    };
    const stop = (e) => this.endPTT(e);
    this.ptt.addEventListener('pointerdown', start);
    this.ptt.addEventListener('pointerup', stop);
    this.ptt.addEventListener('pointercancel', stop);
    this.ptt.addEventListener('pointerleave', (e) => { if (this.pttActive) this.endPTT(e); });
  }

  endPTT(e) {
    if (!this.pttActive) return;
    this.pttActive = false;
    if (e) { try { this.ptt.releasePointerCapture(e.pointerId); } catch (_) {} }
    this.ptt.classList.remove('cp-on');
    this.postCtl('/control/ptt', { action: 'stop' });
    try {
      if (window.setEmbodyState && this.pttPrevState) window.setEmbodyState(this.pttPrevState);
    } catch (_) {}
    this.pttPrevState = null;
    this.armAutoHide();
  }

  // --- tap-ripple: visible confirmation that the touch reached Chromium ---
  bindRipple() {
    if (this.reduceMotion || !this.rippleLayer) return;
    document.addEventListener('pointerdown', (e) => {
      const r = document.createElement('span');
      r.className = 'cp-ripple';
      r.style.left = e.clientX + 'px';
      r.style.top = e.clientY + 'px';
      this.rippleLayer.appendChild(r);
      setTimeout(() => { if (r.parentNode) r.parentNode.removeChild(r); }, 650);
    }, true); // capture phase -> fires even if a target stops propagation
  }

  // --- Shutdown control: power button -> confirm modal -> Yes posts poweroff ---
  bindShutdown() {
    if (!this.powerBtn || !this.shutdownModal) return; // markup absent -> inert
    this.powerBtn.addEventListener('pointerdown', (e) => {
      e.preventDefault(); e.stopPropagation();
      this.openShutdown();
    });
    // No / Cancel + tap-away dismiss with ZERO side effects.
    this.shutdownNo.addEventListener('pointerdown', (e) => { e.preventDefault(); this.closeShutdown(); });
    this.shutdownBackdrop.addEventListener('pointerdown', (e) => { e.preventDefault(); this.closeShutdown(); });
    // Yes is the ONLY path that fires the poweroff.
    this.shutdownYes.addEventListener('pointerdown', (e) => { e.preventDefault(); this.confirmShutdown(); });
  }

  openShutdown() {
    if (this.shutdownOpen) return;
    this.shutdownOpen = true;
    this.shutdownModal.hidden = false;
    requestAnimationFrame(() => this.shutdownModal.classList.add('cp-visible'));
    this.shutdownModal.setAttribute('aria-hidden', 'false');
    // Freeze the panel's idle auto-hide while the user decides.
    if (this.autoHideTimer) { clearTimeout(this.autoHideTimer); this.autoHideTimer = null; }
  }

  closeShutdown() {
    if (!this.shutdownOpen) return;
    this.shutdownOpen = false;
    this.shutdownModal.classList.remove('cp-visible');
    this.shutdownModal.setAttribute('aria-hidden', 'true');
    const m = this.shutdownModal;
    setTimeout(() => { if (!this.shutdownOpen) m.hidden = true; }, this.reduceMotion ? 0 : 260);
    this.armAutoHide(); // resume the panel's idle timer; panel stays open
  }

  // The explicit, deliberate confirm — the ONLY thing that powers off. The
  // "SHUTTING DOWN…" overlay is GATED on a CONFIRMED success: we await the POST
  // and only show the overlay on HTTP 200 with {ok:true, shutting_down:true}.
  // Any failure (non-200 / network / timeout) -> NO overlay, dismiss the modal,
  // and show a dismissible error toast so the user is never misled or stuck.
  async confirmShutdown() {
    if (this.shutdownPending) return; // ignore a double-tap while awaiting
    this.shutdownPending = true;

    let ok = false;
    try {
      const c = new AbortController();
      const t = setTimeout(() => c.abort(), 4000);
      const r = await fetch('/control/shutdown', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: true }), cache: 'no-store', signal: c.signal
      });
      clearTimeout(t);
      if (r && r.status === 200) {
        let data = null;
        try { data = await r.json(); } catch (e) { data = null; }
        ok = !!(data && data.ok === true && data.shutting_down === true);
      }
    } catch (e) {
      ok = false; // network error / abort / timeout
    }

    this.shutdownPending = false;

    if (ok) {
      // Confirmed: tear down the modal and show the terminal overlay.
      this.shutdownOpen = false;
      this.shutdownModal.classList.remove('cp-visible');
      this.shutdownModal.setAttribute('aria-hidden', 'true');
      this.shutdownModal.hidden = true;
      if (this.autoHideTimer) { clearTimeout(this.autoHideTimer); this.autoHideTimer = null; }
      if (this.shuttingOverlay) {
        this.shuttingOverlay.hidden = false;
        requestAnimationFrame(() => this.shuttingOverlay.classList.add('cp-visible'));
        this.shuttingOverlay.setAttribute('aria-hidden', 'false');
      }
    } else {
      // Failed: NO overlay. Dismiss the modal, keep the panel usable, toast.
      this.closeShutdown();
      this.showToast('Shutdown failed — try again');
    }
  }

  // Brief, dismissible toast. Tap to dismiss; also auto-hides. Never blocks.
  showToast(msg) {
    const el = this.toastEl;
    if (!el) return;
    el.textContent = msg;
    el.hidden = false;
    el.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(() => el.classList.add('cp-visible'));
    if (this._toastTimer) clearTimeout(this._toastTimer);
    const hide = () => {
      el.classList.remove('cp-visible');
      el.setAttribute('aria-hidden', 'true');
      if (this._toastTimer) { clearTimeout(this._toastTimer); this._toastTimer = null; }
      setTimeout(() => { if (!el.classList.contains('cp-visible')) el.hidden = true; }, this.reduceMotion ? 0 : 260);
    };
    if (!el._tapBound) { el.addEventListener('pointerdown', hide); el._tapBound = true; }
    this._toastTimer = setTimeout(hide, 4000);
  }
}

// Instantiate the control panel once the DOM is ready (separate from the face
// controller so it can never interfere with the animation loop).
window.addEventListener('DOMContentLoaded', () => {
  window.controlPanel = new ControlPanel();
});

// ==========================================================================
// FACE TOUCH REACTIONS  (poke her face -> she reacts)
// --------------------------------------------------------------------------
// Invisible SVG hit-zones over her face (see #face-touch-zones in index.html).
// Each poke does BOTH, for a snappy local feel + full-being sync:
//   1. OPTIMISTIC LOCAL: setEmbodyMood(reactionMood) + a one-shot spring impulse
//      (and a wink/heart where it fits) — instant, no network wait.
//   2. POST /control/mood {value:<mood>, ttl:3} so the case LEDs + other surfaces
//      react too; mood-core decays it back to the prior/neutral mood after ~3s.
// This is an ADDITIVE input layer — it only calls the public window.setEmbody*
// seam + MinnieController react* helpers; it never touches the rAF/mood/SSE loop
// or the control panel. Reactions are SUPPRESSED while the panel is open, and the
// zones live on her upper face so they never sit under the bottom-center handle.
// Pointer events => one path for ft5x06 touch AND mouse.
// ==========================================================================
class FaceTouch {
  constructor() {
    this.group = document.getElementById('face-touch-zones');
    if (!this.group) return; // markup absent -> inert

    this.localTtlMs = 3000;     // mirror the server ttl:3 for the local decay
    this.decayTimer = null;
    this.lastTapAt = 0;         // for double-tap (giggle) detection
    this.doubleTapMs = 320;

    try {
      this.reduceMotion = !!(window.matchMedia &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (e) { this.reduceMotion = false; }

    // zone id -> reaction descriptor. `mood` is a contract mood; `impulse` reuses
    // MinnieController.reactImpulse; `blink`/`heart` fire the matching helper.
    this.zones = {
      'fz-nose':          { mood: 'surprised', impulse: { nod: -22, glasses: -0.18 } },           // boop! downward recoil
      'fz-forehead':      { mood: 'curious',   impulse: { tilt: 7 } },                              // brow-up + tiny tilt
      'fz-cheek-left':    { mood: 'loving',    impulse: { tilt: 4 },  heart: 'left' },              // blush + heart
      'fz-cheek-right':   { mood: 'loving',    impulse: { tilt: -4 }, heart: 'right' },             // blush + heart
      'fz-glasses-bridge':{ mood: 'playful',   impulse: { glasses: -0.22 } },                       // glasses wobble
      'fz-glasses-left':  { mood: 'playful',   impulse: { glasses: -0.22, tilt: 3 } },
      'fz-glasses-right': { mood: 'playful',   impulse: { glasses: -0.22, tilt: -3 } },
      'fz-eye-left':      { mood: null,        blink: 'left' },                                     // deliberate wink
      'fz-eye-right':     { mood: null,        blink: 'right' }
    };

    this.bind();
  }

  panelOpen() {
    return !!(window.controlPanel && window.controlPanel.isOpen);
  }

  async postMood(mood) {
    try {
      const c = new AbortController();
      const t = setTimeout(() => c.abort(), 1500);
      await fetch('/control/mood', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: mood, ttl: 3 }), cache: 'no-store', signal: c.signal
      });
      clearTimeout(t);
    } catch (e) { /* offline / no server — local reaction still played */ }
  }

  // Apply the local reaction (mood + impulse + blink/heart), then arm decay.
  react(zoneId) {
    const z = this.zones[zoneId];
    if (!z) return;

    // 1a. optimistic mood (skip for pure blink/wink zones where mood is null)
    if (z.mood) {
      try { if (window.setEmbodyMood) window.setEmbodyMood(z.mood); } catch (e) {}
    }
    // 1b. impulse + extras (skipped under reduced motion; mood still applies)
    if (!this.reduceMotion && minnie) {
      if (z.impulse) minnie.reactImpulse(z.impulse);
      if (z.heart) minnie.reactHeartBurst(z.heart);
    }
    if (z.blink && minnie) minnie.reactBlink(z.blink); // blink is essential feedback; keep even reduced

    // 2. server sync so the LEDs react too (decays after ttl:3 on the backend)
    if (z.mood) this.postMood(z.mood);

    // local decay back to neutral to mirror the server ttl (only for mood zones)
    if (z.mood) this.armDecay();
  }

  // double-tap anywhere on the face -> playful giggle
  giggle() {
    try { if (window.setEmbodyMood) window.setEmbodyMood('playful'); } catch (e) {}
    if (!this.reduceMotion && minnie) {
      minnie.reactImpulse({ tilt: 6, nod: -6 });
      minnie.reactBlink('left');
      setTimeout(() => { if (minnie) minnie.reactBlink('right'); }, 130);
    }
    this.postMood('playful');
    this.armDecay();
  }

  armDecay() {
    if (this.decayTimer) clearTimeout(this.decayTimer);
    this.decayTimer = setTimeout(() => {
      // Only revert if the SSE loop hasn't since driven a different mood — i.e.
      // we only clear a mood that is still one of our transient reactions.
      try { if (window.setEmbodyMood) window.setEmbodyMood('neutral'); } catch (e) {}
      this.decayTimer = null;
    }, this.localTtlMs);
  }

  // Resolve which zone a pointer event landed on (the zones are simple shapes
  // that are direct children of the group; the event target IS the zone).
  zoneIdFor(target) {
    if (!target) return null;
    const id = target.id;
    return (id && this.zones[id]) ? id : null;
  }

  bind() {
    // Single handler on the group resolves the zone AND single/double-tap, so a
    // double-tap fires the giggle WITHOUT also firing the second zone reaction.
    this.group.addEventListener('pointerdown', (e) => {
      if (this.panelOpen()) return;          // suppress while the panel is open
      const zoneId = this.zoneIdFor(e.target);
      if (!zoneId) return;                    // poke landed in a gap -> ignore
      e.preventDefault();

      const now = (typeof e.timeStamp === 'number') ? e.timeStamp : 0;
      if (this.lastTapAt && (now - this.lastTapAt) <= this.doubleTapMs) {
        this.giggle();                        // double-tap anywhere on the face
        this.lastTapAt = 0;                   // consume so a 3rd tap starts fresh
      } else {
        this.lastTapAt = now;
        this.react(zoneId);                   // single-zone reaction
      }
    });
  }
}

// Instantiate after the face controller exists (needs `minnie` for the react
// helpers). DOMContentLoaded order: MinnieController is created in an earlier
// listener, so `minnie` is set by the time this one runs.
window.addEventListener('DOMContentLoaded', () => {
  window.faceTouch = new FaceTouch();
});

// ==========================================================================
// STANDALONE HOLD-TO-TALK MIC BUTTON  (bottom-left, always visible)
// --------------------------------------------------------------------------
// Quick-access push-to-talk using the SAME mechanism as the panel's PTT button
// (POST /control/ptt {start|stop} + optimistic listening feedback) — no panel
// needed. Isolated from the panel/face loops; pointer events => touch + mouse.
// ==========================================================================
class MicButton {
  constructor() {
    this.btn = document.getElementById('cp-mic');
    if (!this.btn) return; // markup absent -> inert
    this.active = false;
    this.prevState = null;
    this.bind();
  }

  async post(action) {
    try {
      const c = new AbortController();
      const t = setTimeout(() => c.abort(), 1500);
      await fetch('/control/ptt', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }), cache: 'no-store', signal: c.signal
      });
      clearTimeout(t);
    } catch (e) { /* offline / no server — best-effort, like the panel PTT */ }
  }

  start(e) {
    if (this.active) return;
    this.active = true;
    try { this.btn.setPointerCapture(e.pointerId); } catch (_) {}
    this.btn.classList.add('cp-on');
    this.post('start');
    // optimistic face feedback: go listening, remember prior look to restore.
    try {
      this.prevState = (typeof window.getEmbodyState === 'function') ? window.getEmbodyState() : null;
      if (window.setEmbodyState) window.setEmbodyState('listening');
    } catch (_) {}
    e.preventDefault();
    e.stopPropagation(); // don't let the press fall through to face touch-zones
  }

  stop(e) {
    if (!this.active) return;
    this.active = false;
    if (e) { try { this.btn.releasePointerCapture(e.pointerId); } catch (_) {} }
    this.btn.classList.remove('cp-on');
    this.post('stop');
    try {
      if (window.setEmbodyState && this.prevState) window.setEmbodyState(this.prevState);
    } catch (_) {}
    this.prevState = null;
  }

  bind() {
    this.btn.addEventListener('pointerdown', (e) => this.start(e));
    this.btn.addEventListener('pointerup', (e) => this.stop(e));
    this.btn.addEventListener('pointercancel', (e) => this.stop(e));
    this.btn.addEventListener('pointerleave', (e) => { if (this.active) this.stop(e); });
  }
}

window.addEventListener('DOMContentLoaded', () => {
  window.micButton = new MicButton();
});
