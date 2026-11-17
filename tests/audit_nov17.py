"""Offline workflow and legacy-class compatibility audit; no API calls."""

import ast
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import nodes, concurrent_nodes


def classes(source):
    return {node.name: ast.dump(node, include_attributes=False) for node in ast.parse(source).body if isinstance(node, ast.ClassDef)}


baseline = subprocess.check_output(["git", "show", "HEAD:nodes.py"], cwd=ROOT).decode("utf-8")
previous, current = classes(baseline), classes((ROOT / "nodes.py").read_text(encoding="utf-8"))
unchanged = 0
for name, body in previous.items():
    if name == "Seedance25Video":
        continue
    assert current.get(name) == body, "Unexpected legacy node modification: " + name
    unchanged += 1
workflows = sorted((ROOT / "examples").glob("*.json"))
assert len(workflows) == 370
for path in workflows:
    raw = path.read_text(encoding="utf-8")
    assert not re.search(r"sk-[A-Za-z0-9_-]{20,}", raw), "Credential in " + path.name
    graph = json.loads(raw)
    by_id = {node["id"]: node for node in graph["nodes"]}
    assert len(by_id) == len(graph["nodes"]), path.name
    links = {link[0]: link for link in graph["links"]}
    assert len(links) == len(graph["links"]), path.name
    for node in by_id.values():
        if node["type"] == "Seedance_Config":
            assert node["widgets_values"][1] == "", path.name
        for index, item in enumerate(node.get("inputs", [])):
            if item.get("link") is not None:
                link = links[item["link"]]
                assert link[3:5] == [node["id"], index], path.name
    for link_id, source_id, source_slot, target_id, target_slot, kind in links.values():
        source, target = by_id[source_id], by_id[target_id]
        output, slot = source["outputs"][source_slot], target["inputs"][target_slot]
        assert link_id in output["links"] and slot["link"] == link_id, path.name
        types = {kind, output["type"], slot["type"]} - {"*"}
        assert len(types) <= 1, (path.name, types)
assert len(nodes.NODE_CLASS_MAPPINGS) == 97
assert len(concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS) == 72
assert subprocess.check_output(["git", "check-ignore", "skill.md"], cwd=ROOT).strip() == b"skill.md"
changed = set(subprocess.check_output(["git", "diff", "--name-only", "-z"], cwd=ROOT).decode().split("\0"))
changed.update(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0"))
for name in changed - {""}:
    path = ROOT / name
    if path.is_file():
        raw = path.read_text(encoding="utf-8")
        assert not re.search(r"sk-[A-Za-z0-9_-]{20,}", raw), "Credential in " + name
for name in ("core/data/doubao_tts_voices.json", "core/doubao_tts.py", "core/tts_routes.py", "core/h3_comfy.py", "core/seedance25_flash.py", "web/js/doubao_tts_ui.js", "web/js/h3_comfy_ui.js"):
    assert (ROOT / name).is_file(), name
print(f"PASS {unchanged} unchanged legacy classes, {len(workflows)} blank-key workflows and 169 node registrations")
