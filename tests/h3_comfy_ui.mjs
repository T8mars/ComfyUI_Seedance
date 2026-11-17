import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { originalSeedanceNodeName } from "../web/js/concurrent_node_ui.js";
import * as helpers from "../web/js/dynamic_widget_ui.js";

let extension, id = 0;
const frames = new Map();
const context = vm.createContext({ ...helpers, originalSeedanceNodeName, resizeSeedanceNode() {},
    app: { registerExtension(value) { extension = value; } },
    requestAnimationFrame(callback) { frames.set(++id, callback); return id; }, cancelAnimationFrame(key) { frames.delete(key); } });
vm.runInContext(fs.readFileSync(new URL("../web/js/h3_comfy_ui.js", import.meta.url), "utf8").replace(/^import[\s\S]*?;\r?\n/gm, ""), context);
const flush = () => { for (const [key, callback] of [...frames]) { frames.delete(key); callback(); } };
const profiles = [
    ["Minimax_H3_ComfyUI_CharSwap", { image: 9, video: 1 }],
    ["Minimax_H3_ComfyUI_Wuxi", { image: 9, video: 3, audio: 3 }],
    ["Minimax_H3_ComfyUI_Max_10020", { image: 6, audio: 3 }],
    ["Minimax_H3_ComfyUI_Max_10021", { image: 9, audio: 3 }],
];
for (const [original, caps] of profiles) for (const name of [original, `SeedanceConcurrent_${original}_Submit`]) {
    class Node {
        constructor() {
            this.widgets = Object.entries({ duration_mode: "seconds", seconds: "5", frames: 124, resolution: "768p", ratio: "auto" }).map(([name, value]) => ({ name, value, type: "combo", options: {}, callback() {} }));
            this.inputs = Object.entries(caps).flatMap(([family, cap]) => Array.from({ length: cap }, (_, index) => ({ name: family + (index + 1), link: null,
                hidden: true, pos: [-100000, -100000], widget: { name: "__seedance_hidden_input__" } })));
            this.inputs.push({ name: "api_config", link: 500 });
        }
    }
    await extension.beforeRegisterNodeDef(Node, { name });
    const node = new Node(); node.onNodeCreated(); flush();
    const names = node.inputs.map((input) => input.name), widget = (name) => node.widgets.find((item) => item.name === name);
    for (const [family, cap] of Object.entries(caps)) {
        for (let index = 1; index <= cap; index++) {
            const input = node.inputs.find((input) => input.name === family + index);
            assert.equal(input.hidden, false, name + ": next reference must be visible");
            assert.notEqual(input.pos?.[0], -100000);
            input.link = index; node.onConnectionsChange(); flush();
        }
    }
    if (original.endsWith("CharSwap")) {
        widget("duration_mode").value = "frames"; widget("duration_mode").callback(); flush();
        assert.ok(widget("seconds").type.includes("seedance-hidden"));
        assert.equal(widget("frames").type, "combo");
        widget("ratio").value = "21:9"; widget("resolution").value = "480p"; widget("resolution").callback(); flush();
        assert.equal(widget("ratio").value, "auto");
        widget("ratio").origType = "combo"; widget("ratio").value = "21:9"; node.onConfigure(); flush();
        assert.equal(widget("ratio").value, "21:9", "Converted values must be validated, not overwritten");
    }
    node.onConfigure(); node.onAfterGraphConfigured(); flush();
    assert.deepEqual(node.inputs.map((input) => input.name), names);
    assert.equal(node.inputs.at(-1).link, 500);
}
console.log("PASS four H3 profiles in serial/concurrent nodes: full progressive references, legacy state, frames, ratios and converted inputs");
