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

from imgedge.inat.inat_filter import open_guarded  # reuse decode hardening
from imgedge.voters.salience import image_salience


class Voter:
    name = "voter"

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
    def __init__(self, voters, policy="any", threshold=0.5):
        self.voters = list(voters)
        self.policy = policy
        self.threshold = float(threshold)
        self.inat = None  # set by the server for backward-compatible health fields

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

    def classify(self, img, meta=None, threshold=None, salience=None):
        rows = []  # (voter, score, evidence)
        for v in self.voters:
            try:
                s, e = v.assess(img)
            except Exception:
                s, e = 0.0, 0.0  # a broken voter abstains, never crashes the verdict
            rows.append((v, float(s), float(e)))

        if self.policy == "evidence":
            return self._evidence_verdict(rows, img, meta, threshold, salience)

        # ---- discrete policies (any / all / majority / weighted) ------------
        results = [(v, s >= v.threshold, s) for (v, s, _) in rows]
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

    def _evidence_verdict(self, rows, img, meta, threshold=None, salience=None):
        """Sum signed evidence, scale the positive part by image salience, then
        threshold. Positive evidence (real arachnid) pushes toward a block and
        is amplified for large/photographic images; negative evidence (a
        look-alike) always pulls fully away.

        `threshold` and `salience` are optional per-request overrides (the popup
        sliders): `threshold` replaces the ensemble threshold; `salience` in
        [0, 1] dials the size/detail weighting (0 = off -> mult forced to 1.0;
        1 = full). Because `combined` does not depend on the threshold, a block
        at one threshold stays blocked at every lower threshold."""
        pos = sum(v.weight * e for (v, _, e) in rows if e > 0)
        neg = sum(v.weight * e for (v, _, e) in rows if e < 0)  # <= 0
        try:
            mult, breakdown = image_salience(img, meta)
        except Exception:
            mult, breakdown = 1.0, {}
        if salience is not None:
            mult = 1.0 + salience * (mult - 1.0)  # 0 -> no weighting; 1 -> full
        thr = self.threshold if threshold is None else threshold
        combined = max(0.0, min(1.0, pos * mult + neg))
        block = combined >= thr
        supporters = [v.name for (v, _, e) in rows if e > 0]
        dampers = [v.name for (v, _, e) in rows if e < 0]
        return {
            "block": block,
            "reason": (",".join(supporters) if supporters else "ok") if block else "ok",
            "score": round(combined, 4),
            "votes": {v.name: round(e, 4) for (v, _, e) in rows},
            "salience": breakdown.get("salience", round(mult, 3)),
            "dampers": dampers,
            "dbg": {
                "policy": self.policy,
                "threshold": round(thr, 4),
                "pos": round(pos, 4), "neg": round(neg, 4), "mult": round(mult, 3),
                "salience": breakdown,
                "voters": [{
                    "name": v.name, "score": round(s, 4), "evidence": round(e, 4),
                    "weight": v.weight, "thr": v.threshold,
                    "contrib": round(v.weight * e * (mult if e > 0 else 1.0), 4),
                } for (v, s, e) in rows],
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
