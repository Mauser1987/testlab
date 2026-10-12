"""Inputs shared by make_golden.py (reference tool) and test_facemeasure_parity.py (Python port).

Options are given as the reference viewers' form fields hold them (strings).
"""

from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "facemeasure"
MAHR_LEFT = "JRO-003L.TXT"
MAHR_RIGHT = "JRO-004R.TXT"
ROUNDPAK_CSV = "ROUNDPAK-SIC30-post.csv"


def fixture_text(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def flagged_roundpak(text):
    """The fixture with Delete Flags set on some circular and radial points (incl. the circular LFD extremes)."""
    out, block, row = [], 0, 0
    for line in text.split("\n"):
        if line.startswith("Curve No."):
            block += 1
            row = 0
        elif block and line[:1].isdigit():
            row += 1
            if (block == 1 and (100 <= row < 160 or 2090 <= row < 2110 or row % 997 == 0)) or (block == 2 and 40 <= row < 45):
                line = line[: line.rfind(",") + 1] + "1"
        out.append(line)
    return "\n".join(out)


MAHR_CASES = [
    {"od": "5.034", "id": "4.634", "units": "in", "band": "0.29", "leftDir": "in", "rightDir": "out",
     "leftStart": "0", "leftEnd": "9", "rightStart": "0", "rightEnd": "9"},
    {"od": "128", "id": "117", "units": "mm", "band": "0.3", "leftDir": "out", "rightDir": "in",
     "leftStart": "1", "leftEnd": "7", "rightStart": "0.5", "rightEnd": "8.5"},
    {"od": "5.034", "id": "4.634", "units": "in", "band": "0.29", "leftDir": "in", "rightDir": "in",
     "leftStart": "2.25", "leftEnd": "6.1", "rightStart": "0", "rightEnd": "4.333", "swap": True},
]
MAHR_ERRORS = [
    {"od": "4", "id": "5", "units": "in", "band": "0.29", "leftDir": "in", "rightDir": "out",
     "leftStart": "0", "leftEnd": "9", "rightStart": "0", "rightEnd": "9"},
    {"od": "5.034", "id": "4.634", "units": "in", "band": "0.29", "leftDir": "in", "rightDir": "out",
     "leftStart": "0", "leftEnd": "9.5", "rightStart": "0", "rightEnd": "9"},
    {"od": "5.034", "id": "4.634", "units": "in", "band": "0.29", "leftDir": "in", "rightDir": "out",
     "leftStart": "3", "leftEnd": "3.0005", "rightStart": "0", "rightEnd": "9"},
]
ROUNDPAK_CASES = [
    {"od": "", "id": "", "units": "mm", "band": "0.29", "circleSelect": "0", "circleSource": "deviation",
     "leftSelect": "2", "rightSelect": "1", "radialSource": "deviation",
     "leftStart": "59.42", "leftEnd": "61.71", "rightStart": "59.42", "rightEnd": "61.71"},
    {"od": "5.034", "id": "4.634", "units": "in", "band": "0.3", "circleSelect": "0", "circleSource": "extracted",
     "leftSelect": "1", "rightSelect": "2", "radialSource": "profile",
     "leftStart": "59.5", "leftEnd": "61.5", "rightStart": "59.6", "rightEnd": "61.2"},
    {"od": "128", "id": "117", "units": "mm", "band": "0.29", "circleSelect": "0", "circleSource": "profile",
     "leftSelect": "2", "rightSelect": "1", "radialSource": "extracted",
     "leftStart": "59.42", "leftEnd": "61.71", "rightStart": "59.42", "rightEnd": "61.71", "flagged": True},
]
ROUNDPAK_ERRORS = [
    {**ROUNDPAK_CASES[0], "od": "5", "id": ""},
    {**ROUNDPAK_CASES[0], "leftSelect": "1", "rightSelect": "1"},
    {**ROUNDPAK_CASES[0], "leftStart": "50"},
]

def bad_mahr(text):
    lines = text.split("\n")
    profile = lines.index("[PROFILE]")
    return [
        {"label": "count_mismatch", "text": "\n".join(lines[: profile + 1] + lines[profile + 2:])},
        {"label": "non_numeric", "text": "\n".join(lines[: profile + 5] + ["12a"] + lines[profile + 6:])},
        {"label": "no_cnt", "text": "\n".join(l for l in lines if not l.startswith("CNT="))},
        {"label": "zero_res", "text": text.replace("RES=0.00640889", "RES=0")},
    ]


def bad_roundpak(text):
    lines = text.split("\n")
    first_data = next(i for i, l in enumerate(lines) if l.startswith("Curve No.")) + 1
    gap = lines[: first_data + 3] + lines[first_data + 4:]
    dup = lines[:]
    dup[first_data + 4] = dup[first_data + 3]
    return [
        {"label": "gap", "text": "\n".join(gap)},
        {"label": "duplicate", "text": "\n".join(dup)},
        {"label": "bad_number", "text": "\n".join(lines[: first_data + 2] + ["1,3,0.05,x,0.1,0.1,0"] + lines[first_data + 3:])},
        {"label": "columns", "text": text.replace("LFD (µm)", "LFX (µm)")},
        {"label": "mm_heights", "text": text.replace("Profile (µm)", "Profile (mm)")},
        {"label": "empty", "text": "Title,x\n"},
    ]


# ---- v5 (Seal_Face_Flatness_Claude_v5.html, engines mahr-2 / roundpak-2) ----------------------
# Options as the v5 form fields hold them. Mahr: the left and right fixtures in the default
# directions (left OD → ID, right ID → OD), whole scans. ROUNDPAK: the first two radial blocks
# (v5 trace 1 = right scan "1", trace 2 = left scan "2"), whole scans, one data column for all.
V5_MAHR_CASES = [
    {"od": "5.084", "id": "4.634", "unit": "in", "skip": "5", "hlb": "0.29", "lim": "0.25"},
    {"od": "128", "id": "117", "unit": "mm", "skip": "0", "hlb": "0.3", "lim": "0.05"},
    {"od": "5.034", "id": "4.634", "unit": "in", "skip": "37", "hlb": "0.29", "lim": "0.01", "swap": True},
]
V5_ROUNDPAK_CASES = [
    {"od": "5.084", "id": "4.634", "unit": "in", "col": "5", "hlb": "0.29", "lim": "0.25"},
    {"od": "128", "id": "117", "unit": "mm", "col": "4", "hlb": "0.3", "lim": "1.5"},
    {"od": "5.034", "id": "4.634", "unit": "in", "col": "3", "hlb": "0.29", "lim": "0.25", "flagged": True},
    {"od": "", "id": "", "unit": "in", "col": "5", "hlb": "0.29", "lim": "0.25"},
]
V5_ROUNDPAK_COLUMNS = {"5": "deviation", "4": "profile", "3": "extracted"}


def lenient_mahr(text):
    """Files v5 still reads (with a warning), and one it refuses."""
    lines = text.split("\n")
    profile = lines.index("[PROFILE]")
    return [
        {"label": "count_mismatch", "text": "\n".join(lines[: profile + 1] + lines[profile + 2:])},
        {"label": "non_numeric", "text": "\n".join(lines[: profile + 5] + ["12a"] + lines[profile + 6:])},
        {"label": "no_cnt", "text": "\n".join(l for l in lines if not l.startswith("CNT="))},
        {"label": "decimal_comma", "text": text.replace("RES=0.00640889", "RES=0,00640889")},
        {"label": "zero_res", "text": text.replace("RES=0.00640889", "RES=0")},
    ]
