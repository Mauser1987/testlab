"""Regenerate golden_v5.json: Seal_Face_Flatness_Claude_v5.html's own results for the fixtures.

    python app/testlab/results/tests/fixtures/facemeasure/make_golden_v5.py [path/to/Seal_Face_Flatness_Claude_v5.html]

v5 exposes no calculation API, so the page is driven as a person uses it
(Playwright's Chromium): the form fields are set, the fixture files are
loaded through the file inputs, and the results are read from the state
the page keeps (window.__faces, window.__rp). test_facemeasure_parity.py
requires engines mahr-2 / roundpak-2 to reproduce these numbers. Needs the
reference HTML (reference/ is not in the repository); run it only when the
reference tool changes.
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
from testlab.results.tests.facemeasure_variants import (  # noqa: E402
    MAHR_LEFT, MAHR_RIGHT, ROUNDPAK_CSV, V5_MAHR_CASES, V5_ROUNDPAK_CASES, fixture_text, flagged_roundpak,
    lenient_mahr,
)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
DEFAULT_REFERENCE = REPO / "reference" / "measurement-tools" / "Seal_Face_Flatness_Claude_v5.html"

SET = """([id, value]) => { const e = document.getElementById(id); e.value = value;
  e.dispatchEvent(new Event(e.tagName === 'SELECT' ? 'change' : 'input', {bubbles: true})); }"""

MAHR_RESULT = """() => {
  const f = window.__faces[0], r = f.res, fin = v => Number.isFinite(v) ? v : null;
  if (!r || r.error) return {error: r ? r.error : null};
  const fit = x => ({m: x.m, b: x.b, n: x.n, mean: x.mean}), pv = {};
  for (const view of ['common', 'raw', 'resid']) {
    pv[view] = {};
    for (const side of ['L', 'R']) {
      const h = r.views[view][side]; let lo = Infinity, hi = -Infinity;
      for (let i = r.skip; i < h.length; i++) { lo = Math.min(lo, h[i]); hi = Math.max(hi, h[i]); }
      pv[view][side] = hi - lo;
    }
  }
  return {left: fit(r.fl), right: fit(r.fr), common: r.avg, width: fin(r.W), taper: fin(r.taper), hlb: fin(r.hlb),
          verdict: r.verdict, pv};
}"""

ROUNDPAK_RESULT = """() => {
  const r = window.__rp.res, fin = v => Number.isFinite(v) ? v : null;
  return {wav: r.wav, hi: r.wavHi, lo: r.wavLo, angHi: r.angHi, angLo: r.angLo,
          harm: r.harm.map(h => [h.k, h.amp, h.phase]),
          traces: r.T.map(t => ({angle: t.b.angle, m: t.f.m, n: t.f.n})),
          cone: r.cone, tilt: r.tilt, width: fin(r.W), taper: fin(r.taper), hlb: fin(r.hlb), verdict: r.verdict};
}"""


def load(page, selector, name, text, ready):
    page.set_input_files(selector, files=[{"name": name, "mimeType": "text/plain", "buffer": text.encode("utf-8")}])
    page.wait_for_function(ready, arg=name)


def mahr_slot(page, side, name, text):
    load(page, f"#stat-file{side}", name, text,
         f"n => (window.__faces[0].{side} && window.__faces[0].{side}.name === n) || "
         f"document.querySelector('.slot[data-side=\"{side}\"] .err').textContent !== ''")  # fmt: skip


def mahr_golden(page, left, right):
    out = {"cases": [], "lenient": []}
    for k, case in enumerate(V5_MAHR_CASES):
        for field, value in (("stat-od", case["od"]), ("stat-id", case["id"]), ("sUnit", case["unit"]),
                             ("sSkip", case["skip"]), ("sHlb", case["hlb"]), ("sLim", case["lim"])):
            page.evaluate(SET, [field, value])
        a, b = (right, left) if case.get("swap") else (left, right)
        mahr_slot(page, "L", f"case{k}-{a['name']}", a["text"])
        mahr_slot(page, "R", f"case{k}-{b['name']}", b["text"])
        out["cases"].append({"options": case, **page.evaluate(MAHR_RESULT)})
    for field, value in (("stat-od", "5.084"), ("stat-id", "4.634"), ("sUnit", "in"), ("sSkip", "5"),
                         ("sHlb", "0.29"), ("sLim", "0.25")):
        page.evaluate(SET, [field, value])
    mahr_slot(page, "R", "lenient-right", right["text"])
    for variant in lenient_mahr(left["text"]):
        page.evaluate("() => { document.querySelector('.slot[data-side=\"L\"] .err').textContent = ''; }")
        mahr_slot(page, "L", f"lenient-{variant['label']}", variant["text"])
        error = page.evaluate("() => document.querySelector('.slot[data-side=\"L\"] .err').textContent")
        found = {"label": variant["label"], "error": error or None}
        if not error:
            found.update(page.evaluate("() => { const t = window.__faces[0].L; return {count: t.n, spacing: t.CNT, "
                                       "warning: t.warn}; }"))  # fmt: skip
            found.update(page.evaluate(MAHR_RESULT))
        out["lenient"].append(found)
    return out


def roundpak_golden(page, csv, flagged):
    out = {"cases": []}
    for k, case in enumerate(V5_ROUNDPAK_CASES):
        band = float(case["hlb"])
        for field, value in (("rpId", case["id"]), ("rpOd", case["od"]), ("rpUnitSel", case["unit"]),
                             ("rpCol", case["col"]), ("rpHlbUm", case["hlb"]),
                             ("rpLim", repr(float(case["lim"]) * band))):  # v5's limit is in µm
            page.evaluate(SET, [field, value])
        load(page, "#rpInput", f"case{k}.csv", flagged if case.get("flagged") else csv,
             "n => window.__rp.data && window.__rp.data.name === n")
        out["cases"].append({"options": case, **page.evaluate(ROUNDPAK_RESULT)})
    return out


def main():
    reference = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_REFERENCE
    left = {"name": MAHR_LEFT, "text": fixture_text(MAHR_LEFT)}
    right = {"name": MAHR_RIGHT, "text": fixture_text(MAHR_RIGHT)}
    csv = fixture_text(ROUNDPAK_CSV)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        page.goto(reference.resolve().as_uri())
        page.wait_for_function("() => window.__faces && window.__rp && window.__rp.data")
        mahr = mahr_golden(page, left, right)
        roundpak = roundpak_golden(page, csv, flagged_roundpak(csv))
        browser.close()
    golden = {"reference": reference.name, "mahr": mahr, "roundpak": roundpak}
    (HERE / "golden_v5.json").write_text(json.dumps(golden, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"golden_v5.json written from {reference}")


if __name__ == "__main__":
    main()
