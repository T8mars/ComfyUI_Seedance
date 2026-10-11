import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { setSeedanceWidgetVisible as setWidgetVisible } from "../web/js/dynamic_widget_ui.js";

const source = fs.readFileSync(new URL("../web/js/mai_image_ui.js", import.meta.url), "utf8");
assert.ok(source.includes('from "./dynamic_widget_ui.js"'));
let extension;
const frames = new Map();
let id = 0;
const context = vm.createContext({
    app: { registerExtension(value) { extension = value; } },
    originalSeedanceNodeName: (name) => name.replace(/^SeedanceConcurrent_/, "").replace(/_Submit$/, ""),
    resizeSeedanceNode: () => {}, setWidgetVisible,
    requestAnimationFrame(callback) { frames.set(++id, callback); return id; },
    cancelAnimationFrame(frame) { frames.delete(frame); },
});
vm.runInContext(source.replace(/^import[\s\S]*?;\r?\n/gm, ""), context);
function flush() { for (const [key, callback] of [...frames]) { frames.delete(key); callback(); } }

for (const name of ["MAI_Image_2_6", "SeedanceConcurrent_MAI_Image_2_6_Submit"]) {
    class Node {
        constructor() {
            this.inputs = Array.from({ length: 6 }, (_, index) => ({ name: index < 5 ? `image${index + 1}` : "api_config", link: null }));
            this.widgets = ["size", "resolution", "custom_ratio", "width", "height", "auto_aspect_ratio", "web_grounding"].map((name) => ({
                name, type: name === "auto_aspect_ratio" ? "toggle" : "string", value: name === "size" ? "1:1" : false,
                computeSize: () => [440, 20], options: {}, callback() {},
            }));
        }
    }
    await extension.beforeRegisterNodeDef(Node, { name });
    const node = new Node();
    node.onNodeCreated(); flush();
    const widget = (name) => node.widgets.find((item) => item.name === name);
    const visible = (name) => !widget(name).type.startsWith("converted-widget");
    const change = (name, value) => { widget(name).value = value; widget(name).callback(value); flush(); };
    assert.ok(visible("size") && visible("resolution") && !visible("width"));
    change("size", "custom_ratio");
    assert.ok(visible("custom_ratio") && !visible("width"));
    change("size", "custom_pixels");
    assert.ok(visible("width") && visible("height") && !visible("resolution") && !visible("custom_ratio"));
    change("auto_aspect_ratio", true);
    assert.ok(!visible("size") && !visible("width") && visible("resolution"));
    node.inputs[4].link = 5; node.onConnectionsChange(); flush();
    assert.ok(!visible("resolution") && !visible("auto_aspect_ratio") && visible("web_grounding"));
    node.inputs[4].link = null; node.onConfigure(); flush();
    assert.ok(visible("resolution"));
    change("auto_aspect_ratio", false);
    assert.ok(visible("width") && !visible("resolution"));
    assert.equal(node.inputs.length, 6);
    assert.equal(node.inputs[5].name, "api_config");
    widget("custom_ratio").type = "converted-widget";
    change("size", "custom_ratio");
    assert.equal(widget("custom_ratio").type, "converted-widget");
}
console.log("MAI serial/concurrent sizing, linked references and converted controls passed.");
