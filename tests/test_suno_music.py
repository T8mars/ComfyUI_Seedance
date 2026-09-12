import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT.parent))

from ComfyUI_Seedance import nodes
from ComfyUI_Seedance.core import client


EXPECTED_OPERATIONS = [
    "suno-generation",
    "suno-create-model",
    "suno-upload-cover",
    "suno-upload-extend",
    "suno-lyrics",
    "suno-upload",
    "suno-extend",
    "suno-cover-song",
    "suno-inspo",
    "suno-mashup",
    "suno-upsample-tags",
    "suno-sounds",
    "suno-create-voice",
    "suno-stems",
    "suno-stems-all",
    "suno-wav",
    "suno-generate-mp4",
    "suno-concat",
    "suno-crop",
    "suno-fade-in",
    "suno-fade-out",
    "suno-remove-section",
    "suno-replace-music",
    "suno-adjust-speed",
    "suno-remaster",
    "suno-midi",
    "suno-bpm",
    "suno-aligned-lyrics",
    "suno-persona",
    "suno-vox",
    "suno-sample",
    "suno-add-vocals",
    "suno-add-instrumental",
    "suno-add-stem",
]

EXPECTED_REQUIRED = {
    "suno-generation": ("version", "prompt"),
    "suno-create-model": ("name", "audio_urls"),
    "suno-upload-cover": ("audio_url",),
    "suno-upload-extend": ("audio_url", "continue_at"),
    "suno-lyrics": ("prompt",),
    "suno-upload": ("audioFilePath",),
    "suno-extend": ("task_id", "continue_at"),
    "suno-cover-song": ("task_id", "prompt"),
    "suno-inspo": ("audio_urls",),
    "suno-mashup": ("task_ids", "prompt"),
    "suno-upsample-tags": ("tags",),
    "suno-sounds": ("prompt",),
    "suno-create-voice": ("audio_url",),
    "suno-stems": ("task_id",),
    "suno-stems-all": ("task_id",),
    "suno-wav": ("task_id",),
    "suno-generate-mp4": ("task_id",),
    "suno-concat": ("task_id",),
    "suno-crop": ("task_id", "start_s", "end_s"),
    "suno-fade-in": ("task_id", "duration_s"),
    "suno-fade-out": ("task_id", "duration_s"),
    "suno-remove-section": ("task_id", "start_s", "end_s"),
    "suno-replace-music": ("task_id", "start_s", "end_s"),
    "suno-adjust-speed": ("task_id", "speed"),
    "suno-remaster": ("task_id",),
    "suno-midi": ("task_id",),
    "suno-bpm": ("task_id",),
    "suno-aligned-lyrics": ("task_id",),
    "suno-persona": ("task_id", "name"),
    "suno-vox": ("task_id",),
    "suno-sample": ("task_id", "start_s", "end_s", "prompt"),
    "suno-add-vocals": ("task_id", "prompt"),
    "suno-add-instrumental": ("task_id", "prompt"),
    "suno-add-stem": ("task_id", "prompt"),
}


def base_kwargs():
    return {
        "prompt": "soft piano with rain",
        "version": "v6",
        "custom": False,
        "instrumental": True,
        "title": "",
        "style": "",
        "vocal_gender": "unspecified",
        "tags": "ambient, piano",
        "name": "Studio Voice",
        "task_id": "source-one",
        "task_id_2": "source-two",
        "audio_index": 1,
        "continue_at": 30.0,
        "start_s": 1.0,
        "end_s": 4.0,
        "duration_s": 2.0,
        "speed": 1.1,
        "custom_model_id": "",
        "gpt_description": "turn the source into a calm cinematic arrangement",
        "negative_tags": "harsh vocals",
        "style_weight": 0.6,
        "weirdness": 0.2,
        "audio_weight": 0.7,
        "auto_lyrics": False,
        "persona_id": "",
        "target_duration_s": 10,
        "variety": "normal",
        "max_mode": False,
        "audio_format": "mp3",
    }


class SunoActionSpecTests(unittest.TestCase):
    def test_operation_catalog_matches_documented_registry(self):
        self.assertEqual(nodes.SUNO_OPERATIONS, EXPECTED_OPERATIONS)
        self.assertEqual(len(nodes.SUNO_ACTION_SPECS), 34)

    def test_paths_are_explicit_and_kebab_case(self):
        for operation in EXPECTED_OPERATIONS:
            spec = nodes.SUNO_ACTION_SPECS[operation]
            expected_action = "" if operation == "suno-generation" else operation[5:]
            with self.subTest(operation=operation):
                self.assertEqual(spec["action"], expected_action)

    def test_required_fields_match_verified_contract(self):
        for operation, required in EXPECTED_REQUIRED.items():
            with self.subTest(operation=operation):
                self.assertEqual(
                    nodes.SUNO_ACTION_SPECS[operation]["required_fields"],
                    required,
                )

    def test_only_upsample_tags_is_synchronous(self):
        synchronous = [
            operation
            for operation, spec in nodes.SUNO_ACTION_SPECS.items()
            if spec["sync"]
        ]
        self.assertEqual(synchronous, ["suno-upsample-tags"])

    def test_every_required_field_is_allowed(self):
        for operation, spec in nodes.SUNO_ACTION_SPECS.items():
            with self.subTest(operation=operation):
                self.assertTrue(
                    set(spec["required_fields"]).issubset(spec["allowed_fields"])
                )

    def test_new_inputs_are_appended_after_legacy_sockets_and_widgets(self):
        inputs = nodes.SunoMusic.INPUT_TYPES()
        optional_names = list(inputs["optional"])
        self.assertEqual(
            optional_names[:10],
            [
                "audio1",
                "audio_url1",
                "audio2",
                "audio_url2",
                "audio3",
                "audio_url3",
                "audio4",
                "audio_url4",
                "api_config",
                "skip_error",
            ],
        )
        self.assertEqual(optional_names[-1], "seed")
        self.assertIn("audio24", optional_names)
        self.assertIn("custom_model_id", optional_names)

    def test_every_operation_has_a_matching_example_workflow(self):
        workflow_paths = sorted((PLUGIN_ROOT / "examples").glob("suno-*.json"))
        self.assertEqual(len(workflow_paths), 34)
        covered = set()
        for workflow_path in workflow_paths:
            expected = next(
                operation
                for operation in sorted(EXPECTED_OPERATIONS, key=len, reverse=True)
                if workflow_path.name.startswith(operation)
            )
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            selected = {
                node["widgets_values"][0]
                for node in workflow["nodes"]
                if node["type"] == "Suno_Music" and node.get("widgets_values")
            }
            with self.subTest(workflow=workflow_path.name):
                self.assertIn(expected, selected)
            covered.add(expected)
        self.assertEqual(covered, set(EXPECTED_OPERATIONS))

    def test_upload_workflow_does_not_connect_an_empty_audio_to_save_audio(self):
        workflow_path = PLUGIN_ROOT / "examples" / "suno-upload本地音频导入.json"
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        node_types = {node["type"] for node in workflow["nodes"]}

        self.assertIn("Suno_Music", node_types)
        self.assertNotIn("SaveAudio", node_types)



    def test_add_actions_use_an_uploaded_audio_source_workflow(self):
        operations = (
            "suno-add-vocals",
            "suno-add-instrumental",
            "suno-add-stem",
        )
        for operation in operations:
            path = next((PLUGIN_ROOT / "examples").glob(f"{operation}*.json"))
            workflow = json.loads(path.read_text(encoding="utf-8"))
            node_types = {node["type"] for node in workflow["nodes"]}
            selected = {
                node["widgets_values"][0]
                for node in workflow["nodes"]
                if node["type"] == "Suno_Music"
            }
            with self.subTest(operation=operation):
                self.assertIn("LoadAudio", node_types)
                self.assertIn("suno-upload", selected)
                self.assertIn(operation, selected)
class SunoPayloadTests(unittest.TestCase):
    def setUp(self):
        self.node = nodes.SunoMusic()

    def test_generation_payload_uses_fixed_model_and_documented_fields(self):
        values = base_kwargs()
        values.update(
            {
                "custom": True,
                "instrumental": False,
                "title": "Rain Room",
                "style": "lo-fi",
                "vocal_gender": "Female",
            }
        )
        payload = self.node._build_payload("suno-generation", [], **values)
        self.assertEqual(
            payload,
            {
                "model": "suno",
                "version": "v6",
                "prompt": "soft piano with rain",
                "custom": True,
                "instrumental": False,
                "title": "Rain Room",
                "style": "lo-fi",
                "vocal_gender": "Female",
            },
        )

    def test_create_model_payload_uses_exactly_the_documented_fields(self):
        urls = [f"https://cdn.example/reference-{index}.wav" for index in range(6)]
        payload = self.node._build_payload(
            "suno-create-model",
            urls,
            **base_kwargs(),
        )
        self.assertEqual(
            payload,
            {
                "model": "suno",
                "name": "Studio Voice",
                "audio_urls": urls,
            },
        )

    def test_upload_cover_custom_payload_matches_v6_contract(self):
        values = base_kwargs()
        values.update(
            {
                "custom": True,
                "instrumental": False,
                "title": "Rain Room",
                "vocal_gender": "Female",
                "tags": "piano, ambient",
                "auto_lyrics": True,
                "max_mode": True,
            }
        )
        payload = self.node._build_payload(
            "suno-upload-cover",
            ["https://cdn.example/reference.wav"],
            **values,
        )
        self.assertEqual(
            payload,
            {
                "model": "suno",
                "audio_url": "https://cdn.example/reference.wav",
                "version": "v6",
                "custom": True,
                "instrumental": False,
                "prompt": "soft piano with rain",
                "tags": "piano, ambient",
                "title": "Rain Room",
                "negative_tags": "harsh vocals",
                "style_weight": 0.6,
                "weirdness": 0.2,
                "audio_weight": 0.7,
                "auto_lyrics": True,
                "vocal_gender": "Female",
                "duration_s": 10,
                "variety": "normal",
                "max_mode": True,
                "audio_format": "mp3",
            },
        )

    def test_upload_cover_inspiration_mode_sends_no_custom_only_fields(self):
        payload = self.node._build_payload(
            "suno-upload-cover",
            ["https://cdn.example/reference.wav"],
            **base_kwargs(),
        )
        self.assertEqual(
            payload,
            {
                "model": "suno",
                "audio_url": "https://cdn.example/reference.wav",
                "version": "v6",
                "custom": False,
                "instrumental": True,
                "gpt_description": (
                    "turn the source into a calm cinematic arrangement"
                ),
                "variety": "normal",
                "audio_format": "mp3",
            },
        )

    def test_upload_extend_omits_forbidden_cover_mode_fields(self):
        values = base_kwargs()
        values.update({"custom": True, "instrumental": True})
        payload = self.node._build_payload(
            "suno-upload-extend",
            ["https://cdn.example/reference.wav"],
            **values,
        )
        self.assertEqual(payload["continue_at"], 30.0)
        self.assertEqual(payload["duration_s"], 10)
        self.assertNotIn("custom", payload)
        self.assertNotIn("instrumental", payload)
        self.assertNotIn("gpt_description", payload)

    def test_custom_model_omits_version_and_rejects_persona(self):
        values = base_kwargs()
        values["custom_model_id"] = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        payload = self.node._build_payload(
            "suno-upload-extend",
            ["https://cdn.example/reference.wav"],
            **values,
        )
        self.assertNotIn("version", payload)
        self.assertEqual(payload["custom_model_id"], values["custom_model_id"])

        values["persona_id"] = "persona-test"
        with self.assertRaisesRegex(client.SeedanceAPIError, "mutually exclusive"):
            self.node._build_payload(
                "suno-upload-extend",
                ["https://cdn.example/reference.wav"],
                **values,
            )

    def test_irrelevant_hidden_values_do_not_enter_payload(self):
        payload = self.node._build_payload("suno-lyrics", [], **base_kwargs())
        self.assertEqual(
            payload,
            {"model": "suno", "prompt": "soft piano with rain"},
        )

    def test_generation_runtime_requires_prompt(self):
        values = base_kwargs()
        values["prompt"] = ""
        with self.assertRaisesRegex(client.SeedanceAPIError, "prompt"):
            self.node._build_payload("suno-generation", [], **values)

    def test_linked_prompt_preflight_does_not_reject_empty_widget(self):
        result = nodes.SunoMusic.VALIDATE_INPUTS(
            operation="suno-generation",
            version="v5.5",
            audio_index=1,
            prompt="",
        )
        self.assertIs(result, True)


    def test_all_operations_build_only_registered_fields(self):
        url_actions = {
            "suno-upload": ["https://cdn.example/source.wav"],
            "suno-create-model": [
                f"https://cdn.example/source-{index}.wav" for index in range(6)
            ],
            "suno-upload-cover": ["https://cdn.example/source.wav"],
            "suno-upload-extend": ["https://cdn.example/source.wav"],
            "suno-create-voice": ["https://cdn.example/source.wav"],
            "suno-inspo": ["https://cdn.example/source.wav"],
        }
        for operation in EXPECTED_OPERATIONS:
            with self.subTest(operation=operation):
                urls = url_actions.get(operation, [])
                payload = self.node._build_payload(operation, urls, **base_kwargs())
                spec = nodes.SUNO_ACTION_SPECS[operation]
                self.assertEqual(payload["model"], "suno")
                self.assertTrue(
                    set(payload).issubset({"model", *spec["allowed_fields"]})
                )
                self.assertTrue(set(spec["required_fields"]).issubset(payload))
    def test_unknown_operation_is_rejected(self):
        with self.assertRaisesRegex(client.SeedanceAPIError, "unsupported"):
            self.node._build_payload("suno-not-real", [], **base_kwargs())

    def test_invalid_version_is_rejected(self):
        values = base_kwargs()
        values["version"] = "v3.5"
        with self.assertRaisesRegex(client.SeedanceAPIError, "does not support"):
            self.node._build_payload("suno-sounds", [], **values)

    def test_mashup_builds_exactly_two_task_ids(self):
        payload = self.node._build_payload("suno-mashup", [], **base_kwargs())
        self.assertEqual(payload["task_ids"], ["source-one", "source-two"])
        self.assertEqual(payload["prompt"], "soft piano with rain")
        self.assertNotIn("task_id", payload)
        self.assertNotIn("audio_index", payload)

    def test_cover_song_forwards_required_prompt(self):
        payload = self.node._build_payload("suno-cover-song", [], **base_kwargs())
        self.assertEqual(payload["task_id"], "source-one")
        self.assertEqual(payload["prompt"], "soft piano with rain")


    def test_verified_edit_actions_forward_required_prompt(self):
        operations = (
            "suno-sample",
            "suno-add-vocals",
            "suno-add-instrumental",
            "suno-add-stem",
        )
        for operation in operations:
            with self.subTest(operation=operation):
                payload = self.node._build_payload(operation, [], **base_kwargs())
                self.assertEqual(payload["prompt"], "soft piano with rain")
    def test_task_audio_payload_is_one_based(self):
        payload = self.node._build_payload("suno-stems", [], **base_kwargs())
        self.assertEqual(
            payload,
            {"model": "suno", "task_id": "source-one", "audio_index": 1},
        )

    def test_range_payload_sends_only_its_time_fields(self):
        payload = self.node._build_payload("suno-crop", [], **base_kwargs())
        self.assertEqual(payload["start_s"], 1.0)
        self.assertEqual(payload["end_s"], 4.0)
        self.assertNotIn("duration_s", payload)
        self.assertNotIn("speed", payload)

    def test_invalid_range_is_rejected(self):
        values = base_kwargs()
        values["start_s"] = 4.0
        values["end_s"] = 1.0
        with self.assertRaisesRegex(client.SeedanceAPIError, "end_s"):
            self.node._build_payload("suno-sample", [], **values)

    def test_upload_and_voice_map_first_audio_url(self):
        upload_payload = self.node._build_payload(
            "suno-upload",
            ["https://cdn.example/source.wav"],
            **base_kwargs(),
        )
        voice_payload = self.node._build_payload(
            "suno-create-voice",
            ["https://cdn.example/source.wav"],
            **base_kwargs(),
        )
        self.assertEqual(
            upload_payload["audioFilePath"], "https://cdn.example/source.wav"
        )
        self.assertEqual(
            voice_payload["audio_url"], "https://cdn.example/source.wav"
        )

    def test_inspo_preserves_one_to_four_slot_order(self):
        urls = [
            "https://cdn.example/a.wav",
            "https://cdn.example/b.wav",
            "https://cdn.example/c.wav",
            "https://cdn.example/d.wav",
        ]
        payload = self.node._build_payload("suno-inspo", urls, **base_kwargs())
        self.assertEqual(payload["audio_urls"], urls)

    def test_create_model_accepts_six_to_twenty_four_audio_slots(self):
        kwargs = {
            f"audio_url{index}": f"https://cdn.example/{index}.wav"
            for index in range(1, 7)
        }
        urls = self.node._collect_audio_inputs(
            "suno-create-model",
            kwargs,
            {"api_key": "not-a-real-key"},
            lambda _fraction: None,
        )
        self.assertEqual(len(urls), 6)

        with self.assertRaisesRegex(client.SeedanceAPIError, "6-24"):
            self.node._collect_audio_inputs(
                "suno-create-model",
                {"audio_url1": "https://cdn.example/1.wav"},
                {"api_key": "not-a-real-key"},
                lambda _fraction: None,
            )

    def test_local_audio_is_uploaded_and_url_slot_is_preserved(self):
        audio = {"waveform": MagicMock(), "sample_rate": 16000}
        kwargs = {
            "audio1": audio,
            "audio_url2": "https://cdn.example/reference.wav",
        }
        with (
            patch.object(nodes, "audio_to_wav_bytes", return_value=b"wav"),
            patch.object(
                nodes,
                "upload_media",
                return_value="https://cdn.example/uploaded.wav",
            ) as upload,
        ):
            urls = self.node._collect_audio_inputs(
                "suno-inspo",
                kwargs,
                {"api_key": "not-a-real-key"},
                lambda _fraction: None,
            )
        self.assertEqual(
            urls,
            [
                "https://cdn.example/uploaded.wav",
                "https://cdn.example/reference.wav",
            ],
        )
        upload.assert_called_once()

    def test_upload_rejects_local_audio_shorter_than_six_seconds(self):
        audio = {
            "waveform": MagicMock(shape=(1, 1, 32000)),
            "sample_rate": 16000,
        }
        with patch.object(nodes, "upload_media") as upload:
            with self.assertRaisesRegex(client.SeedanceAPIError, "at least 6 seconds"):
                self.node._collect_audio_inputs(
                    "suno-upload",
                    {"audio1": audio},
                    {"api_key": "not-a-real-key"},
                    lambda _fraction: None,
                )
        upload.assert_not_called()

    def test_local_and_url_in_same_slot_conflict(self):
        with self.assertRaisesRegex(client.SeedanceAPIError, "cannot both"):
            self.node._collect_audio_inputs(
                "suno-inspo",
                {
                    "audio1": {"waveform": MagicMock()},
                    "audio_url1": "https://cdn.example/reference.wav",
                },
                {},
                lambda _fraction: None,
            )


class SunoExecutionTests(unittest.TestCase):
    def setUp(self):
        self.node = nodes.SunoMusic()

    def test_synchronous_action_returns_text_without_polling(self):
        response = {"data": {"status": "completed", "result": {"tags": "cinematic"}}}
        with (
            patch.object(nodes, "get_config", return_value={"api_key": "unused"}),
            patch.object(
                nodes,
                "submit_music_action",
                return_value=(None, response),
            ),
            patch.object(nodes, "poll_music_task") as poll,
        ):
            result = self.node._execute_inner(
                operation="suno-upsample-tags",
                api_config=None,
                **base_kwargs(),
            )
        poll.assert_not_called()
        self.assertEqual(result["result"][3], "cinematic")
        self.assertEqual(len(result["result"]), 11)


    def test_skip_error_returns_eleven_placeholder_outputs(self):
        with patch.object(
            self.node, "_execute_inner", side_effect=client.SeedanceAPIError("boom")
        ):
            result = self.node.execute(
                operation="suno-generation",
                api_config=None,
                skip_error=True,
                **base_kwargs(),
            )
        self.assertEqual(len(result["result"]), 11)
        self.assertIn("boom", json.loads(result["result"][9])["error"])
    def test_asynchronous_action_polls_and_downloads_two_tracks(self):
        final = {
            "data": {
                "status": "completed",
                "result": {
                    "music": [
                        {
                            "image_url": "https://cdn.example/cover.jpg",
                            "audio_url": "https://cdn.example/a.mp3",
                        },
                        {"audio_url": "https://cdn.example/b.mp3"},
                    ]
                },
            }
        }
        audio_a = {"waveform": "a", "sample_rate": 44100}
        audio_b = {"waveform": "b", "sample_rate": 44100}
        with (
            patch.object(nodes, "get_config", return_value={"api_key": "unused"}),
            patch.object(
                nodes,
                "submit_music_action",
                return_value=("source-result", {"data": []}),
            ),
            patch.object(nodes, "poll_music_task", return_value=final) as poll,
            patch.object(
                nodes,
                "download_audio",
                side_effect=[(audio_a, "a.mp3"), (audio_b, "b.mp3")],
            ),
            patch.object(
                nodes,
                "download_file",
                return_value="cover.jpg",
            ) as download_file,
        ):
            result = self.node._execute_inner(
                operation="suno-generation",
                api_config=None,
                **base_kwargs(),
            )
        poll.assert_called_once()
        self.assertIs(result["result"][0], audio_a)
        self.assertIs(result["result"][1], audio_b)
        self.assertEqual(result["result"][8], "source-result")
        self.assertEqual(result["result"][4], "https://cdn.example/cover.jpg")
        self.assertEqual(result["result"][6], "cover.jpg")
        self.assertEqual(
            json.loads(result["result"][5]),
            [
                "https://cdn.example/cover.jpg",
                "https://cdn.example/a.mp3",
                "https://cdn.example/b.mp3",
            ],
        )
        self.assertEqual(
            json.loads(result["result"][7]),
            ["cover.jpg", "a.mp3", "b.mp3"],
        )
        self.assertEqual(download_file.call_args.kwargs["filename_prefix"], "suno_image")



    def test_partial_artifact_download_preserves_alignment_and_warning(self):
        final = {
            "data": {
                "status": "completed",
                "result": {
                    "audio_url": "https://cdn.example/a.mp3",
                    "video_url": "https://cdn.example/a.mp4",
                },
            }
        }
        audio = {"waveform": "a", "sample_rate": 44100}
        with (
            patch.object(nodes, "get_config", return_value={"api_key": "unused"}),
            patch.object(
                nodes,
                "submit_music_action",
                return_value=("source-result", {"data": []}),
            ),
            patch.object(nodes, "poll_music_task", return_value=final),
            patch.object(nodes, "download_audio", return_value=(audio, "a.mp3")),
            patch.object(
                nodes, "download_video_with_path", side_effect=RuntimeError("403")
            ) as video_download,
        ):
            result = self.node._execute_inner(
                operation="suno-replace-music",
                api_config=None,
                **base_kwargs(),
            )
        self.assertIs(result["result"][0], audio)
        self.assertEqual(json.loads(result["result"][7]), ["a.mp3", ""])
        self.assertEqual(result["result"][6], "a.mp3")
        response = json.loads(result["result"][9])
        self.assertEqual(
            response["_seedance_local"]["download_warnings"],
            [{"artifact_index": 2, "kind": "video", "error": "RuntimeError"}],
        )
        video_download.assert_called_once()

    def test_all_artifact_download_failures_raise(self):
        final = {
            "data": {
                "status": "completed",
                "result": {"audio_url": "https://cdn.example/a.mp3"},
            }
        }
        with (
            patch.object(nodes, "get_config", return_value={"api_key": "unused"}),
            patch.object(
                nodes,
                "submit_music_action",
                return_value=("source-result", {"data": []}),
            ),
            patch.object(nodes, "poll_music_task", return_value=final),
            patch.object(nodes, "download_audio", side_effect=RuntimeError("403")),
        ):
            with self.assertRaisesRegex(client.SeedanceAPIError, "全部下载失败"):
                self.node._execute_inner(
                    operation="suno-generation",
                    api_config=None,
                    **base_kwargs(),
                )

class SunoClientTests(unittest.TestCase):
    def test_submit_extracts_task_id_from_data_list(self):
        response = MagicMock()
        response.status_code = 200
        response.text = '{"data":[{"task_id":"source-result"}]}'
        response.json.return_value = {"data": [{"task_id": "source-result"}]}
        session = MagicMock()
        session.post.return_value = response
        with patch.object(client, "_session", return_value=session):
            task_id, data = client.submit_music_action(
                "extend",
                {"model": "suno", "task_id": "source-one"},
                {"base_url": "https://api.example", "api_key": "unused"},
            )
        self.assertEqual(task_id, "source-result")
        self.assertEqual(data["data"][0]["task_id"], "source-result")
        self.assertTrue(
            session.post.call_args.args[0].endswith(
                "/v1/music/generations/extend"
            )
        )


    def test_poll_raises_on_failed_terminal_state(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "data": {"status": "failed", "fail_reason": "upstream rejected"}
        }
        session = MagicMock()
        session.get.return_value = response
        with (
            patch.object(client, "_session", return_value=session),
            patch.object(client.time, "sleep"),
        ):
            with self.assertRaisesRegex(client.SeedanceAPIError, "upstream rejected"):
                client.poll_music_task(
                    "source-result",
                    {
                        "base_url": "https://api.example",
                        "api_key": "unused",
                        "poll_interval": 0,
                        "max_poll_time": 30,
                    },
                )

    def test_poll_stops_at_configured_timeout(self):
        with (
            patch.object(client.time, "time", side_effect=[0.0, 1.0]),
            patch.object(client.time, "sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "exceeded 0.5s"):
                client.poll_music_task(
                    "source-result",
                    {
                        "base_url": "https://api.example",
                        "api_key": "unused",
                        "poll_interval": 0,
                        "max_poll_time": 0.5,
                    },
                )
    def test_poll_accepts_transient_data_list_before_completion(self):
        submitted = MagicMock()
        submitted.status_code = 200
        submitted.json.return_value = {
            "data": [{"status": "submitted", "task_id": "source-result"}]
        }
        completed_payload = {
            "data": {
                "status": "completed",
                "result": {"music": [{"audio_url": "https://cdn.example/a.mp3"}]},
            }
        }
        completed = MagicMock()
        completed.status_code = 200
        completed.json.return_value = completed_payload
        session = MagicMock()
        session.get.side_effect = [submitted, completed]

        with (
            patch.object(client, "_session", return_value=session),
            patch.object(client.time, "sleep"),
        ):
            result = client.poll_music_task(
                "source-result",
                {
                    "base_url": "https://api.example",
                    "api_key": "unused",
                    "poll_interval": 0,
                    "max_poll_time": 30,
                },
            )

        self.assertEqual(result, completed_payload)
        self.assertEqual(session.get.call_count, 2)

    def test_mp3_decode_falls_back_to_ffmpeg(self):
        decoded = {"waveform": "decoded", "sample_rate": 44100}
        with (
            patch.dict(sys.modules, {"torchaudio": None}),
            patch.object(
                client,
                "_decode_audio_with_ffmpeg",
                return_value=decoded,
            ) as ffmpeg_decode,
        ):
            result = client._decode_audio_file(
                "result.mp3",
                24000,
                "Suno_Music",
            )

        self.assertIs(result, decoded)
        ffmpeg_decode.assert_called_once_with("result.mp3")

    def test_extract_music_results_preserves_multiple_media_types(self):
        response = {
            "data": {
                "id": "source-result",
                "status": "completed",
                "result": {
                    "music": [
                        {
                            "audio_url": "https://cdn.example/a.mp3",
                            "image_url": "https://cdn.example/cover.jpg",
                            "lyrics": "hello world",
                        },
                        {"audio_url": "https://cdn.example/b.wav"},
                    ],
                    "video_url": "https://cdn.example/result.mp4",
                    "midi_url": "https://cdn.example/result.mid",
                },
            }
        }
        extracted = client.extract_music_results(response)
        self.assertEqual(
            extracted["audio_urls"],
            ["https://cdn.example/a.mp3", "https://cdn.example/b.wav"],
        )
        self.assertEqual(
            extracted["video_urls"], ["https://cdn.example/result.mp4"]
        )
        self.assertEqual(
            extracted["file_urls"], ["https://cdn.example/result.mid"]
        )
        self.assertEqual(extracted["text"], "hello world")
        self.assertEqual(
            extracted["artifacts"],
            [
                {"url": "https://cdn.example/a.mp3", "kind": "audio"},
                {"url": "https://cdn.example/cover.jpg", "kind": "image"},
                {"url": "https://cdn.example/b.wav", "kind": "audio"},
                {"url": "https://cdn.example/result.mp4", "kind": "video"},
                {"url": "https://cdn.example/result.mid", "kind": "file"},
            ],
        )

    def test_extract_music_results_exposes_custom_model_id(self):
        response = {
            "data": {
                "id": "source-result",
                "status": "completed",
                "result": {
                    "model_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    "name": "Studio Model",
                },
            }
        }
        extracted = client.extract_music_results(response)
        self.assertEqual(
            extracted["model_ids"],
            ["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
        )


if __name__ == "__main__":
    unittest.main()
