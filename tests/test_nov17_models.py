from pathlib import Path
import asyncio
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import concurrent_nodes, nodes
from ComfyUI_Seedance.core import doubao_tts, h3_comfy, llm, seedance25_flash
from ComfyUI_Seedance.core.client import SeedanceAPIError

IMAGE = torch.zeros(1, 8, 8, 3)
AUDIO = {"waveform": torch.zeros(1, 1, 16000), "sample_rate": 8000}
CONFIG = {"base_url": "https://example.test", "api_key": "sk-test"}
CLASSES = {"charswap": nodes.MinimaxH3ComfyUICharSwap, "wuxi": nodes.MinimaxH3ComfyUIWuxi,
           "wf": nodes.MinimaxH3ComfyUIWF, "selflift": nodes.MinimaxH3ComfyUISelfLift}
KEYS = {"charswap": "Minimax_H3_ComfyUI_CharSwap", "wuxi": "Minimax_H3_ComfyUI_Wuxi",
        "wf": "Minimax_H3_ComfyUI_Max_10020", "selflift": "Minimax_H3_ComfyUI_Max_10021"}


def h3_kwargs(kind):
    data = {"prompt": "<Picture 1> waves gently.", "image1": IMAGE, "resolution": "480p",
            "ratio": "auto" if kind == "charswap" else "16:9", "seconds": "5"}
    if kind == "charswap":
        data["video_urls"] = "https://example.com/source.mp4"
    return data


class H3ComfyContractTests(unittest.TestCase):
    def tearDown(self):
        concurrent_nodes.shutdown_concurrent_pools(wait=True)

    def test_four_independent_registrations_native_seeds_and_safe_wrappers(self):
        for kind, cls in CLASSES.items():
            with self.subTest(kind=kind):
                self.assertIs(nodes.NODE_CLASS_MAPPINGS[KEYS[kind]], cls)
                schema, spec = cls.INPUT_TYPES(), h3_comfy.PROFILES[kind]
                self.assertEqual(len([key for key in schema["optional"] if key.startswith("image")]), spec["images"])
                self.assertEqual(len([key for key in schema["optional"] if key.startswith("audio")]), spec["audios"])
                self.assertEqual(len([key for key in schema["optional"] if key.startswith("video") and key != "video_urls"]), spec["videos"])
                seed = schema["required"].get("seed") or schema["optional"]["seed"]
                self.assertTrue(seed[1]["control_after_generate"])
                self.assertEqual(cls.SEEDANCE_CACHE_ONLY_SEED, not spec["seed"])
                self.assertFalse(schema["optional"]["skip_error"][1]["default"])
                wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS["SeedanceConcurrent_" + KEYS[kind] + "_Submit"]
                self.assertFalse(hasattr(wrapper, "VALIDATE_INPUTS"))
                self.assertEqual(wrapper.INPUT_TYPES(), schema)

    def test_queue_validation_defers_external_prompt_and_runtime_requires_text(self):
        for kind, cls in CLASSES.items():
            self.assertTrue(cls.VALIDATE_INPUTS())
            self.assertIsNot(cls.VALIDATE_INPUTS(prompt=42), True)
            with self.assertRaises(SeedanceAPIError):
                h3_comfy.validate(kind, {}, strict=True)

    def test_each_profile_uses_its_own_resolutions_duration_and_image_cap(self):
        for kind, spec in h3_comfy.PROFILES.items():
            for resolution in spec["resolutions"]:
                self.assertTrue(h3_comfy.validate(kind, {"resolution": resolution}))
            for seconds in (str(spec["min_seconds"]), "15"):
                self.assertTrue(h3_comfy.validate(kind, {"seconds": seconds}))
            for data in ({"seconds": str(spec["min_seconds"] - 1)}, {"seconds": "16"}, {"seconds": 5}, {"resolution": "4k"}, {f"image{spec['images'] + 1}": IMAGE}):
                with self.subTest(kind=kind, data=list(data)), self.assertRaises(SeedanceAPIError):
                    h3_comfy.validate(kind, data)

    def test_charswap_requires_image_and_exactly_one_video(self):
        for changes in ({"image1": None}, {"video_urls": ""}, {"video_urls": "https://example.com/1.mp4\nhttps://example.com/2.mp4"}, {"audio1": AUDIO}):
            with self.assertRaises(SeedanceAPIError):
                h3_comfy.validate("charswap", {**h3_kwargs("charswap"), **changes}, strict=True)
        self.assertTrue(h3_comfy.validate("charswap", h3_kwargs("charswap"), strict=True))

    def test_audio_and_video_image_dependencies_differ_between_profiles(self):
        with self.assertRaisesRegex(SeedanceAPIError, "at least one image"):
            h3_comfy.validate("selflift", {"prompt": "hello", "audio1": AUDIO}, strict=True)
        self.assertTrue(h3_comfy.validate("wf", {"prompt": "hello", "audio1": AUDIO}, strict=True))
        with self.assertRaisesRegex(SeedanceAPIError, "at least one image"):
            h3_comfy.validate("wuxi", {"prompt": "hello", "video_urls": "https://example.com/v.mp4"}, strict=True)
        self.assertTrue(h3_comfy.validate("wuxi", {"prompt": "hello", "audio1": AUDIO}, strict=True))

    def test_charswap_frame_mode_exact_values_and_seconds_omission(self):
        for frames in h3_comfy.FRAMES:
            data = {**h3_kwargs("charswap"), "duration_mode": "frames", "frames": frames, "seconds": "stale"}
            body = h3_comfy.payload("charswap", data, ["image"], [], ["video"])
            self.assertEqual(body["metadata"]["frames"], frames)
            self.assertNotIn("seconds", body)
        for frames in (21, 23, 363, 22.0, True, "22"):
            with self.assertRaises(SeedanceAPIError):
                h3_comfy.validate("charswap", {"duration_mode": "frames", "frames": frames})

    def test_charswap_resolution_specific_ratios(self):
        self.assertIn("21:9", h3_comfy.ratios("charswap", "768p"))
        for resolution in ("480p", "1088p", "auto"):
            with self.assertRaises(SeedanceAPIError):
                h3_comfy.validate("charswap", {"resolution": resolution, "ratio": "21:9"})

    def test_payload_exact_reference_field_names_no_invented_audio_flag(self):
        for kind in CLASSES:
            data = h3_kwargs(kind)
            audios = [] if kind == "charswap" else ["https://example.com/a.wav"]
            videos = ["https://example.com/v.mp4"] if kind in ("charswap", "wuxi") else []
            body = h3_comfy.payload(kind, {**data, "seed": 0}, ["https://example.com/i.png"], audios, videos)
            self.assertEqual(body["model"], h3_comfy.PROFILES[kind]["model"])
            self.assertEqual(body["images"], ["https://example.com/i.png"])
            self.assertNotIn("generate_audio", body["metadata"])
            self.assertNotIn("video_urls", body["metadata"])
            if videos:
                self.assertEqual(body["metadata"]["video_url"], videos)
            if audios:
                self.assertEqual(body["metadata"]["audio_urls"], audios)
            self.assertEqual("seed" in body["metadata"], kind in ("charswap", "wuxi"))

    def test_reference_tag_counts_and_workflow_specific_audio_tags(self):
        for kind in CLASSES:
            with self.assertRaises(SeedanceAPIError):
                h3_comfy.validate(kind, {**h3_kwargs(kind), "prompt": "<Picture 2> waves"}, strict=True)
        for kind in ("charswap", "wuxi"):
            with self.assertRaises(SeedanceAPIError):
                h3_comfy.validate(kind, {**h3_kwargs(kind), "prompt": "<Audio 1> hello"}, strict=True)
        for kind in ("wf", "selflift"):
            self.assertTrue(h3_comfy.validate(kind, {**h3_kwargs(kind), "prompt": "<Picture 1> sings <Audio 1>", "audio1": AUDIO}, strict=True))

    def test_all_material_validation_precedes_any_upload(self):
        cases = [("wf", {"image6": torch.zeros(2, 8, 8, 3)}), ("wuxi", {"image9": torch.full((1, 8, 8, 3), float("nan"))}),
                 ("selflift", {"audio3": {"waveform": torch.zeros(2, 1, 4), "sample_rate": 8000}})]
        for kind, changes in cases:
            with patch.object(nodes, "upload_media") as upload, self.assertRaises(SeedanceAPIError):
                CLASSES[kind]().execute(**h3_kwargs(kind), **changes)
            upload.assert_not_called()

    def test_per_profile_image_size_and_combined_limits(self):
        for kind in CLASSES:
            with patch.object(h3_comfy, "MIB", 1), self.assertRaises(SeedanceAPIError):
                h3_comfy.encode_media(kind, h3_kwargs(kind))

    def test_mp4_container_and_total_video_size_before_upload(self):
        for video in ((b"not-mp4", "mp4"), (b"1234ftyp1234", "mov")):
            with patch.object(h3_comfy, "video_to_bytes", return_value=video), patch.object(nodes, "upload_media") as upload:
                with self.assertRaises(SeedanceAPIError):
                    nodes.MinimaxH3ComfyUIWuxi().execute(**h3_kwargs("wuxi"), video1=object())
                upload.assert_not_called()

    def test_shared_execute_download_and_cache_seed_contract(self):
        for kind, cls in CLASSES.items():
            with patch.object(nodes, "submit_legacy_video_task", return_value="example-task") as submit, \
                    patch.object(nodes, "upload_media", return_value="https://example.com/reference.png"), \
                    patch.object(nodes, "poll_legacy_video_task", return_value={}), \
                    patch.object(nodes, "extract_legacy_video_url", return_value="https://example.com/out.mp4"), \
                    patch.object(nodes, "download_video", return_value="video"):
                result = cls().execute(**h3_kwargs(kind), api_config=CONFIG, seed=7)
                self.assertEqual(result["result"][:3], ("video", "https://example.com/out.mp4", "example-task"))
                self.assertEqual("seed" in submit.call_args.args[0]["metadata"], kind in ("charswap", "wuxi"))

    def test_skip_error_default_false_and_placeholder_outputs(self):
        for cls in CLASSES.values():
            with patch.object(cls, "_execute_inner", side_effect=SeedanceAPIError("test failure")), patch.object(nodes, "make_error_video", return_value="placeholder"):
                with self.assertRaises(SeedanceAPIError):
                    cls().execute(prompt="hello")
                self.assertEqual(cls().execute(prompt="hello", skip_error=True)["result"][0], "placeholder")


class Flash25Tests(unittest.TestCase):
    def test_six_models_append_after_original_six_in_existing_node(self):
        self.assertEqual(nodes.SEEDANCE25_MODELS[6:], seedance25_flash.MODELS)
        self.assertEqual(len(nodes.SEEDANCE25_MODELS), 12)
        self.assertEqual(nodes.Seedance25Video.RETURN_NAMES, ("video", "video_url", "task_id", "response"))

    def test_resolution_draft_and_fixed_i2v_ratio_enforced(self):
        for model in seedance25_flash.MODELS:
            for change in ({"resolution": "1080p"}, {"resolution": "native1080p"}, {"draft": True}):
                self.assertIsNot(nodes.Seedance25Video.VALIDATE_INPUTS(model=model, **change), True)
            if model.endswith("i2v"):
                self.assertIsNot(nodes.Seedance25Video.VALIDATE_INPUTS(model=model, ratio="16:9"), True)

    def test_flash_caps_reject_hidden_stale_connections_before_upload(self):
        for family, index in (("image", 11), ("video", 6), ("audio", 6)):
            with patch.object(nodes, "upload_media") as upload, self.assertRaises(SeedanceAPIError):
                nodes.Seedance25Video().execute(model=seedance25_flash.MODELS[2], prompt="hello", resolution="480p", seconds="4", ratio="adaptive", api_config=CONFIG,
                                               **{family + str(index): object()})
            upload.assert_not_called()

    def test_flash_t2v_does_not_silently_ignore_reference_inputs(self):
        with self.assertRaises(SeedanceAPIError):
            seedance25_flash.validate({"model": seedance25_flash.MODELS[0], "image1": IMAGE})

    def test_payloads_for_all_six_exact_counts_and_duration_types(self):
        for model in seedance25_flash.MODELS:
            media = {"images": ["https://example.com/1.png", "https://example.com/2.png"]} if model.endswith("i2v") else {"content": [{"type": "image_url", "image_url": {"url": "https://example.com/i.png"}}]} if model.endswith("multi") else {}
            body = nodes.Seedance25Video().build_payload({"model": model, "prompt": "animate gently", "seconds": "4", "resolution": "480p", "ratio": "adaptive"}, media)
            self.assertEqual(body["model"], model)
            self.assertEqual(body["seconds"], "4")
            self.assertNotIn("draft", body["metadata"])
            self.assertNotIn("omni_reference_task_type", body["metadata"])

    def test_auto_duration_and_edit_requirements(self):
        data = {"model": seedance25_flash.MODELS[2], "prompt": "edit gently", "seconds": "-1", "resolution": "480p", "ratio": "adaptive", "omni_reference_task_type": "edit"}
        media = {"content": [{"type": "video_url", "video_url": {"url": "https://example.com/v.mp4"}}]}
        body = nodes.Seedance25Video().build_payload(data, media)
        self.assertNotIn("seconds", body)
        self.assertEqual(body["metadata"]["duration"], -1)
        self.assertEqual(body["metadata"]["omni_reference_task_type"], "edit")
        for change in ({"seconds": "4"}, {"ratio": "16:9"}):
            with self.assertRaises(SeedanceAPIError):
                nodes.Seedance25Video().build_payload({**data, **change}, media)

    def test_reference_duration_limits_and_total_before_upload(self):
        base = {"model": seedance25_flash.MODELS[2], "audio1": AUDIO}
        self.assertTrue(seedance25_flash.encode_media(base))
        for seconds in (1, 31):
            bad = {"waveform": torch.zeros(1, 1, 8000 * seconds), "sample_rate": 8000}
            with self.assertRaises(SeedanceAPIError):
                seedance25_flash.encode_media({**base, "audio1": bad})
        audio20 = {"waveform": torch.zeros(1, 1, 160000), "sample_rate": 8000}
        with self.assertRaises(SeedanceAPIError):
            seedance25_flash.encode_media({**base, "audio1": audio20, "audio2": audio20})


class DoubaoTTS20Tests(unittest.TestCase):
    def test_catalog_is_complete_unique_and_only_published_20_ids(self):
        self.assertEqual(len(doubao_tts.VOICES), 473)
        self.assertTrue(all("uranus" in key for key in doubao_tts.VOICES))
        self.assertEqual(doubao_tts.VOICES[doubao_tts.VIVI]["name"], "Vivi")
        self.assertIn("zh_male_lubanqihao_uranus_bigtts", doubao_tts.VOICES)

    def test_existing_clone_node_is_not_repurposed(self):
        self.assertEqual(nodes.DOUBAO_VOICE_MODELS, ["doubao-voice-clone", "doubao-seed-icl-2.0"])
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Doubao_Seed_TTS_2_0"], nodes.DoubaoSeedTTS20)
        self.assertNotIn("Doubao_Seed_TTS_2_0", concurrent_nodes.PURE_IMAGE_NODE_KEYS + concurrent_nodes.PURE_VIDEO_NODE_KEYS)
        self.assertTrue(nodes.DoubaoSeedTTS20.SEEDANCE_CACHE_ONLY_SEED)

    def test_exact_payload_and_no_cache_seed_or_ui_fields(self):
        body = doubao_tts.payload({"prompt": " hello ", "seed": 55, "advanced_mode": True, "context_texts": "Gentle"})
        self.assertEqual(body, {"model": "doubao-seed-tts-2.0", "prompt": " hello ", "metadata": {"speaker": doubao_tts.VIVI, "format": "mp3", "sample_rate": "24000", "context_texts": "Gentle"}})

    def test_all_library_voices_resolve_to_their_actual_ids(self):
        for voice in doubao_tts.VOICES:
            self.assertEqual(doubao_tts.payload({"prompt": "hello", "speaker": voice})["metadata"]["speaker"], voice)

    def test_custom_voice_model_omits_instructions_and_library_model_rejected(self):
        data = {"prompt": "hello", "speaker": "exampleCustomVoice", "voice_model": "seed-tts-2.0-standard", "context_texts": "Gentle"}
        body = doubao_tts.payload(data)
        self.assertNotIn("context_texts", body["metadata"])
        with self.assertRaises(SeedanceAPIError):
            doubao_tts.payload({**data, "speaker": doubao_tts.VIVI})

    def test_dialect_vivi_only_and_language_constraints(self):
        self.assertEqual(doubao_tts.payload({"prompt": "hello", "explicit_dialect": "sichuan"})["metadata"]["explicit_dialect"], "sichuan")
        for change in ({"speaker": "zh_male_m191_uranus_bigtts"}, {"explicit_language": "en"}):
            with self.assertRaises(SeedanceAPIError):
                doubao_tts.payload({"prompt": "hello", "explicit_dialect": "sichuan", **change})

    def test_boolean_markdown_semantics_and_latex_are_not_inverted(self):
        data = {"prompt": "hello", "disable_markdown_filter": "enabled", "enable_latex_tn": "enabled", "latex_parser": "v2"}
        self.assertTrue(doubao_tts.payload(data)["metadata"]["disable_markdown_filter"])
        with self.assertRaises(SeedanceAPIError):
            doubao_tts.payload({**data, "disable_markdown_filter": "disabled"})

    def test_numeric_ranges_low_bitrate_and_text_limits(self):
        for change in ({"prompt": ""}, {"prompt": "a"*10001}, {"context_texts": "x"*501}, {"speech_rate": 101}, {"pitch": float("nan")}, {"sample_rate": "12345"}, {"bit_rate": 16000}, {"enable_subtitle": True}):
            with self.subTest(change=list(change)), self.assertRaises(SeedanceAPIError):
                doubao_tts.payload({"prompt": "hello", **change})
        self.assertEqual(doubao_tts.payload({"prompt": "hello", "bit_rate": 16000, "disable_default_bit_rate": "enabled"})["metadata"]["bit_rate"], 16000)

    def test_ssml_library_rejected_and_custom_filtering_conflict(self):
        with self.assertRaises(SeedanceAPIError):
            doubao_tts.payload({"prompt": "hello", "ssml": "<speak>hello</speak>"})
        custom = {"prompt": "hello", "speaker": "exampleCustomVoice", "ssml": "<speak>hello</speak>"}
        self.assertFalse(doubao_tts.payload(custom)["metadata"]["disable_markdown_filter"])

    def test_execute_uses_shared_audio_download_with_requested_format(self):
        with patch.object(nodes, "submit_audio_task", return_value="example-task") as submit, patch.object(nodes, "poll_audio_task", return_value={}), \
                patch.object(nodes, "extract_audio_url", return_value="https://example.com/a.pcm"), patch.object(nodes, "download_audio", return_value=(AUDIO, "audio.pcm")) as download:
            result = nodes.DoubaoSeedTTS20().execute(prompt="hello", api_config=CONFIG, output_format="pcm", sample_rate="16000", seed=4)
            self.assertEqual(result["result"][0], AUDIO)
            self.assertEqual(download.call_args.kwargs["sample_rate"], 16000)
            self.assertNotIn("seed", submit.call_args.args[0]["metadata"])

    def test_default_error_raises_skip_error_returns_silence(self):
        with patch.object(nodes, "submit_audio_task", side_effect=SeedanceAPIError("test error")):
            with self.assertRaises(SeedanceAPIError):
                nodes.DoubaoSeedTTS20().execute(prompt="hello", api_config=CONFIG)
            result = nodes.DoubaoSeedTTS20().execute(prompt="hello", api_config=CONFIG, skip_error=True)["result"]
            self.assertEqual(len(result), 6)
            self.assertTrue(torch.isfinite(result[0]["waveform"]).all())

    def test_new_llm_model_positive_catalog_and_payload(self):
        self.assertIn("zhenzhen-fb-5.2", llm.MODELS)
        self.assertEqual(len(llm.MODELS), 29)

    def test_voice_catalog_route_is_local_idempotent_and_credential_free(self):
        from ComfyUI_Seedance.core import tts_routes
        captured = {}
        server = SimpleNamespace(routes=SimpleNamespace(get=lambda path: lambda function: captured.setdefault(path, function)))
        with patch.dict(sys.modules, {"server": SimpleNamespace(PromptServer=SimpleNamespace(instance=server))}):
            tts_routes.register()
            tts_routes.register()
        self.assertEqual(len(captured), 1)
        result = asyncio.run(captured["/seedance/doubao/voices"](None))
        self.assertEqual(result.status, 200)
        self.assertEqual(len(json.loads(result.body)["voices"]), 473)
        self.assertNotIn("api_key", result.text)

    def test_voice_route_registration_without_running_server_is_safe(self):
        from ComfyUI_Seedance.core import tts_routes
        with patch.dict(sys.modules, {"server": SimpleNamespace(PromptServer=SimpleNamespace(instance=None))}):
            self.assertIsNone(tts_routes.register())
