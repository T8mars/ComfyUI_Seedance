import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { originalSeedanceNodeName } from "../web/js/concurrent_node_ui.js";
import { setSeedanceInputVisible, setSeedanceWidgetVisible } from "../web/js/dynamic_widget_ui.js";

let extension, id = 0;
const frames = new Map();
const context = vm.createContext({ app: { registerExtension(value) { extension = value; } }, originalSeedanceNodeName,
    setSeedanceInputVisible, setSeedanceWidgetVisible, resizeSeedanceNode() {},
    requestAnimationFrame(callback) { frames.set(++id, callback); return id; }, cancelAnimationFrame(frame) { frames.delete(frame); } });
vm.runInContext(fs.readFileSync(new URL("../web/js/seedream55_ui.js", import.meta.url), "utf8").replace(/^import[\s\S]*?;\r?\n/gm, ""), context);
function flush() { for (const [key, callback] of [...frames]) { frames.delete(key); callback(); } }
for (const key of ["Seedream_5_5_Image", "SeedanceConcurrent_Seedream_5_5_Image_Submit", "Seedance_2_5_Video", "SeedanceConcurrent_Seedance_2_5_Video_Submit"]) {
    class Node {
        constructor() {
            this.widgets = ["model", "resolution", "width", "height", "background", "output_format", "draft"].map((name) => ({ name, type: "text", value: "", callback() {} }));
            this.inputs = Array.from({ length: 10 }, (_, i) => ({ name: `image${i+1}`, link: null }));
            this.inputs.push({ name: "api_config", link: 50 });
        }
    }
    await extension.beforeRegisterNodeDef(Node, { name: key });
    const node = new Node();
    const w = (name) => node.widgets.find((item) => item.name === name);
    const set = (name, value) => { w(name).value = value; w(name).callback(value); flush(); };
    node.onNodeCreated(); flush();
    if (key.includes("Seedream")) {
        set("model", "seedream-v5.5-t2i"); assert.ok(node.inputs[0].hidden);
        for (const model of ["seedream-v5.5-i2i", "dola-seedream-5.5-i2i"]) {
            set("model", model);
            assert.ok(node.inputs.slice(0, 10).every((input) => !input.hidden), "Editing exposes all ten references without a connection callback");
        }
        for (let index = 0; index < 10; index++) {
            node.inputs[index].link = index + 1; node.onConnectionsChange(); flush();
            assert.ok(node.inputs.slice(0, 10).every((input) => !input.hidden));
        }
        node.onConfigure(); node.onAfterGraphConfigured(); flush();
        assert.ok(node.inputs.slice(0, 10).every((input) => !input.hidden));
        set("model", "seedream-v5.5-t2i");
        assert.ok(node.inputs.slice(0, 10).every((input) => !input.hidden), "Existing connections remain visible in text mode for validation");
        for (let index = 1; index < 10; index++) node.inputs[index].link = null;
        node.onConnectionsChange(); flush();
        assert.ok(!node.inputs[0].hidden && node.inputs.slice(1, 10).every((input) => input.hidden));
        set("model", "dola-seedream-5.5-i2i");
        assert.ok(node.inputs.slice(0, 10).every((input) => !input.hidden));
        set("resolution", "custom"); assert.equal(w("width").type, "text");
        set("resolution", "1k"); assert.ok(w("width").type.includes("seedance-hidden"));
        set("output_format", "jpeg"); set("background", "transparent"); assert.equal(w("output_format").value, "png");
        w("output_format").type = "converted-widget"; w("output_format").origType = "text";
        w("output_format").value = "jpeg"; set("background", "transparent"); assert.equal(w("output_format").value, "jpeg");
    } else {
        set("draft", true); assert.ok(w("resolution").type.includes("seedance-hidden"));
        set("draft", false); assert.equal(w("resolution").type, "text");
    }
    node.onConfigure(); node.onAfterGraphConfigured(); flush();
    assert.equal(node.inputs.at(-1).link, 50);
    assert.equal(node.inputs.length, 11);
}
console.log("Seedream 5.5 serial/concurrent references, alpha format guard, converted inputs, draft toggles and reload passed.");
