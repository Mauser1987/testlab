"""Regenerate golden.json: the reference tool's own results for the fixtures.

    python app/testlab/results/tests/fixtures/facemeasure/make_golden.py [path/to/Seal_Face_Measurement_Tools.html]

Runs the calculation functions the offline viewers expose
(window.ProfileCore, window.RoundpakCore) in Playwright's Chromium on the
fixture files and on variations of them (other directions, intervals,
units, sources, deleted points, invalid files). test_facemeasure_parity.py
requires the Python port to reproduce these numbers and refusals. Needs
the reference HTML (reference/ is not in the repository); run it only when
the reference tool changes.
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
from testlab.results.tests.facemeasure_variants import (  # noqa: E402
    MAHR_CASES, MAHR_ERRORS, MAHR_LEFT, MAHR_RIGHT, ROUNDPAK_CASES, ROUNDPAK_CSV, ROUNDPAK_ERRORS, bad_mahr,
    bad_roundpak, fixture_text, flagged_roundpak,
)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
DEFAULT_REFERENCE = REPO / "reference" / "measurement-tools" / "Seal_Face_Measurement_Tools.html"


def viewers(reference):
    line = next(l for l in reference.read_text(encoding="utf-8").splitlines() if l.startswith("const VIEWERS="))
    data, _ = json.JSONDecoder().raw_decode(line[len("const VIEWERS="):])
    return data


MAHR_JS = """([left, right, cases, errors, bad]) => {
  const C = window.ProfileCore, out = {cases: [], errors: [], parse_errors: []};
  const L = C.parseMahr(left.text, left.name), R = C.parseMahr(right.text, right.name);
  out.profiles = [L, R].map(p => ({name: p.name, count: p.count, length: p.length, resolution: p.resolution,
                                    reported: p.reported, headers: p.headers}));
  for (const c of cases) {
    const [l, r] = c.swap ? [R, L] : [L, R];
    const a = C.calculate(l, r, c), pv = {};
    for (const view of ['raw', 'common', 'residual']) {
      pv[view] = {};
      for (const [side, f] of [['left', a.l], ['right', a.r]]) {
        let lo = Infinity, hi = -Infinity;
        for (let i = f.first; i <= f.last; i++) { const y = C.height(f, i, view, a.common); lo = Math.min(lo, y); hi = Math.max(hi, y); }
        pv[view][side] = hi - lo;
      }
    }
    out.cases.push({options: c, width: a.width, common: a.common, taper: a.taper, hlb: a.hlb,
      classification: a.classification, pv,
      left: {m: a.l.m, b: a.l.b, meanZ: a.l.meanZ, first: a.l.first, last: a.l.last},
      right: {m: a.r.m, b: a.r.b, meanZ: a.r.meanZ, first: a.r.first, last: a.r.last}});
  }
  for (const c of errors) { try { C.calculate(L, R, c); out.errors.push({options: c, error: null}); }
                            catch (e) { out.errors.push({options: c, error: e.message}); } }
  for (const b of bad) { try { C.parseMahr(b.text, 'bad'); out.parse_errors.push({label: b.label, error: null}); }
                         catch (e) { out.parse_errors.push({label: b.label, error: e.message}); } }
  return out;
}"""

ROUNDPAK_JS = """([file, flagged, cases, errors, bad]) => {
  const C = window.RoundpakCore, out = {cases: [], errors: [], parse_errors: []};
  const plain = C.parseRoundpak(file.text, file.name), withFlags = C.parseRoundpak(flagged, file.name);
  const ev = f => f && {source: f.source, start: f.start, end: f.end, selected: f.selected.length, used: f.used.length,
                        lo: f.lo, hi: f.hi, pv: f.pv, m: f.m, b: f.b, min_x: f.minPoint.x, max_x: f.maxPoint.x};
  const scans = f => f.scans.map(s => ({id: s.id, kind: s.kind, name: s.name, curve: s.curve, points: s.points.length,
                         min: s.min, max: s.max, complete: s.complete, flagged: s.points.filter(p => p.flag !== 0).length,
                         params: s.params, line: s.line, meta: s.meta}));
  out.scans = scans(plain); out.flagged_scans = scans(withFlags);
  for (const c of cases) {
    const a = C.calculate(c.flagged ? withFlags : plain, c);
    out.cases.push({options: c, circular: ev(a.circular), lfd: ev(a.lfd), left: ev(a.left), right: ev(a.right),
      reported: a.reported, width: a.width, meanSlope: a.meanSlope, taper: a.taper, separation: a.separation});
  }
  for (const c of errors) { try { C.calculate(plain, c); out.errors.push({options: c, error: null}); }
                            catch (e) { out.errors.push({options: c, error: e.message}); } }
  for (const b of bad) { try { C.parseRoundpak(b.text, 'bad'); out.parse_errors.push({label: b.label, error: null}); }
                         catch (e) { out.parse_errors.push({label: b.label, error: e.message}); } }
  return out;
}"""


def main():
    reference = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_REFERENCE
    pages = viewers(reference)
    left, right, csv = fixture_text(MAHR_LEFT), fixture_text(MAHR_RIGHT), fixture_text(ROUNDPAK_CSV)
    flagged = flagged_roundpak(csv)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(pages["mahr"])
        mahr = page.evaluate(MAHR_JS, [{"name": MAHR_LEFT, "text": left}, {"name": MAHR_RIGHT, "text": right},
                                       MAHR_CASES, MAHR_ERRORS, bad_mahr(left)])  # fmt: skip
        page = browser.new_page()  # fresh realm: the viewers declare the same globals
        page.set_content(pages["roundpak"])
        roundpak = page.evaluate(ROUNDPAK_JS, [{"name": ROUNDPAK_CSV, "text": csv}, flagged,
                                               ROUNDPAK_CASES, ROUNDPAK_ERRORS, bad_roundpak(csv)])  # fmt: skip
        browser.close()
    golden = {"reference": reference.name, "mahr": mahr, "roundpak": roundpak}
    (HERE / "golden.json").write_text(json.dumps(golden, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"golden.json written from {reference}")


if __name__ == "__main__":
    main()
