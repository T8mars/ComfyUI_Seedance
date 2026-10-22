import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import concurrent_nodes, nodes
from ComfyUI_Seedance.core.client import SeedanceAPIError

IMAGE = torch.zeros((1, 16, 16, 3))
AUDIO = {"waveform": torch.zeros((1, 1, 24000)), "sample_rate": 24000}
CONFIG = {"base_url": "https://example.test", "api_key": "sk-test"}


def defaults(node_class, **changes):
    return {**{name: spec[1]["default"] for name, spec in node_class.INPUT_TYPES()["required"].items()}, **changes}


class NBLowpriceTests(unittest.TestCase):
    def args(self, **changes):
        return defaults(nodes.ZhenzhenImageNBLowprice, **{"prompt": "A blue teapot", **changes})

    def tearDown(self):
        concurrent_nodes.shutdown_concurrent_pools(wait=True)

    def test_independent_registration_controls_and_concurrent_contract(self):
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Zhenzhen_Image_NB_Lowprice"], nodes.ZhenzhenImageNBLowprice)
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Zhenzhen_Image_NB_2_1"], nodes.ZhenzhenImageNB21)
        inputs = nodes.ZhenzhenImageNBLowprice.INPUT_TYPES()
        self.assertEqual(list(inputs["optional"]), [f"image{i}" for i in range(1, 15)] + ["api_config", "skip_error", "seed"])
        self.assertTrue(inputs["optional"]["seed"][1]["control_after_generate"])
        self.assertTrue(nodes.ZhenzhenImageNBLowprice.SEEDANCE_CACHE_ONLY_SEED)
        wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS["SeedanceConcurrent_Zhenzhen_Image_NB_Lowprice_Submit"]
        self.assertEqual(wrapper.INPUT_TYPES(), inputs)
        self.assertFalse(hasattr(wrapper, "VALIDATE_INPUTS"))
        self.assertFalse(hasattr(wrapper, "IS_CHANGED"))

    def test_both_models_whitelist_payload_and_14_ordered_references(self):
        for model in nodes.ZHENZHEN_IMAGE_NB_LOWPRICE_MODELS:
            args = self.args(model=model, seed=33, output_format="png", n=8)
            expected = {"model": model, "prompt": "A blue teapot", "n": 1, "size": "1:1", "metadata": {"resolution": "1k"}}
            node = nodes.ZhenzhenImageNBLowprice()
            self.assertEqual(node.build_payload(args, []), expected)
            urls = [f"https://reference.test/{i}.png" for i in range(14)]
            self.assertEqual(node.build_payload(args, urls), {**expected, "images": urls})
            with self.assertRaises(SeedanceAPIError):
                node.build_payload(args, urls + ["extra"])

    def test_prompt_bounds_and_linked_preflight(self):
        self.assertIs(nodes.ZhenzhenImageNBLowprice.VALIDATE_INPUTS(prompt=None), True)
        for length in (1, 5000):
            self.assertIs(nodes.ZhenzhenImageNBLowprice.VALIDATE_INPUTS(**self.args(prompt="x" * length), strict=True), True)
        for length in (0, 5001):
            self.assertIsNot(nodes.ZhenzhenImageNBLowprice.VALIDATE_INPUTS(**self.args(prompt="x" * length), strict=True), True)

    def test_model_specific_ratios_and_resolutions(self):
        for ratio in ("1:4", "4:1", "1:8", "8:1"):
            self.assertIsNot(nodes.ZhenzhenImageNBLowprice.VALIDATE_INPUTS(**self.args(size=ratio)), True)
            self.assertIs(nodes.ZhenzhenImageNBLowprice.VALIDATE_INPUTS(**self.args(model=nodes.ZHENZHEN_IMAGE_NB_LOWPRICE_MODELS[1], size=ratio)), True)
        for resolution in ("1k", "2k", "4k"):
            self.assertIs(nodes.ZhenzhenImageNBLowprice.VALIDATE_INPUTS(**self.args(resolution=resolution)), True)
        self.assertIsNot(nodes.ZhenzhenImageNBLowprice.VALIDATE_INPUTS(**self.args(resolution="0.5k")), True)

    def test_actual_execute_uploads_all_14_slots_and_downloads(self):
        urls = [f"https://reference.test/{i}.png" for i in range(14)]
        with patch.object(nodes, "get_config", return_value=CONFIG), \
             patch.object(nodes, "upload_media", side_effect=urls) as upload, \
             patch.object(nodes, "submit_image_task", return_value="test-task") as submit, \
             patch.object(nodes, "poll_image_task", return_value={"data": {"result_url": "https://result.test/image.png"}}), \
             patch.object(nodes, "download_image", return_value=IMAGE) as download:
            result = nodes.ZhenzhenImageNBLowprice().execute(**self.args(), **{f"image{i}": IMAGE for i in range(1, 15)}, seed=3)
        self.assertEqual(upload.call_count, 14)
        self.assertEqual(submit.call_args.args[0]["images"], urls)
        self.assertEqual(upload.call_args_list[-1].args[1], "nb_lowprice_reference_14.png")
        self.assertIs(result["result"][0], IMAGE)
        download.assert_called_once()

    def test_invalid_input_is_rejected_before_upload(self):
        with patch.object(nodes, "upload_media") as upload:
            for args in (self.args(prompt=""), self.args(image14=IMAGE.repeat(2, 1, 1, 1))):
                with self.assertRaises(SeedanceAPIError):
                    nodes.ZhenzhenImageNBLowprice().execute(**args)
        upload.assert_not_called()

    def test_concurrent_skip_error_does_not_cancel_sibling(self):
        wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS["SeedanceConcurrent_Zhenzhen_Image_NB_Lowprice_Submit"]
        with patch.object(nodes.ZhenzhenImageNBLowprice, "_execute_inner", return_value={"result": (IMAGE, "", "", "{}")}):
            good = wrapper().submit(**self.args())[0]
            bad = wrapper().submit(**self.args(prompt=""), skip_error=True)[0]
            result = concurrent_nodes.SeedanceConcurrentImageAwait().wait_all(future_1=good, future_2=bad)
        self.assertIs(result[0], IMAGE)
        self.assertEqual(result[1].shape, (1, 512, 512, 3))
        self.assertFalse(good.cancel_event.is_set())


class DoubaoVoiceTests(unittest.TestCase):
    def clone(self, **changes):
        return defaults(nodes.DoubaoVoiceCloneICL, **{"prompt": "Good morning.", "reference_audio": AUDIO, **changes})

    def synth(self, **changes):
        return defaults(nodes.DoubaoVoiceCloneICL, **{"model": nodes.DOUBAO_ICL_MODEL, "prompt": "Good morning.", "speaker": "exampleVoice", **changes})

    def test_two_modes_six_outputs_cache_and_no_audio_wrapper(self):
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Doubao_Voice_Clone_ICL"], nodes.DoubaoVoiceCloneICL)
        inputs = nodes.DoubaoVoiceCloneICL.INPUT_TYPES()
        self.assertEqual(inputs["required"]["model"][0], ["doubao-voice-clone", "doubao-seed-icl-2.0"])
        self.assertEqual(nodes.DoubaoVoiceCloneICL.RETURN_NAMES[3], "speaker")
        self.assertTrue(inputs["optional"]["seed"][1]["control_after_generate"])
        self.assertNotIn("SeedanceConcurrent_Doubao_Voice_Clone_ICL_Submit", concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS)

    def test_clone_payload_ids_and_fields_are_not_synthesis_fields(self):
        args = self.clone(custom_speaker_id="exampleVoice", training_speaker_id="provider-example",
                          reference_text="Reference speech", language="1", enable_audio_denoise="enabled", seed=55)
        payload = nodes.DoubaoVoiceCloneICL().build_payload(args, "https://reference.test/voice.wav")
        self.assertEqual(payload, {"model": nodes.DOUBAO_VOICE_CLONE_MODEL, "prompt": "Good morning.", "metadata": {
            "audio_url": "https://reference.test/voice.wav", "custom_speaker_id": "exampleVoice", "speaker_id": "provider-example",
            "reference_text": "Reference speech", "language": "1", "enable_audio_denoise": True}})

    def test_synthesis_payload_types_whitelist_and_no_clone_leak(self):
        args = self.synth(custom_speaker_id="ignoredValue", reference_audio=AUDIO, audio_url="bad-hidden-url",
                          speech_rate=1.5, pitch=-1.5, enable_subtitle="enabled", bit_rate=16000,
                          explicit_language="en", max_length_to_filter_parenthesis="100", seed=33)
        meta = nodes.DoubaoVoiceCloneICL().build_payload(args)["metadata"]
        self.assertEqual(meta["sample_rate"], "24000")
        self.assertEqual(meta["speech_rate"], 1.5)
        self.assertIs(meta["enable_subtitle"], True)
        self.assertEqual(meta["max_length_to_filter_parenthesis"], 100)
        self.assertEqual(meta["bit_rate"], 16000)
        for field in ("audio_url", "custom_speaker_id", "speaker_id", "seed", "advanced_mode", "context_texts"):
            self.assertNotIn(field, meta)

    def test_api_default_booleans_are_omitted_and_context_is_conditional(self):
        node = nodes.DoubaoVoiceCloneICL()
        meta = node.build_payload(self.synth())["metadata"]
        for field in nodes.DOUBAO_ICL_BOOLEAN_FIELDS:
            self.assertNotIn(field, meta)
        meta = node.build_payload(self.synth(voice_model="api_default", context_texts="Calm tone"))["metadata"]
        self.assertEqual(meta["context_texts"], "Calm tone")
        self.assertNotIn("voice_model", meta)
        meta = node.build_payload(self.synth(context_texts="x" * 501))["metadata"]
        self.assertNotIn("context_texts", meta)

    def test_prompt_bounds_and_upstream_linked_inputs_are_deferred(self):
        self.assertIs(nodes.DoubaoVoiceCloneICL.VALIDATE_INPUTS(model=nodes.DOUBAO_ICL_MODEL, prompt=None), True)
        for args, lengths in ((self.clone, (4, 300)), (self.synth, (1, 10000))):
            for length in lengths:
                self.assertIs(nodes.DoubaoVoiceCloneICL.VALIDATE_INPUTS(**args(prompt="x" * length), strict=True), True)
            for length in (lengths[0] - 1, lengths[1] + 1):
                self.assertIsNot(nodes.DoubaoVoiceCloneICL.VALIDATE_INPUTS(**args(prompt="x" * length), strict=True), True)

    def test_reference_exclusivity_url_id_and_language_validation(self):
        invalid = [self.clone(reference_audio=None), self.clone(audio_url="https://reference.test/a.wav"),
                   self.clone(reference_audio=None, audio_url="file:///voice.wav"), self.clone(custom_speaker_id="short"),
                   self.clone(custom_speaker_id="中exampleVoice"), self.clone(language="18"), self.clone(reference_text="x" * 2001),
                   self.clone(reference_audio={**AUDIO, "waveform": AUDIO["waveform"].repeat(2, 1, 1)})]
        for args in invalid:
            self.assertIsNot(nodes.DoubaoVoiceCloneICL.VALIDATE_INPUTS(**args, strict=True), True)
        self.assertIs(nodes.DoubaoVoiceCloneICL.VALIDATE_INPUTS(**self.clone(reference_audio=None, audio_url="https://reference.test/a.wav"), strict=True), True)

    def test_numeric_and_enum_boundaries(self):
        for change in ({"speaker": ""}, {"bit_rate": 15999}, {"speech_rate": 101}, {"pitch": -13},
                       {"sample_rate": "16001"}, {"enable_subtitle": True}, {"voice_model": "invented"},
                       {"context_texts": "x" * 501, "voice_model": "api_default"}, {"section_id": "x" * 129}):
            self.assertIsNot(nodes.DoubaoVoiceCloneICL.VALIDATE_INPUTS(**self.synth(**change), strict=True), True)

    def test_latex_requires_filtering_without_guessing_default(self):
        meta = nodes.DoubaoVoiceCloneICL().build_payload(self.synth(latex_parser="v2"))["metadata"]
        self.assertIs(meta["disable_markdown_filter"], False)
        self.assertIsNot(nodes.DoubaoVoiceCloneICL.VALIDATE_INPUTS(**self.synth(latex_parser="v2", disable_markdown_filter="enabled"), strict=True), True)

    def test_clone_upload_download_and_authoritative_speaker(self):
        final = {"data": {"status": "SUCCESS", "result_text": "returnedVoice", "result_url": "https://result.test/preview.mp3"}}
        with patch.object(nodes, "get_config", return_value=CONFIG), \
             patch.object(nodes, "audio_to_wav_bytes", return_value=b"wav"), \
             patch.object(nodes, "upload_media", return_value="https://reference.test/a.wav") as upload, \
             patch.object(nodes, "submit_audio_task", return_value="test-task") as submit, \
             patch.object(nodes, "poll_audio_task", return_value=final), \
             patch.object(nodes, "download_audio", return_value=(AUDIO, "preview.mp3")) as download:
            result = nodes.DoubaoVoiceCloneICL().execute(**self.clone(custom_speaker_id="requestedVoice"), seed=42)
        self.assertEqual(result["result"][3], "returnedVoice")
        self.assertEqual(len(result["result"]), 6)
        self.assertEqual(submit.call_args.args[0]["metadata"]["audio_url"], "https://reference.test/a.wav")
        upload.assert_called_once()
        self.assertEqual(download.call_args.kwargs["output_format"], "")

    def test_missing_training_id_is_not_fabricated(self):
        with patch.object(nodes, "get_config", return_value=CONFIG), \
             patch.object(nodes, "audio_to_wav_bytes", return_value=b"wav"), \
             patch.object(nodes, "upload_media", return_value="https://reference.test/a.wav"), \
             patch.object(nodes, "submit_audio_task", return_value="test-task"), \
             patch.object(nodes, "poll_audio_task", return_value={"data": {"status": "SUCCESS"}}):
            with self.assertRaisesRegex(SeedanceAPIError, "speaker ID"):
                nodes.DoubaoVoiceCloneICL().execute(**self.clone(custom_speaker_id="requestedVoice"))

    def test_oversized_encoded_sample_is_rejected_before_network(self):
        with patch.object(nodes, "audio_to_wav_bytes", return_value=b"x" * (10 * 1024 * 1024 + 1)), \
             patch.object(nodes, "get_config") as config, patch.object(nodes, "upload_media") as upload:
            with self.assertRaisesRegex(SeedanceAPIError, "10 MB"):
                nodes.DoubaoVoiceCloneICL().execute(**self.clone())
        config.assert_not_called()
        upload.assert_not_called()

    def test_synthesis_downloads_without_retraining_or_upload(self):
        with patch.object(nodes, "get_config", return_value=CONFIG), patch.object(nodes, "upload_media") as upload, \
             patch.object(nodes, "submit_audio_task", return_value="test-task") as submit, \
             patch.object(nodes, "poll_audio_task", return_value={"data": {"result_url": "https://result.test/a.pcm"}}), \
             patch.object(nodes, "download_audio", return_value=(AUDIO, "a.pcm")) as download:
            result = nodes.DoubaoVoiceCloneICL().execute(**self.synth(output_format="pcm", sample_rate="48000"))
        upload.assert_not_called()
        self.assertEqual(submit.call_args.args[0]["model"], nodes.DOUBAO_ICL_MODEL)
        self.assertEqual(download.call_args.kwargs["sample_rate"], 48000)
        self.assertIs(result["result"][0], AUDIO)

    def test_skip_error_returns_silence_and_empty_runtime_fields(self):
        result = nodes.DoubaoVoiceCloneICL().execute(**self.synth(speaker=""), skip_error=True)
        self.assertEqual(result["result"][0]["waveform"].shape, (1, 1, 24000))
        self.assertEqual(result["result"][1:5], ("", "", "", ""))


class ExampleAndFrontendTests(unittest.TestCase):
    def test_nine_workflows_and_training_chain_have_valid_connections_and_blank_keys(self):
        paths = [path for path in (ROOT / "examples").glob("*.json") if any(node["type"] in
                 ("Zhenzhen_Image_NB_Lowprice", "Doubao_Voice_Clone_ICL") for node in json.loads(path.read_text(encoding="utf-8"))["nodes"])]
        self.assertEqual(len(paths), 9)
        combinations = set()
        for path in paths:
            workflow = json.loads(path.read_text(encoding="utf-8"))
            by_id = {node["id"]: node for node in workflow["nodes"]}
            for node in by_id.values():
                if node["type"] == "Seedance_Config":
                    self.assertEqual(node["widgets_values"][1], "")
                if node["type"] == "Zhenzhen_Image_NB_Lowprice":
                    combinations.add((node["widgets_values"][0], sum(item["type"] == "LoadImage" for item in by_id.values())))
                    self.assertEqual(len(node["inputs"]), 15)
            for link_id, origin, origin_slot, target, target_slot, kind in workflow["links"]:
                self.assertEqual(by_id[origin]["outputs"][origin_slot]["type"], kind)
                self.assertEqual(by_id[target]["inputs"][target_slot]["type"], kind)
                self.assertEqual(by_id[target]["inputs"][target_slot]["link"], link_id)
        self.assertEqual(combinations, {(model, count) for model in nodes.ZHENZHEN_IMAGE_NB_LOWPRICE_MODELS for count in range(3)})
        chain = json.loads((ROOT / "examples" / "doubao音色训练到ICL语音合成.json").read_text(encoding="utf-8"))
        self.assertTrue(any(link[2] == 3 and link[5] == "STRING" for link in chain["links"]))

    def test_frontend_dynamic_controls_and_converted_widgets(self):
        executable = shutil.which("node")
        if not executable:
            self.skipTest("Node.js unavailable")
        result = subprocess.run([executable, str(ROOT / "tests" / "nb_lowprice_doubao_ui.mjs")], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
