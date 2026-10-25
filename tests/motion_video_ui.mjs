import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { setSeedanceWidgetVisible } from "../web/js/dynamic_widget_ui.js";

const source = fs.readFileSync(new URL("../web/js/motion_video_ui.js", import.meta.url), "utf8");
let extension;
const frames = new Map();
let id = 0;
const context = vm.createContext({
    app: { registerExtension(value) { extension = value; } },
    originalSeedanceNodeName: (name) => name.replace(/^SeedanceConcurrent_/, "").replace(/_Submit$/, ""),
    resizeSeedanceNode: () => {}, setSeedanceWidgetVisible,
    requestAnimationFrame(callback) { frames.set(++id, callback); return id; },
    cancelAnimationFrame(frame) { frames.delete(frame); },
});
vm.runInContext(source.replace(/^import[\s\S]*?;\r?\n/gm, ""), context);
function flush() { for (const [key, callback] of [...frames]) { frames.delete(key); callback(); } }

for (const name of ["Zhenzhen_Motion_Video", "SeedanceConcurrent_Zhenzhen_Motion_Video_Submit"]) {
    class Node {
        constructor() {
            this.widgets = ["operation", "revise_from", "revision_instruction"].map((name) => ({
                name, type: "string", value: name === "operation" ? "generate" : "keep me",
                computeSize: () => [460, 20], callback() {}, options: {},
            }));
        }
    }
    await extension.beforeRegisterNodeDef(Node, { name });
    const node = new Node();
    node.onNodeCreated(); flush();
    const widget = (name) => node.widgets.find((item) => item.name === name);
    const visible = (name) => !widget(name).type.startsWith("converted-widget");
    assert.ok(!visible("revise_from") && !visible("revision_instruction"));
    assert.deepEqual(widget("revise_from").computeSize(), [0, -4]);
    widget("operation").value = "revise";
    widget("operation").callback(); flush();
    assert.ok(visible("revise_from") && visible("revision_instruction"));
    assert.equal(widget("revise_from").value, "keep me");
    widget("revise_from").type = "converted-widget";
    widget("operation").value = "generate";
    node.onConfigure(); flush();
    assert.equal(widget("revise_from").type, "converted-widget");
    node.onAfterGraphConfigured(); flush();
    assert.equal(widget("revise_from").value, "keep me");
}
console.log("Motion serial/concurrent revision controls and converted widgets passed.");
