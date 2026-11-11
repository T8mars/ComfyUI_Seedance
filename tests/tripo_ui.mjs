import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { setSeedanceInputVisible, setSeedanceWidgetVisible } from "../web/js/dynamic_widget_ui.js";

let extension, id = 0;
const frames = new Map();
const context = vm.createContext({
    app: { registerExtension(value) { extension = value; } },
    setSeedanceInputVisible, setSeedanceWidgetVisible, resizeSeedanceNode() {},
    requestAnimationFrame(callback) { frames.set(++id, callback); return id; },
    cancelAnimationFrame(frame) { frames.delete(frame); },
});
vm.runInContext(fs.readFileSync(new URL("../web/js/tripo_ui.js", import.meta.url), "utf8").replace(/^import[\s\S]*?;\r?\n/gm, ""), context);
function flush() { for (const [key, callback] of [...frames]) { frames.delete(key); callback(); } }
const definitions = {
    Tripo_Generate: ["tripo-h-v3.1-text-to-3d", "prompt", "negative_prompt", "image_seed", "face_limit", "enable_image_autofix", "geometry_quality",
        "smart_low_poly", "generate_parts", "quad", "auto_size", "compress", "texture_quality", "texture_alignment", "orientation", "texture_seed", "input_mode", "multiview_task_id", "texture", "pbr"],
    Tripo_Texture: ["tripo-texture-v3.0", "texture_prompt_mode", "texture_prompt_text", "texture_image_url", "texture_front_image_url", "texture_left_image_url", "texture_back_image_url", "texture_right_image_url", "style_image_url", "compress"],
    Tripo_Retopology: ["tripo-retopology-v2", "bake", "part_names"],
    Tripo_Mesh: ["tripo-mesh-segment-v1", "model_url", "seg_type", "granularity", "hint", "image_url", "transform", "ref_image_url", "segmentation_granularity", "split_by_connectivity", "tripo_segment_task_id", "completion_mode", "part_names"],
    Tripo_Convert: ["tripo-convert", "quad", "force_symmetry", "flatten_bottom", "flatten_bottom_threshold", "export_vertex_colors", "format", "fbx_preset"],
    Tripo_Splat: ["tripo-image-to-splat", "model_seed"],
};
for (const [name, [model, ...fields]] of Object.entries(definitions)) {
    class Node {
        constructor() {
            this.widgets = ["model", ...fields, "seed", "control_after_generate"].map((name) => ({ name, type: "text", value: "api_default", options: {}, callback() {} }));
            this.widgets[0].value = model;
            this.inputs = Array.from({ length: 4 }, (_, i) => ({ name: `image${i+1}`, type: "IMAGE", link: null }));
            this.inputs.push({ name: "style_image", type: "IMAGE", link: null }, { name: "api_config", link: 90 });
        }
    }
    await extension.beforeRegisterNodeDef(Node, { name });
    const node = new Node();
    const w = (name) => node.widgets.find((item) => item.name === name);
    const set = (name, value) => { w(name).value = value; w(name).callback(value); flush(); };
    const visible = (name) => !w(name).type.includes("seedance-hidden");
    node.onNodeCreated(); flush();
    if (name === "Tripo_Generate") {
        assert.ok(visible("prompt") && node.inputs[0].hidden);
        set("model", "tripo-h-v3.1-multiview-to-3d");
        assert.ok(!visible("prompt") && !node.inputs[0].hidden && !node.inputs[1].hidden && node.inputs[2].hidden);
        node.inputs[1].link = 1; node.onConnectionsChange(); flush();
        assert.ok(!node.inputs[2].hidden);
        set("input_mode", "multiviewTaskId");
        assert.ok(visible("multiview_task_id") && node.inputs[0].hidden && !node.inputs[1].hidden);
        set("model", "tripo-h-v2.5-image-to-3d");
        assert.ok(!visible("geometry_quality") && !visible("compress") && !visible("quad"));
        set("model", "tripo-p-p2-text-to-3d");
        set("quad", "true");
        assert.equal(w("face_limit").options.max, 25000);
        set("texture", "false"); set("pbr", "false");
        assert.ok(!visible("texture_quality") && !visible("texture_seed"));
    } else if (name === "Tripo_Texture") {
        set("texture_prompt_mode", "images");
        assert.ok(node.inputs.slice(0, 4).every((input) => !input.hidden));
        assert.ok(visible("texture_front_image_url") && !visible("style_image_url"));
        set("texture_prompt_mode", "text");
        assert.ok(!node.inputs[4].hidden && visible("texture_prompt_text"));
        set("model", "tripo-texture-v2.5"); assert.ok(!visible("compress"));
    } else if (name === "Tripo_Retopology") {
        set("model", "tripo-retopology-v1"); assert.ok(!visible("bake") && !visible("part_names"));
        set("model", "tripo-retopology-v2"); assert.ok(visible("bake"));
    } else if (name === "Tripo_Mesh") {
        set("model", "tripo-mesh-smartsegment"); set("seg_type", "model");
        assert.ok(visible("transform") && visible("model_url") && !visible("image_url"));
        set("seg_type", "image"); assert.ok(!node.inputs[0].hidden && visible("image_url"));
        set("model", "tripo-mesh-segment-v2"); set("ref_image_url", "https://example.com/front.png");
        assert.ok(!visible("segmentation_granularity"));
        set("model", "tripo-mesh-complete"); assert.ok(!visible("model_url") && visible("tripo_segment_task_id"));
    } else if (name === "Tripo_Convert") {
        set("format", "FBX"); assert.ok(visible("fbx_preset") && !visible("export_vertex_colors"));
        set("quad", "true"); assert.ok(visible("force_symmetry"));
        set("flatten_bottom", "true"); assert.ok(visible("flatten_bottom_threshold"));
    } else assert.ok(!node.inputs[0].hidden && node.inputs[1].hidden);
    node.onConfigure(); node.onAfterGraphConfigured(); flush();
    assert.equal(node.inputs.at(-1).link, 90);
    assert.equal(node.inputs.length, 6);
    assert.ok(visible("seed") && visible("control_after_generate"));
}
console.log("Tripo six groups: model/mode visibility, stable links, face limits and reload passed.");
