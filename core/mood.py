"""embody.core.mood — infer an emotional MOOD from text (local, offline, zero-config).

This is the v1 mood-inference seam: a pure, deterministic, dependency-free
heuristic so the plugin emotes on ANY install with **no model, prompt, or config
change**. ``infer_mood(text)`` maps a chunk of text (an assistant reply) to one of
the nine canonical MOODS, which ``core.state.set_mood`` then broadcasts to the
face (SSE) and the hardware backends (``on_mood``). Mood is INDEPENDENT of the
activity STATE — it tints the persona's feeling, not what it's doing.

MOODS (the locked cross-worker vocabulary; default ``neutral``)::

    neutral  happy  excited  loving  playful  curious  sad  surprised  concerned

HOW IT DECIDES (single source of truth = the ordered ``_RULES`` table below)
---------------------------------------------------------------------------
Rules are evaluated top-to-bottom in THREE passes; the first hit wins:

  1. **Emoji cues** (highest-confidence — an explicit signal the writer chose):
        😍❤️🥰 → loving      🎉🔥🚀 → excited     😮😲😱 → surprised
        😜😝😏 → playful      😄😁🙂 → happy        ⚠️😟😬 → concerned
        😢😞😔 → sad          🤔🧐   → curious
  2. **Keyword / phrase cues** (lowercased substring scan), e.g.::
        "i love"/"adore"                     → loving
        "let's go"/"shipped"/"we did it"     → excited
        "wow"/"incredible"/"unbelievable"    → surprised
        "haha"/"lol"/"just kidding"          → playful
        "great"/"awesome"/"perfect"          → happy
        "sorry"/"unfortunately"/"careful"    → concerned
        "failed"/"error"/"can't"/"broke"     → sad
        "hmm"/"let me think"/"interesting"   → curious
  3. **Punctuation cues** (weak, last resort):
        "!" density >= 2 → excited     trailing "?" → curious
     (A lone "!" is deliberately NOT a happy cue — almost every upbeat-but-neutral
     reply ends in one, so it would flatten the persona to "happy" by default and
     drown out the specific moods. Genuine happiness is caught by the keyword pass.)

Anything with no signal → ``neutral``. Empty/non-str input → ``neutral``.

The mapping is intentionally a flat, ordered table so it's trivially tunable:
re-order rows to change precedence, add a keyword to a row to broaden a mood.
Substring matching is deliberate (catches "great" in "great job") and is a known,
accepted source of heuristic noise for v1 (e.g. "error" in a neutral log path).
"""
from __future__ import annotations

# The canonical mood vocabulary. Mirrors core.state.VALID_MOODS (order matters
# for the /config payload). infer_mood only ever returns a member of this set.
MOODS = (
    "neutral", "happy", "excited", "loving",
    "playful", "curious", "sad", "surprised", "concerned",
)

# Ordered inference rules — the single source of truth. Each row is
# (mood, emoji_cues, keyword_cues). Evaluated emoji-pass then keyword-pass,
# top-to-bottom; first match wins. Emoji cues use the BARE codepoint (e.g. "❤"
# not "❤️") so they match with or without a trailing variation selector (U+FE0F).
_RULES: tuple = (
    ("loving",    ("❤", "🥰", "😍", "😘", "💕", "💖", "💗", "🤗"),
     ("i love", "love it", "love this", "love that", "adore", "so sweet",
      "you're the best", "youre the best", "my favorite", "my favourite",
      "with love", "sweetheart")),

    ("excited",   ("🎉", "🔥", "🚀", "✨", "💯", "🥳", "🙌"),
     ("let's go", "lets go", "let’s go", "shipped", "ship it", "we did it",
      "we shipped", "deployed", "launching", "can't wait", "cant wait",
      "so excited", "woohoo", "woo hoo", "hyped", "amazing news")),

    ("surprised", ("😮", "😲", "😱", "😯", "🤯", "😳"),
     ("wow", "whoa", "woah", "incredible", "unbelievable", "no way",
      "i can't believe", "i cannot believe", "had no idea", "out of nowhere",
      "didn't expect", "didnt expect")),

    ("playful",   ("😜", "😝", "😏", "😉", "😋", "😆", "😈"),
     ("haha", "hehe", "lol", "lmao", "rofl", "just kidding", "kidding",
      "teasing", "tee hee", "wink wink", ":)", ":-)")),

    ("happy",     ("😄", "😁", "😀", "🙂", "😊", "👍", "😺"),
     ("great", "awesome", "perfect", "wonderful", "fantastic", "excellent",
      "nice work", "well done", "good job", "glad", "happy to", "yay",
      "looks good", "lgtm", "love to help", "my pleasure")),

    ("concerned", ("⚠", "😟", "😬", "😰", "😨"),
     ("sorry", "unfortunately", "be careful", "careful", "warning",
      "watch out", "heads up", "concern", "worried", "risky", "caution",
      "i'm afraid", "im afraid", "apolog")),

    ("sad",       ("😢", "😞", "😔", "😭", "💔", "🥺"),
     ("failed", "failure", "error", "can't", "cannot", "couldn't", "couldnt",
      "unable", "broke", "broken", "went wrong", "not working", "doesn't work",
      "didn't work", "didnt work", "no luck", "gave up")),

    ("curious",   ("🤔", "🧐"),
     ("hmm", "let me think", "let me check", "interesting", "i wonder",
      "wonder if", "curious", "not sure", "what if", "how about", "intriguing")),
)


def infer_mood(text: str) -> str:
    """Map ``text`` to one of MOODS. Pure, deterministic, offline. Never raises.

    Three passes over the ordered ``_RULES`` table (emoji → keyword → punctuation),
    first hit wins; ``neutral`` if nothing matches. See the module docstring for
    the full mapping. Non-string / empty input → ``neutral``.
    """
    if not text or not isinstance(text, str):
        return "neutral"

    lowered = text.lower()

    # Pass 1 — emoji cues (matched against the raw text; case-irrelevant).
    for mood, emojis, _keywords in _RULES:
        for cue in emojis:
            if cue in text:
                return mood

    # Pass 2 — keyword / phrase cues (lowercased substring scan).
    for mood, _emojis, keywords in _RULES:
        for cue in keywords:
            if cue in lowered:
                return mood

    # Pass 3 — punctuation cues (weak signals, last resort). A lone "!" is NOT a
    # cue (see module docstring): it would make almost every reply read "happy".
    if text.count("!") >= 2:
        return "excited"
    if text.rstrip().endswith("?"):
        return "curious"

    return "neutral"
