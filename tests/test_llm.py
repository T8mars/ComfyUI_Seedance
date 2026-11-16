import asyncio
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import concurrent_nodes, nodes
from ComfyUI_Seedance.core import llm
from ComfyUI_Seedance.core.client import SeedanceAPIError

CONFIG = {"base_url": "https://api.seedance.nz", "api_key": "sk-test"}
IMAGE = torch.zeros(1, 8, 8, 3)


def response(body=None, lines=None, status=200):
    result = Mock(status_code=status)
    result.headers = {"Content-Type": "text/event-stream" if lines is not None else "application/json"}
    result.json.return_value = body or {"choices": [{"message": {"role": "assistant", "content": "Hello", "reasoning_content": "Think"}}]}
    result.iter_lines.return_value = iter(lines or [])
    return result


class LLMTests(unittest.TestCase):
    def setUp(self):
        llm._catalog_cache.clear()

    def test_registration_is_independent_and_not_an_image_video_future(self):
        cls = nodes.NODE_CLASS_MAPPINGS["Seedance_LLM_API"]
        self.assertIs(cls, nodes.SeedanceLLMAPI)
        self.assertEqual(cls.RETURN_TYPES, ("STRING",) * 4)
        schema = cls.INPUT_TYPES()
        self.assertFalse(schema["optional"]["skip_error"][1]["default"])
        self.assertTrue(schema["optional"]["seed"][1]["control_after_generate"])
        self.assertTrue(cls.SEEDANCE_CACHE_ONLY_SEED)
        self.assertNotIn("Seedance_LLM_API", concurrent_nodes.PURE_IMAGE_NODE_KEYS + concurrent_nodes.PURE_VIDEO_NODE_KEYS)

    def test_only_exact_https_seedance_origin_accepted_before_http(self):
        for url in ("http://api.seedance.nz", "https://api.seedance.nz.evil.example", "https://other.example", "https://api.seedance.nz/v1", "https://user@api.seedance.nz", "https://api.seedance.nz:444", "https://api.seedance.nz?host=other.example", "https://api.seedance.nz/#x"):
            with patch.object(llm, "_session") as session:
                with self.assertRaises((SeedanceAPIError, ValueError)):
                    llm.complete({**CONFIG, "base_url": url}, {"prompt": "Hello"})
                session.assert_not_called()
        for url in ("https://api.seedance.nz", "https://api.seedance.nz/", "https://api.seedance.nz:443"):
            llm.check_origin({**CONFIG, "base_url": url})

    def test_catalog_positive_documented_llms_not_openai_endpoint_tag(self):
        res = response({"data": [{"id": llm.MODELS[1]}, {"id": "tripo-h-v3.1-text-to-3d", "supported_endpoint_types": ["openai"]},
            {"id": "minimax-h3-image", "supported_endpoint_types": ["openai"]}, {"id": llm.MODELS[0]}, {"id": llm.MODELS[0]}]})
        with patch.object(llm, "_session") as session:
            session.return_value.get.return_value = res
            self.assertEqual(llm.catalog(CONFIG), llm.MODELS[:2])
            args, kwargs = session.return_value.get.call_args
            self.assertEqual(args, (llm.BASE_URL+"/v1/models",))
            self.assertFalse(kwargs["allow_redirects"])
        res.close.assert_called_once()

    def test_catalog_cache_is_key_scoped_refreshable_and_no_silent_failure_fallback(self):
        with patch.object(llm, "_session") as session:
            session.return_value.get.return_value = response({"data": [{"id": llm.MODELS[0]}]})
            llm.catalog(CONFIG)
            llm.catalog(CONFIG)
            self.assertEqual(session.return_value.get.call_count, 1)
            llm.catalog({**CONFIG, "api_key": "sk-another"})
            llm.catalog(CONFIG, force=True)
            self.assertEqual(session.return_value.get.call_count, 3)
            session.return_value.get.return_value = response(status=401)
            with self.assertRaisesRegex(SeedanceAPIError, "401"):
                llm.catalog(CONFIG, force=True)

    def test_empty_or_invalid_catalog_is_rejected(self):
        for body in ({"data": []}, {"data": [{"id": "video-model"}]}, {"data": {}}, []):
            with patch.object(llm, "_session") as session:
                res = response()
                res.json.return_value = body
                session.return_value.get.return_value = res
                with self.assertRaises(SeedanceAPIError):
                    llm.catalog(CONFIG, True)
                res.close.assert_called_once()

    def test_request_whitelist_defaults_temperature_and_cache_seed_omitted(self):
        body = llm.payload({"prompt": " Hello ", "seed": 123, "api_config": CONFIG, "unsupported": True})
        self.assertEqual(set(body), {"model", "messages", "max_tokens", "stream"})
        self.assertEqual(body["messages"][-1], {"role": "user", "content": "Hello"})
        self.assertFalse(body["stream"])
        custom = llm.payload({"prompt": "Hi", "temperature_mode": "custom", "temperature": 0})
        self.assertEqual(custom["temperature"], 0)

    def test_queue_defers_connected_prompt_and_runtime_rejects_invalid_types(self):
        self.assertTrue(nodes.SeedanceLLMAPI.VALIDATE_INPUTS())
        for kwargs in ({"prompt": " "}, {"prompt": 123}, {"prompt": "x", "model": "moss-image"}, {"prompt": "x", "stream": "true"}):
            with self.assertRaises(SeedanceAPIError):
                llm.payload(kwargs)

    def test_numeric_controls_validate_only_explicit_temperature(self):
        for kwargs in ({"max_tokens": True}, {"max_tokens": 0}, {"max_tokens": 32769}, {"timeout": 9}, {"timeout": 601},
                       {"temperature_mode": "custom", "temperature": float("nan")}, {"temperature_mode": "custom", "temperature": 3}):
            with self.assertRaises(SeedanceAPIError):
                llm.validate(kwargs)
        self.assertTrue(llm.validate({"temperature_mode": "api_default", "temperature": 999}))

    def test_history_json_schema_and_roles(self):
        for text in ("bad", "{}", '[{"role":"tool","content":"x"}]', '[{"role":"user","content":null}]', '[{"role":"user","content":"x","tools":[]}]', '[{"role":"user","content":[{"type":"video_url"}]}]'):
            with self.assertRaises(SeedanceAPIError):
                llm.history(text)
        self.assertEqual(llm.history(""), [])
        self.assertEqual(llm.history('[{"role":"assistant","content":"previous"}]')[0]["content"], "previous")

    def test_history_system_replacement_and_roundtrip(self):
        prior = json.dumps([{"role": "system", "content": "old"}, {"role": "user", "content": "one"}, {"role": "assistant", "content": "two"}])
        body = llm.payload({"prompt": "three", "system_prompt": "new", "history": prior})
        self.assertEqual([message["content"] for message in body["messages"]], ["new", "one", "two", "three"])
        body = llm.payload({"prompt": "three", "system_prompt": "", "history": prior})
        self.assertEqual(body["messages"][0]["content"], "old")

    def test_images_are_ordered_data_uris_and_glm_text_only_is_enforced(self):
        with patch.object(llm, "image_to_png_bytes", side_effect=[b"one", b"three"]) as encode:
            body = llm.payload({"prompt": "describe", "image3": IMAGE, "image1": IMAGE})
        parts = body["messages"][-1]["content"]
        self.assertEqual([part["image_url"]["url"] for part in parts[1:]], ["data:image/png;base64,b25l", "data:image/png;base64,dGhyZWU="])
        self.assertEqual(encode.call_count, 2)
        with self.assertRaisesRegex(SeedanceAPIError, "text-only"):
            llm.payload({"prompt": "describe", "model": "glm-5.3", "image1": IMAGE})
        with self.assertRaises(SeedanceAPIError):
            llm.payload({"prompt": "describe", "model": "glm-5.3", "history": json.dumps([{ "role":"user", "content":parts}])})

    def test_bad_images_fail_before_network(self):
        for image in (torch.zeros(2,8,8,3), torch.zeros(1,8,8,1), torch.full((1,8,8,3),float("nan"))):
            with patch.object(llm, "_session") as session:
                with self.assertRaises(SeedanceAPIError):
                    llm.complete(CONFIG, {"prompt": "describe", "image1": image})
                session.assert_not_called()
        with self.assertRaises(SeedanceAPIError):
            llm.validate({"image5": IMAGE})

    def test_nonstream_returns_text_reasoning_history_and_result_fields(self):
        body = {"id":"test-id", "model":llm.MODELS[0], "usage":{"anything":1}, "choices":[{"message":{"content":"Answer", "reasoning_content":"Think"}}]}
        res = response(body)
        with patch.object(llm, "_session") as session:
            session.return_value.post.return_value = res
            answer = llm.complete(CONFIG, {"prompt": "Question"})
            self.assertEqual(session.return_value.post.call_count, 1)
            args, kwargs = session.return_value.post.call_args
            self.assertEqual(args, (llm.BASE_URL+"/v1/chat/completions",))
            self.assertFalse(kwargs["allow_redirects"])
            self.assertNotIn("seed", kwargs["json"])
        self.assertEqual(answer[:2], ("Answer", "Think"))
        self.assertEqual(json.loads(answer[2])[-1], {"role":"assistant", "content":"Answer"})
        self.assertNotIn("usage", json.loads(answer[3]))
        res.close.assert_called_once()

    def test_text_array_response(self):
        self.assertEqual(llm.text_content([{"type":"text","text":"one"},{"type":"image_url"},{"type":"text","text":"two"}]), "onetwo")

    def test_stream_unicode_reasoning_done_and_finish(self):
        events = [
            ': comment', 'event: message',
            'data: '+json.dumps({"choices":[{"index":0,"delta":{"reasoning_content":"思考"}}]},ensure_ascii=False), '',
            'data: '+json.dumps({"choices":[{"index":0,"delta":{"content":"你好"}}]},ensure_ascii=False), '',
            'data: '+json.dumps({"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}), '', 'data: [DONE]', '',
        ]
        res = response(lines=events)
        with patch.object(llm, "_session") as session:
            session.return_value.post.return_value = res
            value = llm.complete(CONFIG, {"prompt":"Hi", "stream":True})
        self.assertEqual(value[:2], ("你好", "思考"))
        self.assertEqual(json.loads(value[2])[-1]["content"], "你好")
        res.close.assert_called_once()

    def test_stream_missing_done_can_finish_with_explicit_finish_reason(self):
        res = response(lines=['data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":"stop"}]}', ''])
        self.assertEqual(llm.read_stream(res), ("Hi", ""))

    def test_incomplete_invalid_and_error_streams_never_replay(self):
        for events in (['data: {"choices":[{"delta":{"content":"partial"}}]}',''], ['data: bad',''], ['data: {"error":{"message":"failed"}}','']):
            res = response(lines=events)
            with patch.object(llm, "_session") as session:
                session.return_value.post.return_value = res
                with self.assertRaises(SeedanceAPIError):
                    llm.complete(CONFIG, {"prompt":"Hi", "stream":True})
                self.assertEqual(session.return_value.post.call_count, 1)
            res.close.assert_called_once()

    def test_http_errors_redirects_and_empty_final_never_replay(self):
        for res in (response(status=302), response(status=429), response(status=502), response({"choices":[{"message":{"content":None,"reasoning_content":"thinking"}}]})):
            with patch.object(llm, "_session") as session:
                session.return_value.post.return_value = res
                with self.assertRaises(SeedanceAPIError):
                    llm.complete(CONFIG, {"prompt":"Hi"})
                self.assertEqual(session.return_value.post.call_count, 1)
            res.close.assert_called_once()

    def test_skip_error_preserves_history_and_never_exposes_key(self):
        with patch.object(nodes, "get_config", return_value=CONFIG), patch.object(llm, "complete", side_effect=RuntimeError("failure "+CONFIG["api_key"])):
            with self.assertRaises(SeedanceAPIError) as error:
                nodes.SeedanceLLMAPI().execute(prompt="Hi")
            self.assertNotIn(CONFIG["api_key"], str(error.exception))
            result = nodes.SeedanceLLMAPI().execute(prompt="Hi", skip_error=True, history="[]")["result"]
        self.assertEqual(result[:3], ("", "", "[]"))
        self.assertNotIn(CONFIG["api_key"], result[3])

    def test_cache_seed_is_not_forwarded_to_llm(self):
        with patch.object(nodes, "get_config", return_value=CONFIG), patch.object(llm, "complete", return_value=("Hi","","[]","{}")) as complete:
            nodes.SeedanceLLMAPI().execute(prompt="Hello", seed=99)
            self.assertNotIn("seed", complete.call_args.args[1])

    def test_four_examples_blank_keys_and_history_link(self):
        paths = list((ROOT/"examples").glob("SeedanceLLM*.json"))
        self.assertEqual(len(paths), 4)
        history_workflow = None
        for path in paths:
            graph = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(next(n for n in graph["nodes"] if n["type"] == "Seedance_Config")["widgets_values"][1], "")
            if "历史" in path.name:
                history_workflow = graph
        self.assertTrue(any(link[2] == 2 and link[5] == "STRING" for link in history_workflow["links"]))

    def test_all_five_multiview_examples_have_four_ordered_views(self):
        files = list((ROOT/"examples").glob("tripo-*-multiview-to-3d示例.json"))
        self.assertEqual(len(files), 5)
        for path in files:
            graph = json.loads(path.read_text(encoding="utf-8"))
            target = next(n for n in graph["nodes"] if n["type"] == "Tripo_Generate")
            inputs = {item["name"]: item["link"] for item in target["inputs"]}
            self.assertTrue(all(inputs[f"image{i}"] is not None for i in range(1,5)))
            sources = {n["id"]: n for n in graph["nodes"]}
            for index, view in enumerate(("front","left","back","right"), 1):
                link = next(link for link in graph["links"] if link[0] == inputs[f"image{index}"])
                self.assertEqual(sources[link[1]]["widgets_values"][0], "tripo_"+view+".png")

    def route(self):
        from ComfyUI_Seedance.core import llm_routes
        captured = {}
        server = SimpleNamespace(routes=SimpleNamespace(post=lambda path: lambda function: captured.setdefault(path, function)))
        with patch.dict(sys.modules, {"server": SimpleNamespace(PromptServer=SimpleNamespace(instance=server))}):
            llm_routes.register()
            llm_routes.register()
        self.assertEqual(len(captured), 1)
        return captured["/seedance/llm/models"]

    def test_local_refresh_route_returns_only_models_and_never_credentials(self):
        from ComfyUI_Seedance.core import llm_routes
        handler = self.route()
        request = SimpleNamespace(content_length=100, json=AsyncMock(return_value={"api_config": CONFIG}))
        with patch.object(llm_routes, "get_config", return_value=CONFIG), patch.object(llm, "catalog", return_value=llm.MODELS[:2]) as catalog:
            result = asyncio.run(handler(request))
        self.assertEqual(result.status, 200)
        value = json.loads(result.body)
        self.assertEqual(value, {"models": llm.MODELS[:2], "source": llm.BASE_URL})
        self.assertNotIn(CONFIG["api_key"], result.text)
        self.assertTrue(catalog.call_args.args[1])

    def test_local_refresh_route_rejects_oversize_and_unknown_parameters(self):
        handler = self.route()
        for request in (SimpleNamespace(content_length=17000, json=AsyncMock()), SimpleNamespace(content_length=10, json=AsyncMock(return_value={"url":"https://other.example"}))):
            with patch.object(llm, "catalog") as catalog:
                result = asyncio.run(handler(request))
            self.assertEqual(result.status, 400)
            catalog.assert_not_called()

    def test_local_refresh_errors_are_redacted(self):
        from ComfyUI_Seedance.core import llm_routes
        handler = self.route()
        request = SimpleNamespace(content_length=100, json=AsyncMock(return_value={}))
        with patch.object(llm_routes, "get_config", return_value=CONFIG), patch.object(llm, "catalog", side_effect=RuntimeError(CONFIG["api_key"])):
            result = asyncio.run(handler(request))
        self.assertEqual(result.status, 400)
        self.assertNotIn(CONFIG["api_key"], result.text)
