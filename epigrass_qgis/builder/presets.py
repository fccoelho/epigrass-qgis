"""Disease parameter presets for the model builder wizard.

Values follow common epidemiological literature defaults and the conventions
used in the Epigrass demos.  They are starting points, not prescriptions:
users are expected to review them in the wizard.
"""

from __future__ import annotations

PRESETS = {
    "Custom (no preset)": {
        "model": "SEIR",
        "params": {"beta": "0.4", "alpha": "1", "e": "0.2", "r": "0.14",
                   "delta": "0", "B": "0", "w": "0", "p": "0"},
        "inits": {"S": "N", "E": "10", "I": "0"},
        "description": "Generic SEIR starting point.",
    },
    "Seasonal influenza": {
        "model": "SIR",
        "params": {
            # R0 ~ 1.3, infectious period ~ 4 days -> r = 0.25, beta = R0 * r
            "beta": "0.325", "alpha": "1", "e": "0.5", "r": "0.25",
            "delta": "0", "B": "0", "w": "0", "p": "0",
        },
        "inits": {"S": "N", "E": "10", "I": "0"},
        "description": "SIR, R0 ~ 1.3, 4-day infectious period.",
    },
    "COVID-19 (ancestral)": {
        "model": "SEIR",
        "params": {
            # R0 ~ 2.5, latent 5 d (e=0.2), infectious 7 d (r~0.14), beta = R0 * r
            "beta": "0.36", "alpha": "1", "e": "0.2", "r": "0.14",
            "delta": "0", "B": "0", "w": "0", "p": "0",
        },
        "inits": {"S": "N", "E": "10", "I": "0"},
        "description": "SEIR, R0 ~ 2.5, 5-day incubation, 7-day infectious period.",
    },
    "Measles": {
        "model": "SIR",
        "params": {
            # R0 ~ 15, infectious ~ 7 d -> r ~ 0.14, beta = R0 * r
            "beta": "2.14", "alpha": "1", "e": "0.5", "r": "0.14",
            "delta": "0", "B": "0", "w": "0", "p": "0",
        },
        "inits": {"S": "N", "E": "5", "I": "0"},
        "description": "SIR, R0 ~ 15 — very fast spread, lifelong immunity.",
    },
    "Dengue (host population)": {
        "model": "SEIR",
        "params": {
            # Host-side approximation: latent 5 d (e=0.2), viraemic 5 d (r=0.2)
            "beta": "0.4", "alpha": "1", "e": "0.2", "r": "0.2",
            "delta": "0", "B": "0", "w": "0", "p": "0",
        },
        "inits": {"S": "N", "E": "10", "I": "0"},
        "description": "SEIR host approximation (vector dynamics not modelled).",
    },
    "Influenza pandemic (1918-like)": {
        "model": "SEIR",
        "params": {
            # R0 ~ 2, latent 1.5 d (e~0.67), infectious 4 d (r=0.25)
            "beta": "0.5", "alpha": "1", "e": "0.67", "r": "0.25",
            "delta": "0", "B": "0", "w": "0", "p": "0",
        },
        "inits": {"S": "N", "E": "10", "I": "0"},
        "description": "SEIR, R0 ~ 2, short incubation.",
    },
}


def preset_names() -> list:
    return list(PRESETS)


def get_preset(name: str) -> dict:
    """Return a deep copy of the preset *name* (raises KeyError if unknown)."""
    import copy

    return copy.deepcopy(PRESETS[name])
