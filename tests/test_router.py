from astra_pc.ai.router import ModelRouter


class FakeClient:
    def __init__(self, model, models=None):
        self.model = model
        self._models = models or []

    def models(self):
        return self._models


def test_router_vision():
    text = FakeClient("tiny")
    vision = FakeClient("vision")
    router = ModelRouter(text, vision)
    assert router.choose("anything", has_images=True) is vision


def test_router_simple_text():
    text = FakeClient("tiny")
    vision = FakeClient("vision")
    strong = FakeClient("strong:4b", ["strong:4b"])
    router = ModelRouter(text, vision, strong)
    assert router.choose("oi") is text
