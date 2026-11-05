import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { setSeedanceInputVisible } from "../web/js/dynamic_widget_ui.js";

let extension;
let id = 0;
const frames = new Map();
const context = vm.createContext({
    app: { registerExtension(value) { extension = value; } },
    setSeedanceInputVisible, resizeSeedanceNode: () => {},
    requestAnimationFrame(callback) { frames.set(++id, callback); return id; },
    cancelAnimationFrame(frame) { frames.delete(frame); },
});
vm.runInContext(fs.readFileSync(new URL("../web/js/hitem_meshy_ui.js", import.meta.url), "utf8")
    .replace(/^import[\s\S]*?;\r?\n/gm, ""), context);
function flush() { for (const [key, callback] of [...frames]) { frames.delete(key); callback(); } }

for (const name of ["Hitem3D_V2", "Hitem3D_Portrait_V2_1", "Meshy_6_Global"]) {
    class Node {
        constructor() {
            this.widgets = [{ name: "model", value: "hitem3d-v2-image-to-3d", callback() {} }];
            this.inputs = [...Array.from({ length: name.startsWith("Meshy") ? 1 : 4 }, (_, i) => ({ name: `image${i + 1}`, link: null })),
                { name: "api_config", link: null }];
        }
    }
    await extension.beforeRegisterNodeDef(Node, { name });
    const node = new Node();
    node.onNodeCreated(); flush();
    assert.ok(!node.inputs[0].hidden);
    if (!name.startsWith("Meshy")) {
        assert.ok(node.inputs[1].hidden);
        node.widgets[0].value = "hitem3d-v2-multi-image-to-3d";
        node.widgets[0].callback(); flush();
        assert.ok(!node.inputs[1].hidden && node.inputs[2].hidden);
        node.inputs[1].link = 1;
        node.onConnectionsChange(); flush();
        assert.ok(!node.inputs[2].hidden && node.inputs[3].hidden);
        node.inputs[2].link = 2;
        node.onConnectionsChange(); flush();
        assert.ok(!node.inputs[3].hidden);
        node.widgets[0].value = "hitem3d-v2-image-to-3d";
        node.widgets[0].callback(); flush();
        assert.ok(!node.inputs[1].hidden && !node.inputs[2].hidden);
        assert.equal(node.inputs.length, 5);
    }
    node.onConfigure(); flush();
    assert.equal(node.inputs.at(-1).name, "api_config");
}
console.log("Hitem/Meshy single/multi views, stable sockets, reload and existing links passed.");
