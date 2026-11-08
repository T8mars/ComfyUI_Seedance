import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { setSeedanceInputVisible, setSeedanceWidgetVisible } from "../web/js/dynamic_widget_ui.js";

let extension;
let id = 0;
const frames = new Map();
const source = fs.readFileSync(new URL("../web/js/kling_v4_ui.js", import.meta.url), "utf8");
const context = vm.createContext({
    app: { registerExtension(value) { extension = value; } },
    originalSeedanceNodeName: (name) => name.replace(/^SeedanceConcurrent_/, "").replace(/_Submit$/, ""),
    setSeedanceInputVisible, setSeedanceWidgetVisible, resizeSeedanceNode: () => {},
    requestAnimationFrame(callback) { frames.set(++id, callback); return id; },
    cancelAnimationFrame(frame) { frames.delete(frame); },
});
vm.runInContext(source.replace(/^import[\s\S]*?;\r?\n/gm, ""), context);
function flush() { for (const [key, callback] of [...frames]) { frames.delete(key); callback(); } }

for (const name of ["Kling_V4_Custom_Element", "Kling_V4_Custom_Voice", "Kling_V4_Omni", "SeedanceConcurrent_Kling_V4_Omni_Submit",
    "Zhenzhen_Video_G_Omni_1_2_Flash_Lowprice", "SeedanceConcurrent_Zhenzhen_Video_G_Omni_1_2_Flash_Lowprice_Submit"]) {
    class Node {
        constructor() {
            this.widgets = ["reference_type", "source_mode", "video_url", "video_urls", "audio_url", "video_id", "model", "resolution", "ratio", "seconds",
                "watermark", "image_element_ids", "video_element_ids", "voice_ids"].map((name) => ({
                name, value: name === "reference_type" ? "image_refer" : name === "source_mode" ? "audio" : "preserve",
                type: "string", options: {}, computeSize: () => [460, 20], callback() {},
            }));
            for (const [field, value] of Object.entries({ model: "kling-v4-omni", resolution: "1080p", ratio: "adaptive", seconds: 30, video_urls: "" }))
                this.widgets.find((item) => item.name === field).value = value;
            this.inputs = [...Array.from({ length: 10 }, (_, i) => ({ name: `image${i + 1}`, link: null })),
                ...Array.from({ length: 5 }, (_, i) => ({ name: `video${i + 1}`, link: null })),
                { name: "input_video", link: null }, { name: "audio", link: null }, { name: "api_config", link: null }];
        }
    }
    await extension.beforeRegisterNodeDef(Node, { name });
    const node = new Node();
    node.onNodeCreated(); flush();
    const widget = (name) => node.widgets.find((item) => item.name === name);
    const input = (name) => node.inputs.find((item) => item.name === name);
    const change = (name, value) => { widget(name).value = value; widget(name).callback(); flush(); };
    if (name.includes("Element")) {
        assert.ok(!input("image1").hidden && !input("image2").hidden && input("image3").hidden);
        assert.ok(input("input_video").hidden);
        change("reference_type", "video_refer");
        assert.ok(input("image1").hidden && !input("input_video").hidden);
        assert.equal(widget("video_url").type, "string");
        change("reference_type", "image_refer");
        input("image2").link = 2;
        node.onConnectionsChange(); flush();
        assert.ok(!input("image3").hidden);
        widget("video_url").type = "converted-widget";
        change("reference_type", "video_refer");
        assert.equal(widget("video_url").type, "converted-widget");
        assert.equal(widget("video_url").value, "preserve");
        assert.ok(!input("image2").hidden);
    } else if (name.includes("Voice")) {
        assert.ok(!input("audio").hidden);
        assert.ok(widget("video_id").type.startsWith("converted-widget:seedance-hidden"));
        change("source_mode", "video_id");
        assert.ok(input("audio").hidden);
        assert.equal(widget("video_id").type, "string");
        assert.equal(widget("video_id").value, "preserve");
        node.onConfigure(); flush();
    } else if (name.includes("1_2")) {
        assert.ok(!input("image1").hidden && !input("video1").hidden && input("video2").hidden);
        input("image10").link = 1; node.onConnectionsChange(); flush();
        assert.ok(!input("image10").hidden && input("video1").hidden);
        input("image10").link = null; input("video1").link = 2; node.onConnectionsChange(); flush();
        assert.ok(input("image1").hidden && !input("video1").hidden);
        input("video1").link = null;
        change("video_urls", "https://example.com/ref.mp4");
        assert.ok(input("image1").hidden);
        change("video_urls", "");
        assert.ok(!input("image1").hidden);
    } else {
        assert.ok(!input("image1").hidden && input("image2").hidden);
        assert.ok(!input("video1").hidden && input("video2").hidden);
        input("image10").link = 1;
        input("video5").link = 2;
        node.onConnectionsChange(); flush();
        assert.ok(node.inputs.filter((item) => /^image\d+$/.test(item.name)).every((item) => !item.hidden));
        assert.ok(node.inputs.filter((item) => /^video\d+$/.test(item.name)).every((item) => !item.hidden));
        assert.equal(node.inputs.length, 18);
        assert.equal(input("api_config").name, "api_config");
        change("model", "zhenzhen-video-kling-v4-flash");
        assert.equal(widget("resolution").value, "720p");
        assert.equal(widget("ratio").value, "16:9");
        assert.equal(widget("seconds").value, 20);
        assert.ok(widget("voice_ids").type.includes("seedance-hidden"));
        assert.ok(!input("image10").hidden && !input("video5").hidden);
        change("model", "kling-v4-omni");
        assert.equal(widget("voice_ids").type, "string");
        assert.equal(widget("seconds").options.max, 30);
    }
}
console.log("Kling 4 mode controls, progressive sockets, concurrent aliases and linked inputs passed.");
