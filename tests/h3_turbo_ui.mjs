import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { originalSeedanceNodeName } from "../web/js/concurrent_node_ui.js";
import { setSeedanceInputVisible } from "../web/js/dynamic_widget_ui.js";

let extension, id = 0;
const frames = new Map();
const context = vm.createContext({ app: { registerExtension(value) { extension = value; } }, originalSeedanceNodeName,
    setSeedanceInputVisible, resizeSeedanceNode() {}, requestAnimationFrame(callback) { frames.set(++id, callback); return id; },
    cancelAnimationFrame(key) { frames.delete(key); } });
vm.runInContext(fs.readFileSync(new URL("../web/js/h3_turbo_ui.js", import.meta.url), "utf8").replace(/^import[\s\S]*?;\r?\n/gm, ""), context);
function flush() { for (const [key, callback] of [...frames]) { frames.delete(key); callback(); } }
for (const original of ["Minimax_H3_ComfyUI_Max", "Minimax_H3_Image", "Qwen_Image_2_1_Turbo"]) {
    for (const key of [original, `SeedanceConcurrent_${original}_Submit`]) {
        const cap = original.includes("ComfyUI") ? 9 : original.includes("Minimax") ? 16 : 4;
        class Node {
            constructor() {
                this.widgets = [{ name: "resolution", type: "combo", value: "1k", options: {}, callback() {} }];
                this.inputs = Array.from({ length: cap }, (_, i) => ({ name: `image${i+1}`, link: null }));
                if (original.includes("ComfyUI")) this.inputs.push(...Array.from({ length: 3 }, (_, i) => ({ name: `audio${i+1}`, link: null })));
                this.inputs.push({ name: "api_config", link: 50 });
            }
        }
        await extension.beforeRegisterNodeDef(Node, { name: key });
        const node = new Node();
        node.onNodeCreated(); flush();
        assert.ok(!node.inputs[0].hidden && node.inputs[1].hidden);
        const names = node.inputs.map((input) => input.name);
        node.inputs[cap-1].link = 7; node.onConnectionsChange(); flush();
        assert.ok(!node.inputs[cap-1].hidden);
        assert.ok(node.inputs.slice(0, cap).every((input) => !input.hidden));
        if (original === "Qwen_Image_2_1_Turbo") {
            const w = node.widgets[0];
            assert.ok(w.options.values.includes("720p"));
            w.value = "720p";
            node.inputs[cap-1].link = null; node.onConnectionsChange(); flush();
            assert.equal(w.value, "1k");
            assert.ok(!w.options.values.includes("720p"));
            w.type = "converted-widget"; w.origType = "combo"; w.value = "720p";
            node.onConfigure(); flush();
            assert.equal(w.value, "720p");
        }
        node.onConfigure(); node.onAfterGraphConfigured(); flush();
        assert.deepEqual(node.inputs.map((input) => input.name), names);
        assert.equal(node.inputs.at(-1).link, 50);
    }
}
console.log("H3/Turbo serial/concurrent progressive image/audio sockets, Qwen 720p, converted inputs and reload passed.");
