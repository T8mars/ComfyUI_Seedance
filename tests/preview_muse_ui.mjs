import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { setSeedanceInputVisible, setSeedanceWidgetVisible } from "../web/js/dynamic_widget_ui.js";

let extension;
let id = 0;
const frames = new Map();
const context = vm.createContext({
    app: { registerExtension(value) { extension = value; } },
    originalSeedanceNodeName: (name) => name.replace(/^SeedanceConcurrent_/, "").replace(/_Submit$/, ""),
    setSeedanceInputVisible, setSeedanceWidgetVisible, resizeSeedanceNode: () => {},
    requestAnimationFrame(callback) { frames.set(++id, callback); return id; },
    cancelAnimationFrame(frame) { frames.delete(frame); },
});
vm.runInContext(fs.readFileSync(new URL("../web/js/preview_muse_flux_ui.js", import.meta.url), "utf8")
    .replace(/^import[\s\S]*?;\r?\n/gm, ""), context);
function flush() { for (const [key, callback] of [...frames]) { frames.delete(key); callback(); } }

for (const base of ["HY_Image_3_5_Preview", "Muse_Image", "Muse_Video", "Flux_3_Image_Variants"]) {
    for (const name of [base, `SeedanceConcurrent_${base}_Submit`]) {
        class Node {
            constructor() {
                this.widgets = ["model", "size", "resolution", "width", "height", "grounding", "safety_tolerance", "steps", "output_format", "seed"].map((name) => ({
                    name, value: name === "model" ? "flux-3-image-t2i" : name === "size" ? "auto" : "preserve",
                    type: "combo", options: {}, computeSize: () => [460, 20], callback() {},
                }));
                const maximum = base.startsWith("HY") ? 5 : base.startsWith("Flux") ? 10 : 9;
                this.inputs = [...Array.from({ length: maximum }, (_, i) => ({ name: `image${i + 1}`, link: null })),
                    { name: "api_config", link: null }];
            }
        }
        await extension.beforeRegisterNodeDef(Node, { name });
        const node = new Node();
        node.onNodeCreated(); flush();
        const widget = (name) => node.widgets.find((item) => item.name === name);
        const change = (name, value) => { widget(name).value = value; widget(name).callback(); flush(); };
        const hidden = (name) => widget(name).type.startsWith("converted-widget:seedance-hidden");
        const count = node.inputs.length;
        if (base.startsWith("Flux")) {
            assert.ok(node.inputs[0].hidden);
            assert.ok(hidden("steps") && hidden("output_format") && !hidden("grounding"));
            change("model", "flux-3-image-klein-i2i");
            assert.ok(!node.inputs[0].hidden && node.inputs[1].hidden);
            assert.ok(!hidden("steps") && !hidden("output_format") && hidden("grounding"));
            node.inputs[1].link = 1;
            node.onConnectionsChange(); flush();
            assert.ok(!node.inputs[2].hidden);
            change("model", "flux-3-image-t2i");
            assert.ok(!node.inputs[1].hidden); // Never hide an existing link.
            assert.equal(widget("seed").value, "preserve");
        } else {
            assert.ok(!node.inputs[0].hidden && node.inputs[1].hidden);
            if (base.startsWith("HY")) {
                assert.ok(hidden("width") && hidden("height"));
                change("size", "custom");
                assert.ok(!hidden("width") && !hidden("height") && hidden("resolution"));
                widget("width").type = "converted-widget";
                change("size", "auto");
                assert.equal(widget("width").type, "converted-widget");
                assert.ok(!hidden("resolution"));
            }
        }
        node.onConfigure(); flush();
        assert.equal(node.inputs.length, count);
        assert.equal(node.inputs.at(-1).name, "api_config");
    }
}
console.log("Preview/Muse/FLUX controls, reference sockets, concurrent aliases and converted links passed.");
