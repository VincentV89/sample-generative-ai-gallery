"""Curated creative options for the Time-Travel Portrait Studio.

Single source of truth: the API serves these to the web app (GET /api/options)
and validates every generation request against them.
"""

ERAS = {
    "ancient_egypt": {"label": "Ancient Egypt", "years": "c. 1350 BC", "emoji": "𓂀",
                      "details": "New Kingdom Thebes, linen and gold collars, lapis lazuli, papyrus and lotus motifs, warm desert light"},
    "ancient_rome": {"label": "Ancient Rome", "years": "c. 50 AD", "emoji": "🏛️",
                     "details": "Imperial Rome, togas and stolas with tyrian purple trim, marble colonnades, laurel wreaths"},
    "ancient_india": {"label": "Ancient India", "years": "c. 300 BC", "emoji": "🪷",
                      "details": "Mauryan court, silk and cotton drapery, gold jewellery, sandstone pillars, marigolds"},
    "tang_china": {"label": "Tang Dynasty China", "years": "c. 750 AD", "emoji": "🏮",
                   "details": "Chang'an court, flowing hanfu silk robes, peony motifs, lacquered pavilions, ink-wash mountains"},
    "viking_age": {"label": "Viking Age", "years": "c. 900 AD", "emoji": "⚔️",
                   "details": "Norse longhouse, wool and fur cloaks, bronze brooches, carved knotwork, fjord mist"},
    "mughal_empire": {"label": "Mughal Empire", "years": "c. 1630", "emoji": "🕌",
                      "details": "Shah Jahan's court, brocade jama and pearls, pietra dura inlay, jharokha windows, gardens"},
    "renaissance": {"label": "Renaissance Florence", "years": "c. 1500", "emoji": "🎨",
                    "details": "Medici Florence, velvet and brocade, sfumato landscape background, Brunelleschi's dome"},
    "edo_japan": {"label": "Edo Japan", "years": "c. 1800", "emoji": "🗾",
                  "details": "Edo period, layered silk kimono, cherry blossoms, wooden machiya, paper lanterns"},
    "victorian": {"label": "Victorian London", "years": "c. 1880", "emoji": "🎩",
                  "details": "gaslit London, tailored frock coats and bustle gowns, brass instruments, fog"},
    "roaring_twenties": {"label": "Roaring Twenties", "years": "c. 1925", "emoji": "🥂",
                         "details": "Jazz Age, art deco geometry, beaded dresses and sharp suits, champagne glow"},
    "cyberpunk_2099": {"label": "Neo-Tokyo 2099", "years": "2099", "emoji": "🌃",
                       "details": "rain-slick megacity, neon holograms, techwear, subtle cybernetic accents"},
    "mars_2300": {"label": "Mars Colony", "years": "2300", "emoji": "🪐",
                  "details": "terraformed Martian habitat, sleek pressure suits, rust-red dunes, twin moons in the sky"},
}

ROLES = {
    "ruler": "Ruler / Monarch",
    "scholar": "Scholar / Philosopher",
    "explorer": "Explorer / Navigator",
    "artist": "Artist / Musician",
    "healer": "Healer / Physician",
    "inventor": "Inventor / Engineer",
    "merchant": "Merchant / Trader",
    "guardian": "Guardian / General",
}

STYLES = {
    "baroque_oil": {"label": "Baroque Oil", "details": "baroque oil painting, dramatic chiaroscuro, rich glazes, visible brushwork, in the manner of Rembrandt"},
    "renaissance_tempera": {"label": "Renaissance Panel", "details": "Renaissance tempera and oil on panel, sfumato, delicate glazing, in the manner of Leonardo da Vinci"},
    "impressionist": {"label": "Impressionist", "details": "impressionist painting, broken colour, luminous dappled light, in the manner of Claude Monet"},
    "ukiyo_e": {"label": "Ukiyo-e Woodblock", "details": "ukiyo-e woodblock print, bold outlines, flat colour fields, washi paper texture, in the manner of Hokusai"},
    "art_nouveau": {"label": "Art Nouveau", "details": "art nouveau poster, ornamental halo, flowing organic lines, muted gold palette, in the manner of Alphonse Mucha"},
    "mughal_miniature": {"label": "Mughal Miniature", "details": "Mughal miniature painting, gold leaf, fine brush detail, jewel-toned pigments, ornate border"},
    "cinematic_photo": {"label": "Cinematic Photo", "details": "cinematic portrait photograph, 85mm lens, shallow depth of field, volumetric light, film grain"},
    "watercolor": {"label": "Watercolour", "details": "loose watercolour portrait, soft washes, granulating pigment, white paper glow"},
}

# How closely a photo-based portrait follows the visitor's photo
# (Stable Image Control Structure "control_strength").
LIKENESS = {
    # blend: AlphaFace face-swap strength (SageMaker). strength: Control Structure fallback.
    "artistic": {"label": "Artistic", "hint": "Loose, painterly reinterpretation", "blend": 0.7, "strength": 0.45},
    "balanced": {"label": "Balanced", "hint": "Recognisably you, fully in period", "blend": 0.88, "strength": 0.6},
    "faithful": {"label": "Faithful", "hint": "Your face, as true as possible", "blend": 1.0, "strength": 0.75},
}
DEFAULT_LIKENESS = "balanced"

MAX_IDEA_LENGTH = 200
# Decoded upload size limit; the browser resizes photos to ~1 MP JPEG (~150-400 KB) first.
MAX_PHOTO_BYTES = 4 * 1024 * 1024


def public_options():
    """Options as served to the browser."""
    return {
        "eras": [{"id": k, "label": v["label"], "years": v["years"], "emoji": v["emoji"]} for k, v in ERAS.items()],
        "roles": [{"id": k, "label": v} for k, v in ROLES.items()],
        "styles": [{"id": k, "label": v["label"]} for k, v in STYLES.items()],
        "likeness": [{"id": k, "label": v["label"], "hint": v["hint"]} for k, v in LIKENESS.items()],
        "defaultLikeness": DEFAULT_LIKENESS,
        "maxIdeaLength": MAX_IDEA_LENGTH,
        "maxPhotoBytes": MAX_PHOTO_BYTES,
    }
