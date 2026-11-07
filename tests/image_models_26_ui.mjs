import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { originalSeedanceNodeName } from "../web/js/concurrent_node_ui.js";
import { setSeedanceInputVisible, setSeedanceWidgetVisible } from "../web/js/dynamic_widget_ui.js";

let extension;
let serial = 0;
const frames = new Map();
const app = { nodeOutputs: {}, registerExtension(value) { extension = value; } };
const context = vm.createContext({
    app, api: { apiURL: (value) => value }, originalSeedanceNodeName,
    setSeedanceInputVisible, setSeedanceWidgetVisible, resizeSeedanceNode: () => {}, URLSearchParams,
    requestAnimationFrame(callback) { frames.set(++serial, callback); return serial; },
    cancelAnimationFrame(id) { frames.delete(id); },
    document: { createElement() { return { style: {}, children: [], append(...items) { this.children.push(...items); },
        replaceChildren() { this.children = []; } }; } },
});
const load = (filename) => vm.runInContext("(() => {\n" + fs.readFileSync(new URL(filename, import.meta.url), "utf8")
    .replace(/^import[\s\S]*?;\r?\n/gm, "") + "\n})()", context);
const flush = () => { for (const [id, callback] of [...frames]) { frames.delete(id); callback(); } };

load("../web/js/image_models_26_ui.js");
for (const name of ["Zhenzhen_Image_G26", "SeedanceConcurrent_Zhenzhen_Image_G26_Submit", "Krea_V3_Image"]) {
    class Node {
        constructor() {
            const values = { model: name.includes("Krea") ? "krea-v3-t2i" : "zhenzhen-image-g-v2.6-lowprice", mode: "image",
                size: "1:1", frame_size: "512x512", output_format: "png" };
            this.widgets = ["model", "mode", "size", "width", "height", "resolution", "quality", "complexity", "n", "output_format",
                "output_compression", "frame_size", "frame_width", "frame_height", "frame_count", "frame_duration_ms", "mask_url", "markup_url"]
                .map((field) => ({ name: field, type: "combo", value: values[field] ?? 0, options: {}, callback() {} }));
            this.inputs = Array.from({ length: name.includes("Krea") ? 8 : 16 }, (_, i) => ({ name: `image${i + 1}`, link: null }));
        }
    }
    await extension.beforeRegisterNodeDef(Node, { name });
    const node = new Node(); node.onNodeCreated(); flush();
    const widget = (field) => node.widgets.find((item) => item.name === field);
    const change = (field, value) => { widget(field).value = value; widget(field).callback(); flush(); };
    const hidden = (field) => widget(field).type.includes("seedance-hidden");
    if (name.includes("Krea")) {
        assert.ok(node.inputs[0].hidden);
        change("model", "krea-v3-i2i");
        assert.ok(!node.inputs[0].hidden);
        change("size", "custom"); assert.ok(!hidden("width"));
    } else {
        assert.ok(hidden("resolution") && hidden("frame_count"));
        for (let i = 0; i < 9; i++) node.inputs[i].link = i + 1;
        node.onConnectionsChange(); flush();
        assert.equal(node.inputs[9].hidden, false);
        assert.equal(node.inputs[10].hidden, true);
        node.inputs[9].link = 10;
        change("mode", "gif");
        assert.equal(node.inputs[9].hidden, false);
        assert.equal(node.inputs[10].hidden, true);
        node.inputs[10].link = 11;
        node.onConnectionsChange(); flush();
        assert.equal(node.inputs[10].hidden, false, "Preserve an existing out-of-range link for validation");
        for (const input of node.inputs) input.link = null;
        node.onConnectionsChange(); flush();
        change("mode", "gif"); assert.ok(hidden("frame_count"));
        change("model", "zhenzhen-image-g-v2.6-flare");
        assert.ok(!hidden("frame_count") && hidden("size") && node.inputs[0].hidden);
        change("frame_size", "custom"); assert.ok(!hidden("frame_width"));
        change("mode", "image"); change("size", "custom");
        assert.ok(!hidden("width") && hidden("resolution"));
        node.inputs[1].link = 1;
        change("mode", "gif"); assert.ok(!node.inputs[1].hidden);
        change("model", "zhenzhen-image-g-v2.6-lowprice");
        assert.equal(widget("size").value, "1:1");
        assert.ok(hidden("quality") && hidden("frame_count"));
    }
    node.onConfigure(); flush();
}

load("../web/js/gif_preview.js");
for (const comfyClass of ["Zhenzhen_Image_G26", "SeedanceConcurrent_Image_Await", "Seedance_Save_GIF"]) {
    const node = { id: ++serial, comfyClass,
        widgets: comfyClass === "Seedance_Save_GIF" ? ["source_mode", "fps", "loop"].map((name) => ({ name, type: "combo", value: name === "source_mode" ? "auto" : 0 })) : [],
        inputs: [{ name: "source_path", link: null }], size: [500, 600], graph: { setDirtyCanvas() {} },
        onExecuted(message) { this.nativeMessage = message; },
        addDOMWidget(name, type, container, options) { const widget = { name, type, options }; this.widgets.push(widget); return widget; },
        setSize(size) { this.size = size; }, computeSize() { return [500, 900]; } };
    await extension.nodeCreated(node);
    flush();
    if (comfyClass === "Seedance_Save_GIF") {
        node.inputs[0].link = 1;
        node.onConnectionsChange(); flush();
        assert.ok(node.widgets.find((widget) => widget.name === "fps").type.includes("seedance-hidden"));
        const selector = node.widgets.find((widget) => widget.name === "source_mode");
        selector.value = "frames"; selector.callback(); flush();
        assert.equal(node.widgets.find((widget) => widget.name === "fps").type, "combo");
    }
    const gif = { filename: "test.gif", subfolder: "nested", type: "output" };
    node.onExecuted({ images: [gif], animated: [true] });
    assert.equal(node.previewMediaType, "image");
    assert.equal(node.nativeMessage.images.length, 0);
    assert.equal(node.seedanceGifWidget.serialize, false);
    assert.equal(node.seedanceGifContainer.children.length, 1);
    const [image, save] = node.seedanceGifContainer.children[0].children;
    assert.ok(image.src.startsWith("/view?"));
    assert.ok(!image.src.includes("preview="));
    assert.equal(save.download, "test.gif");
    node.onConfigure(); flush();
    assert.equal(node.seedanceGifContainer.children.length, 1);
    node.onExecuted({ images: [{ filename: "static.png", type: "output" }] });
    assert.equal(node.seedanceGifContainer.children.length, 0);
    assert.equal(node.seedanceGifContainer.style.display, "none");
    assert.equal(node.nativeMessage.images[0].filename, "static.png");
}
console.log("G 2.6/Krea dynamic controls, converted links, GIF playback widgets, cache restoration and static previews passed.");
