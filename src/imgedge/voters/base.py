"""Voting ensemble: combine several image classifiers into one verdict.

Each Voter scores an image in [0, 1] (probability it should be blocked) and
votes "block" if its score crosses its own threshold. The ensemble then combines
the votes by policy:

  evidence  sum each voter's SIGNED evidence, scale the positive part by image
            salience (size / detail / surface), then threshold (default)
  any       block if any voter blocks       (aggressive avoidance)
  all       block only if every voter blocks (conservative)
  majority  block if more than half block
  weighted  block if the blocking voters' weight is >= half the total weight

Under the "evidence" policy a voter may argue *against* a block (negative
evidence) -- e.g. the second model recognising a non-arachnid look-alike -- and
the positive evidence is scaled by how salient the image is (see salience.py),
so big photorealistic close-ups block hard while tiny/stylised/fleeting images
slip through more easily.

The image is decoded once (with the same hardening as the single-model path)
and the open PIL image is handed to each voter, so codecs run only once.
"""

import time

from imgedge.inat.inat_filter import open_guarded  # reuse decode hardening
from imgedge.voters.salience import image_salience


class Voter:
    name = "voter"
    deferred = False  # if True, the ensemble runs this voter only when the cheap
    # voters leave the score near the threshold (see VoteEnsemble cascade gate).

    def __init__(self, threshold=0.5, weight=1.0):
        self.threshold = float(threshold)
        self.weight = float(weight)

    def score(self, img):
        """Return P(block) in [0, 1] for an already-decoded PIL image."""
        raise NotImplementedError

    def assess(self, img):
        """Return (score, evidence) from a single inference.

        score    in [0, 1]   P(block), used for discrete votes and reporting.
        evidence in [-1, 1]  signed contribution; negative argues *against* a
                             block. Default: evidence == score (positive only).
        Override in voters that can produce negative evidence so they share one
        forward pass between score and evidence.
        """
        s = self.score(img)
        return s, s

    def vote(self, img):
        s, _ = self.assess(img)
        return (s >= self.threshold, s)


class VoteEnsemble:
    def __init__(self, voters, policy="any", threshold=0.5, inat_override=1.01, gate=0.0):
        self.voters = list(voters)
        self.policy = policy
        self.threshold = float(threshold)
        self.inat = None  # set by the server for backward-compatible health fields
        # iNat (real-organism) confidence at/above which it blocks outright,
        # regardless of the contrast voter. >1.0 disables the override.
        self.inat_override = float(inat_override)
        # Cascade gate: skip the deferred (expensive) voters when the cheap-voter
        # combined score is below this floor -- they can't realistically rescue
        # an image the cheap voters see nothing in. 0.0 = always run them.
        self.gate = float(gate)

    @property
    def names(self):
        return [v.name for v in self.voters]

    def classify_bytes(self, raw, meta=None, decoder=None, threshold=None, salience=None):
        if decoder is not None:
            # Decode out-of-process; reconstruct from a trusted RGB array.
            from PIL import Image

            arr, ow, oh = decoder.decode(raw)
            meta = dict(meta or {})
            meta.setdefault("w", ow)  # keep the true size for salience
            meta.setdefault("h", oh)
            return self.classify(Image.fromarray(arr), meta, threshold, salience)
        with open_guarded(raw) as img:
            return self.classify(img, meta, threshold, salience)

    def _assess(self, v, img):
        """Run one voter, isolating failures: a broken voter abstains (0, 0).
        The voter's wall-clock cost is recorded in its breakdown as ``ms``."""
        t0 = time.perf_counter()
        try:
            out = v.assess(img)
            d = out[2] if len(out) > 2 else None  # optional per-voter breakdown
            ms = round((time.perf_counter() - t0) * 1000, 3)
            return (v, float(out[0]), float(out[1]), {**(d or {}), "ms": ms})
        except Exception:
            ms = round((time.perf_counter() - t0) * 1000, 3)
            return (v, 0.0, 0.0, {"ms": ms, "error": True})  # never crash the verdict

    def classify(self, img, meta=None, threshold=None, salience=None):
        deferred = [v for v in self.voters if getattr(v, "deferred", False)]
        if deferred and self.policy == "evidence":
            # Cascade: assess the cheap voters first; run the expensive
            # (deferred) voters only when the cheap score lands in the band where
            # they could still change the verdict -- at/above threshold it
            # already blocks; below `gate` they realistically can't rescue it.
            # Skips the heavy voter on the bulk of clearly-allow images.
            rows = [self._assess(v, img) for v in self.voters if not getattr(v, "deferred", False)]
            cheap = self._combine(rows, img, meta, threshold, salience)[0]
            thr = self.threshold if threshold is None else threshold
            if self.gate <= cheap < thr:
                rows += [self._assess(v, img) for v in deferred]
            else:
                rows += [(v, 0.0, 0.0, {"skipped": True, "ms": 0.0}) for v in deferred]
        else:
            rows = [self._assess(v, img) for v in self.voters]

        if self.policy == "evidence":
            return self._evidence_verdict(rows, img, meta, threshold, salience)

        # ---- discrete policies (any / all / majority / weighted) ------------
        results = [(v, s >= v.threshold, s) for (v, s, _, _) in rows]
        block = self._decide(results)
        blockers = [v.name for (v, b, _) in results if b]
        scores = {v.name: round(s, 4) for (v, _, s) in results}
        top = max((s for (_, _, s) in results), default=0.0)
        return {
            "block": block,
            "reason": ",".join(blockers) if block and blockers else "ok",
            "score": round(top, 4),
            "votes": scores,
        }

    def _combine(self, rows, img, meta, threshold=None, salience=None):
        """Core evidence math shared by the cascade gate and the final verdict.
        Returns (combined, pos, neg, mult, breakdown, override, inat_score).

        Sum signed evidence, scale the positive part by image salience (boost-
        only), then apply the iNat-confidence override."""
        pos = sum(v.weight * e for (v, _, e, _) in rows if e > 0)
        neg = sum(v.weight * e for (v, _, e, _) in rows if e < 0)  # <= 0
        try:
            mult, breakdown = image_salience(img, meta)
        except Exception:
            mult, breakdown = 1.0, {}
        if salience is not None:
            mult = 1.0 + salience * (mult - 1.0)  # 0 -> no weighting; 1 -> full
        mult = max(1.0, mult)  # boost-only: salience amplifies, never suppresses
        combined = max(0.0, min(1.0, pos * mult + neg))
        inat_score = next((s for (v, s, _, _) in rows if v is self.inat), None)
        override = inat_score is not None and inat_score >= self.inat_override
        if override:
            combined = max(combined, inat_score)  # confident real organism pins the score
        return combined, pos, neg, mult, breakdown, override, inat_score

    def _evidence_verdict(self, rows, img, meta, threshold=None, salience=None):
        """Sum signed evidence, scale the positive part by image salience, then
        threshold. Positive evidence (real arachnid) pushes toward a block and
        is amplified for large/photographic images; negative evidence (a
        look-alike) always pulls fully away.

        `threshold` and `salience` are optional per-request overrides (the popup
        sliders): `threshold` replaces the ensemble threshold; `salience` in
        [0, 1] dials the size/detail weighting (0 = off -> mult forced to 1.0;
        1 = full). Because `combined` does not depend on the threshold, a block
        at one threshold stays blocked at every lower threshold.

        If the iNat voter is present and its own P(block) reaches
        `inat_override`, it blocks outright: a confident real-organism match is
        not vetoed by the look-alike contrast voter's negative evidence."""
        combined, pos, neg, mult, breakdown, override, inat_score = self._combine(rows, img, meta, threshold, salience)
        thr = self.threshold if threshold is None else threshold
        block = override or combined >= thr

        supporters = [v.name for (v, _, e, _) in rows if e > 0]
        dampers = [v.name for (v, _, e, _) in rows if e < 0]
        return {
            "block": block,
            "reason": (",".join(supporters) if supporters else "ok") if block else "ok",
            "score": round(combined, 4),
            "votes": {v.name: round(e, 4) for (v, _, e, _) in rows},
            "salience": breakdown.get("salience", round(mult, 3)),
            "dampers": dampers,
            "dbg": {
                "policy": self.policy,
                "threshold": round(thr, 4),
                "pos": round(pos, 4),
                "neg": round(neg, 4),
                "mult": round(mult, 3),
                "inat_override": round(self.inat_override, 3),
                "override": override,
                "salience": breakdown,
                "voters": [
                    {
                        "name": v.name,
                        "score": round(s, 4),
                        "evidence": round(e, 4),
                        "weight": v.weight,
                        "thr": v.threshold,
                        "contrib": round(v.weight * e * (mult if e > 0 else 1.0), 4),
                        "details": d,
                    }
                    for (v, s, e, d) in rows
                ],
            },
        }

    def _decide(self, results):
        n = len(results)
        if n == 0:
            return False
        nb = sum(1 for (_, b, _) in results if b)
        if self.policy == "all":
            return nb == n
        if self.policy == "majority":
            return nb > n / 2
        if self.policy == "weighted":
            total = sum(v.weight for (v, _, _) in results) or 1.0
            wblock = sum(v.weight for (v, b, _) in results if b)
            return (wblock / total) >= 0.5
        return nb >= 1  # "any" (default)
