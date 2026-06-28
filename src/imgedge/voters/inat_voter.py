"""Wrap the iNaturalist taxon filter (TFLite/ONNX backend) as an ensemble voter."""

from imgedge.voters.base import Voter


class InatVoter(Voter):
    def __init__(self, model, threshold=0.5, weight=1.0):
        super().__init__(threshold, weight)
        self.model = model  # TaxonFilter or OnnxTaxonFilter
        self.target = getattr(model, "target", "?")
        self.name = f"inat:{str(self.target).lower()}"
        self.match_count = getattr(model, "match_count", 0)
        self.provider = getattr(model, "provider", None)
        self.backend = getattr(model, "backend", None)

    def score(self, img):
        return self.model.score(img)
