import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT.parent))

from ComfyUI_Seedance import nodes
from ComfyUI_Seedance.core import client


EXPECTED_OPERATIONS = [
    "flowmusic-generation",
    "flowmusic-lyrics",
    "flowmusic-upload-audio",
    "flowmusic-extend",
    "flowmusic-replace",
    "flowmusic-cover",
    "flowmusic-stems",
    "flowmusic-download-audio",
    "flowmusic-video-clip",
]


def values():
    return {
        "version": "default",
        "sound_prompt": "warm cinematic piano",
        "lyrics": "",
        "prompt": "a hopeful song after rain",
        "title": "",
        "bpm": 120,
        "length": 30,
        "clip_id": "clip-source",
        "extend_from_s": 0.0,
        "extend_s": 15,
        "instruction": "continue naturally with soft strings",
        "start_s": 0.0,
        "end_s": 5.0,
        "strength": 0.5,
        "format": "mp3",
        "preset": "modern",
        "seed": 7,
    }


class FlowMusicContractTests(unittest.TestCase):
    def setUp(self):
        self.node = nodes.FlowMusic()

    def test_operation_catalog_and_paths_are_exact(self):
        self.assertEqual(nodes.FLOWMUSIC_OPERATIONS, EXPECTED_OPERATIONS)
        for operation in EXPECTED_OPERATIONS:
            expected_action = "" if operation == "flowmusic-generation" else operation[10:]
            with self.subTest(operation=operation):
                self.assertEqual(
                    nodes.FLOWMUSIC_ACTION_SPECS[operation]["action"],
                    expected_action,
                )

    def test_every_payload_uses_fixed_model_and_action_whitelist(self):
        for operation in EXPECTED_OPERATIONS:
            uploaded = "https://media.test/source.wav" if operation == "flowmusic-upload-audio" else ""
            with self.subTest(operation=operation):
                payload = self.node._build_payload(operation, uploaded, **values())
                allowed = set(nodes.FLOWMUSIC_ACTION_SPECS[operation]["allowed_fields"])
                self.assertEqual(payload["model"], "flowmusic")
                self.assertTrue(set(payload).issubset({"model", *allowed}))

    def test_generation_requires_sound_or_lyrics_and_honors_ranges(self):
        kwargs = values()
        kwargs.update({"sound_prompt": "", "lyrics": ""})
        with self.assertRaisesRegex(client.SeedanceAPIError, "cannot both be empty"):
            self.node._build_payload("flowmusic-generation", **kwargs)
        kwargs = values()
        kwargs["length"] = 241
        with self.assertRaisesRegex(client.SeedanceAPIError, "1 and 240"):
            self.node._build_payload("flowmusic-generation", **kwargs)

    def test_generation_payload_preserves_documented_types(self):
        kwargs = values()
        payload = self.node._build_payload("flowmusic-generation", **kwargs)
        self.assertEqual(payload, {
            "model": "flowmusic",
            "sound_prompt": "warm cinematic piano",
            "bpm": "120",
            "length": 30,
            "seed": 7,
        })

    def test_lyria_version_is_sent_only_by_supported_actions(self):
        supported = {
            "flowmusic-generation",
            "flowmusic-extend",
            "flowmusic-replace",
            "flowmusic-cover",
        }
        for operation in EXPECTED_OPERATIONS:
            kwargs = values()
            kwargs["version"] = "lyria-3.5"
            uploaded = "https://media.test/source.wav" if operation == "flowmusic-upload-audio" else ""
            payload = self.node._build_payload(operation, uploaded, **kwargs)
            with self.subTest(operation=operation):
                self.assertEqual(payload.get("version"), "lyria-3.5" if operation in supported else None)

    def test_lyrics_replace_cover_and_extend_validation(self):
        kwargs = values()
        kwargs["prompt"] = "x" * 3001
        with self.assertRaisesRegex(client.SeedanceAPIError, "3000"):
            self.node._build_payload("flowmusic-lyrics", **kwargs)
        kwargs = values()
        kwargs.update({"start_s": 5.0, "end_s": 5.0})
        with self.assertRaisesRegex(client.SeedanceAPIError, "greater"):
            self.node._build_payload("flowmusic-replace", **kwargs)
        kwargs = values()
        kwargs["strength"] = 1.1
        with self.assertRaisesRegex(client.SeedanceAPIError, "between 0 and 1"):
            self.node._build_payload("flowmusic-cover", **kwargs)
        kwargs = values()
        kwargs["extend_s"] = 165
        with self.assertRaisesRegex(client.SeedanceAPIError, "164"):
            self.node._build_payload("flowmusic-extend", **kwargs)

    def test_upload_accepts_one_local_or_public_audio_source(self):
        config = {"api_key": "not-a-real-key"}
        with self.assertRaisesRegex(client.SeedanceAPIError, "cannot both"):
            self.node._resolve_audio_url(
                "flowmusic-upload-audio", object(), "https://media.test/a.wav", config
            )
        with (
            patch.object(nodes, "audio_to_wav_bytes", return_value=b"wav"),
            patch.object(nodes, "upload_media", return_value="https://media.test/upload.wav") as upload,
        ):
            url = self.node._resolve_audio_url(
                "flowmusic-upload-audio", object(), "", config
            )
        self.assertEqual(url, "https://media.test/upload.wav")
        upload.assert_called_once()


class FlowMusicResultTests(unittest.TestCase):
    def test_music_result_extracts_nested_lyrics_and_clip_ids(self):
        response = {
            "data": {
                "id": "task-test",
                "status": "completed",
                "result": {
                    "lyrics": [{"title": "Rain", "lyrics": "Light after rain"}],
                    "music": [
                        {"clip_id": "clip-one", "audio_url": "https://media.test/a.wav"},
                        {"clip_id": "clip-two", "video_url": "https://media.test/a.mp4"},
                    ],
                },
            }
        }
        extracted = client.extract_music_results(response)
        self.assertEqual(extracted["clip_ids"], ["clip-one", "clip-two"])
        self.assertEqual(extracted["text"], "Light after rain")
        self.assertEqual(extracted["audio_urls"], ["https://media.test/a.wav"])
        self.assertEqual(extracted["video_urls"], ["https://media.test/a.mp4"])

    def test_execute_returns_clip_and_downloaded_audio(self):
        node = nodes.FlowMusic()
        final = {
            "data": {
                "id": "task-test",
                "status": "completed",
                "result": {
                    "music": [{
                        "clip_id": "clip-result",
                        "audio_url": "https://media.test/result.wav",
                    }]
                },
            }
        }
        audio = {"waveform": object(), "sample_rate": 44100}
        with (
            patch.object(nodes, "get_config", return_value={"base_url": "https://example.test", "api_key": "test"}),
            patch.object(nodes, "submit_music_action", return_value=("task-test", {})) as submit,
            patch.object(nodes, "poll_music_task", return_value=final),
            patch.object(nodes, "download_audio", return_value=(audio, "result.wav")),
        ):
            result = node.execute(operation="flowmusic-generation", **values())
        self.assertEqual(submit.call_args.args[0], "")
        self.assertEqual(result["result"][0], audio)
        self.assertEqual(result["result"][4], "clip-result")

    def test_skip_error_returns_all_typed_outputs(self):
        result = nodes.FlowMusic().execute(
            operation="flowmusic-lyrics",
            skip_error=True,
            **{**values(), "prompt": ""},
        )
        self.assertEqual(len(result["result"]), 11)
        self.assertIn("error", result["result"][-1])


class FlowMusicRegistrationAndWorkflowTests(unittest.TestCase):
    def test_node_and_frontend_are_registered(self):
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Flow_Music"], nodes.FlowMusic)
        source = (PLUGIN_ROOT / "web" / "js" / "flowmusic_action_ui.js").read_text(
            encoding="utf-8"
        )
        for fragment in (
            'const FLOWMUSIC_NODE_NAME = "Flow_Music"',
            '"flowmusic-video-clip": ["clip_id", "preset"]',
            'from "./dynamic_widget_ui.js"',
            "setInputVisible(node, input, visible.has(input.name))",
            "refreshFlowMusicNode(this)",
        ):
            self.assertIn(fragment, source)

    def test_all_nine_safe_workflows_exist_and_clip_actions_are_chained(self):
        paths = sorted((PLUGIN_ROOT / "examples").glob("flowmusic-*.json"))
        self.assertEqual(len(paths), 9)
        covered = set()
        clip_actions = set(EXPECTED_OPERATIONS) - {
            "flowmusic-generation", "flowmusic-lyrics", "flowmusic-upload-audio",
        }
        for path in paths:
            workflow = json.loads(path.read_text(encoding="utf-8"))
            flow_nodes = [item for item in workflow["nodes"] if item["type"] == "Flow_Music"]
            selected = {item["widgets_values"][0] for item in flow_nodes}
            operation = next(item for item in EXPECTED_OPERATIONS if path.name.startswith(item))
            covered.add(operation)
            self.assertIn(operation, selected)
            target_node = next(
                item for item in flow_nodes if item["widgets_values"][0] == operation
            )
            if operation == "flowmusic-replace":
                self.assertEqual(target_node["widgets_values"][1], "lyria-3.5")
            config = next(item for item in workflow["nodes"] if item["type"] == "Seedance_Config")
            self.assertEqual(config["widgets_values"][1], "")
            source = path.read_text(encoding="utf-8")
            self.assertNotRegex(source, r"sk-[A-Za-z0-9]{12,}")
            self.assertNotRegex(source, r'"task_[A-Za-z0-9_-]{6,}"')
            if operation in clip_actions:
                target = target_node
                clip_links = [
                    link for link in workflow["links"]
                    if link[3] == target["id"] and link[5] == "STRING"
                ]
                self.assertEqual(len(clip_links), 1)
                self.assertIn("flowmusic-upload-audio", selected)
        self.assertEqual(covered, set(EXPECTED_OPERATIONS))


if __name__ == "__main__":
    unittest.main()
