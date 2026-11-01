import ast
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import client, flux3_variants as flux


PROMPT = "A red teapot"
IMAGES = [f"https://example.test/reference-{index}.png" for index in range(1, 11)]


class ConnectedImage:
    def __bool__(self):
        raise AssertionError("Image connections must not be coerced to bool")


class Flux3VariantsTests(unittest.TestCase):
    def arguments(self, model_id="flux-3-image-t2i", **changes):
        return {"model": model_id, "prompt": PROMPT, **changes}

    def expected(self, model, **changes):
        result = {
            "model": model, "prompt": PROMPT, "resolution": "1k",
            "aspect_ratio": "auto", "safety_tolerance": 2,
        }
        result.update({"seed": 0} if "-klein-" in model else {"grounding": True})
        return {**result, **changes}

    def test_exports_and_existing_size_contract(self):
        self.assertEqual(flux.__all__, ["MODELS", "RESOLUTIONS", "RATIOS", "validate", "payload"])
        self.assertEqual(flux.MODELS, [
            "flux-3-image-t2i", "flux-3-image-i2i",
            "flux-3-image-klein-t2i", "flux-3-image-klein-i2i",
        ])
        tree = ast.parse((ROOT / "nodes.py").read_text(encoding="utf-8"))
        constants = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {"FLUX3_IMAGE_RESOLUTIONS", "FLUX3_IMAGE_RATIOS"}
        }
        self.assertEqual(flux.RESOLUTIONS, constants["FLUX3_IMAGE_RESOLUTIONS"])
        self.assertEqual(flux.RATIOS, constants["FLUX3_IMAGE_RATIOS"])

    def test_default_model_and_exact_payloads_for_all_models(self):
        self.assertEqual(flux.payload({"prompt": "  " + PROMPT + "\n"}, []), self.expected(flux.MODELS[0]))
        for model in flux.MODELS:
            images = IMAGES[:2] if model.endswith("-i2i") else []
            expected = self.expected(model, images=images) if images else self.expected(model)
            with self.subTest(model=model):
                self.assertEqual(flux.payload(self.arguments(model), images), expected)
                result = flux.payload(self.arguments(model, n=1, metadata={"n": 1}), images)
                self.assertEqual(result, expected)
                self.assertNotIn("n", result)
                self.assertNotIn("n", result.get("metadata", {}))

    def test_exact_standard_payload_only_sends_standard_controls(self):
        for model in flux.MODELS[:2]:
            kwargs = self.arguments(model, resolution="768sq", aspect_ratio="1:1",
                                    grounding=False, safety_tolerance=4, seed=42, steps=16,
                                    output_format="png", metadata={"steps": 8}, n=9)
            images = IMAGES[:1] if model.endswith("-i2i") else []
            expected = self.expected(model, resolution="768sq", aspect_ratio="1:1",
                                     grounding=False, safety_tolerance=4)
            if images:
                expected["images"] = images
            with self.subTest(model=model):
                result = flux.payload(kwargs, images)
                self.assertEqual(result, expected)
                allowed = {"model", "prompt", "resolution", "aspect_ratio", "safety_tolerance", "grounding"}
                self.assertEqual(set(result), allowed | ({"images"} if images else set()))
                self.assertNotIn("n", result)

    def test_exact_klein_payload_with_all_controls(self):
        for model in flux.MODELS[2:]:
            kwargs = self.arguments(model, resolution="4k", aspect_ratio="21:9",
                                    safety_tolerance=0, seed=2147483647, steps=16,
                                    output_format="png", grounding="stale hidden value",
                                    metadata={"grounding": True, "other": True}, n=7)
            images = IMAGES[:2] if model.endswith("-i2i") else []
            expected = self.expected(model, resolution="4k", aspect_ratio="21:9",
                                     safety_tolerance=0, seed=2147483647,
                                     metadata={"steps": 16}, output_format="png")
            if images:
                expected["images"] = images
            with self.subTest(model=model):
                result = flux.payload(kwargs, images)
                self.assertEqual(result, expected)
                allowed = {"model", "prompt", "resolution", "aspect_ratio", "safety_tolerance",
                           "seed", "metadata", "output_format"}
                self.assertEqual(set(result), allowed | ({"images"} if images else set()))
                self.assertEqual(set(result["metadata"]), {"steps"})
                self.assertNotIn("n", result)

    def test_all_resolutions_and_ratios(self):
        for model in flux.MODELS:
            images = IMAGES[:1] if model.endswith("-i2i") else []
            for resolution in flux.RESOLUTIONS:
                for ratio in flux.RATIOS:
                    kwargs = self.arguments(model, resolution=resolution, aspect_ratio=ratio)
                    with self.subTest(model=model, resolution=resolution, ratio=ratio):
                        self.assertIs(flux.validate(kwargs), True)
                        result = flux.payload(kwargs, images)
                        self.assertEqual(result["resolution"], resolution)
                        self.assertEqual(result["aspect_ratio"], ratio)

    def test_invalid_common_options_return_strings_and_raise_api_errors(self):
        for model in flux.MODELS:
            images = IMAGES[:1] if model.endswith("-i2i") else []
            for changes in ({"model": "flux-3-image"}, {"model": None}, {"model": []},
                            {"resolution": "720p"}, {"resolution": None},
                            {"aspect_ratio": "8:1"}, {"aspect_ratio": None},
                            {"prompt": 42}, {"prompt": False}, {"prompt": ["linked", 0]}):
                kwargs = self.arguments(model, **changes)
                with self.subTest(model=model, changes=changes):
                    self.assertIsInstance(flux.validate(kwargs), str)
                    with self.assertRaises(client.SeedanceAPIError):
                        flux.payload(kwargs, images)

    def test_safety_tolerance_all_integer_values_for_all_models(self):
        for model in flux.MODELS:
            images = IMAGES[:1] if model.endswith("-i2i") else []
            for value in range(5):
                with self.subTest(model=model, value=value):
                    kwargs = self.arguments(model, safety_tolerance=value)
                    self.assertIs(flux.validate(kwargs), True)
                    result = flux.payload(kwargs, images)
                    self.assertEqual(result["safety_tolerance"], value)
                    self.assertIs(type(result["safety_tolerance"]), int)

    def test_numeric_controls_reject_bools_floats_strings_and_out_of_range(self):
        controls = {
            "safety_tolerance": (-1, 5, 0.0, 2.0, 2.5),
            "seed": (-1, 2147483648, 0.0, 42.0, 42.5),
            "steps": (-1, 17, 0.0, 1.0, 1.5),
        }
        for model in flux.MODELS:
            images = IMAGES[:1] if model.endswith("-i2i") else []
            for control, invalid in controls.items():
                if control != "safety_tolerance" and "-klein-" not in model:
                    continue
                for value in (*invalid, True, False, "0", "2", None, [], float("inf"), float("nan")):
                    kwargs = self.arguments(model, **{control: value})
                    with self.subTest(model=model, control=control, value=value):
                        self.assertIsInstance(flux.validate(kwargs), str)
                        with self.assertRaises(client.SeedanceAPIError):
                            flux.payload(kwargs, images)

    def test_klein_seed_boundaries_and_every_step(self):
        for model in flux.MODELS[2:]:
            images = IMAGES[:1] if model.endswith("-i2i") else []
            for seed in (0, 2147483647):
                for steps in range(17):
                    kwargs = self.arguments(model, seed=seed, steps=steps)
                    with self.subTest(model=model, seed=seed, steps=steps):
                        self.assertIs(flux.validate(kwargs), True)
                        result = flux.payload(kwargs, images)
                        self.assertEqual(result["seed"], seed)
                        if steps:
                            self.assertEqual(result["metadata"], {"steps": steps})
                        else:
                            self.assertNotIn("metadata", result)

    def test_klein_output_format_and_default_omission(self):
        for model in flux.MODELS[2:]:
            images = IMAGES[:1] if model.endswith("-i2i") else []
            for value in ("api_default", "jpeg", "png"):
                with self.subTest(model=model, value=value):
                    result = flux.payload(self.arguments(model, output_format=value), images)
                    if value == "api_default":
                        self.assertNotIn("output_format", result)
                    else:
                        self.assertEqual(result["output_format"], value)
            for value in ("webp", "jpg", "PNG", "", None, True, []):
                with self.subTest(model=model, value=value):
                    kwargs = self.arguments(model, output_format=value)
                    self.assertIsInstance(flux.validate(kwargs), str)
                    with self.assertRaises(client.SeedanceAPIError):
                        flux.payload(kwargs, images)

    def test_standard_grounding_requires_a_real_boolean(self):
        for model in flux.MODELS[:2]:
            images = IMAGES[:1] if model.endswith("-i2i") else []
            for value in (True, False):
                with self.subTest(model=model, value=value):
                    kwargs = self.arguments(model, grounding=value)
                    self.assertIs(flux.validate(kwargs), True)
                    self.assertIs(flux.payload(kwargs, images)["grounding"], value)
            for value in (0, 1, 0.0, 1.0, "true", "false", None, []):
                with self.subTest(model=model, value=value):
                    kwargs = self.arguments(model, grounding=value)
                    self.assertIsInstance(flux.validate(kwargs), str)
                    with self.assertRaises(client.SeedanceAPIError):
                        flux.payload(kwargs, images)

    def test_standard_ignores_even_invalid_stale_klein_controls(self):
        for model in flux.MODELS[:2]:
            images = IMAGES[:1] if model.endswith("-i2i") else []
            for stale in (-1, 2**64, True, 1.5, None, [], "old value"):
                kwargs = self.arguments(model, seed=stale, steps=stale, output_format=stale)
                with self.subTest(model=model, stale=stale):
                    self.assertIs(flux.validate(kwargs), True)
                    expected = self.expected(model, images=images) if images else self.expected(model)
                    self.assertEqual(flux.payload(kwargs, images), expected)

    def test_klein_ignores_even_invalid_stale_grounding(self):
        for model in flux.MODELS[2:]:
            images = IMAGES[:1] if model.endswith("-i2i") else []
            for stale in (False, 1, 1.5, None, [], "old value"):
                with self.subTest(model=model, stale=stale):
                    kwargs = self.arguments(model, grounding=stale)
                    self.assertIs(flux.validate(kwargs), True)
                    self.assertNotIn("grounding", flux.payload(kwargs, images))

    def test_linked_prompt_preflight_defers_required_values_but_runtime_rejects(self):
        self.assertIs(flux.validate({}), True)
        self.assertIsInstance(flux.validate({}, strict=True), str)
        for model in flux.MODELS:
            images = IMAGES[:1] if model.endswith("-i2i") else []
            for changes in ({}, {"prompt": None}, {"prompt": ""}, {"prompt": " \n\t"}):
                kwargs = {"model": model, **changes}
                if images:
                    kwargs["image10"] = ConnectedImage()
                with self.subTest(model=model, changes=changes):
                    self.assertIs(flux.validate(kwargs), True)
                    self.assertIsInstance(flux.validate(kwargs, strict=True), str)
                    with self.assertRaises(client.SeedanceAPIError):
                        flux.payload(kwargs, images)

    def test_strict_i2i_needs_an_original_socket_not_a_kwargs_images_field(self):
        for model in (flux.MODELS[1], flux.MODELS[3]):
            for changes in ({}, {"image1": None}, {"images": IMAGES[:1]}):
                kwargs = self.arguments(model, **changes)
                with self.subTest(model=model, changes=changes):
                    self.assertIs(flux.validate(kwargs), True)
                    self.assertIsInstance(flux.validate(kwargs, strict=True), str)
            for index in range(1, 11):
                kwargs = self.arguments(model, **{f"image{index}": ConnectedImage()})
                with self.subTest(model=model, index=index):
                    self.assertIs(flux.validate(kwargs, strict=True), True)

    def test_t2i_rejects_every_raw_connected_socket_even_with_no_uploaded_images(self):
        for model in (flux.MODELS[0], flux.MODELS[2]):
            for index in range(1, 11):
                kwargs = self.arguments(model, **{f"image{index}": ConnectedImage()})
                with self.subTest(model=model, index=index):
                    self.assertIsInstance(flux.validate(kwargs), str)
                    self.assertIsInstance(flux.validate(kwargs, strict=True), str)
                    with self.assertRaises(client.SeedanceAPIError):
                        flux.payload(kwargs, [])
            kwargs = self.arguments(model, **{f"image{i}": None for i in range(1, 11)})
            self.assertIs(flux.validate(kwargs, strict=True), True)
            self.assertNotIn("images", flux.payload(kwargs, []))

    def test_t2i_rejects_uploaded_images_instead_of_dropping_them(self):
        for model in (flux.MODELS[0], flux.MODELS[2]):
            for images in (IMAGES[:1], IMAGES, IMAGES + IMAGES[:1]):
                with self.subTest(model=model, count=len(images)):
                    with self.assertRaises(client.SeedanceAPIError):
                        flux.payload(self.arguments(model), images)

    def test_i2i_direct_uploaded_arrays_accept_one_through_ten_in_order(self):
        for model in (flux.MODELS[1], flux.MODELS[3]):
            for count in range(1, 11):
                with self.subTest(model=model, count=count):
                    images = IMAGES[:count]
                    result = flux.payload(self.arguments(model), images)
                    self.assertEqual(result["images"], images)
                    self.assertIsNot(result["images"], images)
            for images in ([], IMAGES + IMAGES[:1]):
                with self.subTest(model=model, count=len(images)):
                    with self.assertRaises(client.SeedanceAPIError):
                        flux.payload(self.arguments(model), images)

    def test_multiple_connections_with_gaps_and_all_ten_are_preserved(self):
        for model in (flux.MODELS[1], flux.MODELS[3]):
            for indexes in ((1, 4, 10), tuple(range(1, 11))):
                kwargs = self.arguments(model, **{f"image{i}": ConnectedImage() for i in indexes})
                images = [IMAGES[i - 1] for i in indexes]
                with self.subTest(model=model, indexes=indexes):
                    self.assertIs(flux.validate(kwargs, strict=True), True)
                    self.assertEqual(flux.payload(kwargs, images)["images"], images)

    def test_invalid_uploaded_arrays_raise_api_errors(self):
        for model in flux.MODELS:
            for images in (None, "reference", {}, [None], [True], [1], [""], [" \n"]):
                with self.subTest(model=model, images=images):
                    with self.assertRaises(client.SeedanceAPIError):
                        flux.payload(self.arguments(model), images)

    def test_invalid_arguments_return_strings_and_raise_api_errors(self):
        for kwargs in (None, [], "prompt", 1):
            with self.subTest(kwargs=kwargs):
                self.assertIsInstance(flux.validate(kwargs), str)
                with self.assertRaises(client.SeedanceAPIError):
                    flux.payload(kwargs, [])

    def test_helpers_do_not_mutate_inputs_or_perform_network_io(self):
        kwargs = self.arguments(flux.MODELS[3], steps=8, image1=ConnectedImage())
        original = kwargs.copy()
        images = IMAGES[:2]
        with patch.object(client.requests.sessions.Session, "request",
                          side_effect=AssertionError("Network access is not allowed")):
            self.assertIs(flux.validate(kwargs, strict=True), True)
            result = flux.payload(kwargs, images)
        result["images"].append("https://example.test/extra.png")
        self.assertEqual(kwargs, original)
        self.assertEqual(images, IMAGES[:2])


if __name__ == "__main__":
    unittest.main()
