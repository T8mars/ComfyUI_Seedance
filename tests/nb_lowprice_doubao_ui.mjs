import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { setSeedanceWidgetVisible as setWidgetVisible, setSeedanceInputVisible as setInputVisible } from "../web/js/dynamic_widget_ui.js";

const source = fs.readFileSync(new URL("../web/js/nb_lowprice_doubao_ui.js", import.meta.url), "utf8");
assert.ok(source.includes('from "./dynamic_widget_ui.js"'));
let extension;
let next = 0;
const frames = new Map();
const context = vm.createContext({
    app: { registerExtension(value) { extension = value; } },
    originalSeedanceNodeName: (name) => name.replace(/^SeedanceConcurrent_/, "").replace(/_Submit$/, ""),
    setWidgetVisible, setInputVisible, resizeSeedanceNode: () => {},
    requestAnimationFrame(callback) { frames.set(++next, callback); return next; },
    cancelAnimationFrame(id) { frames.delete(id); },
});
vm.runInContext(source.replace(/^import[\s\S]*?;\r?\n/gm, ""), context);
const flush = () => { for (const [key, callback] of [...frames]) { frames.delete(key); callback(); } };
const makeWidget = (name, value) => ({ name, value, type: typeof value === "boolean" ? "toggle" : "combo", options: {}, computeSize: () => [440, 20] });

for (const name of ["Zhenzhen_Image_NB_Lowprice", "SeedanceConcurrent_Zhenzhen_Image_NB_Lowprice_Submit"]) {
    class Node {
        constructor() {
            this.widgets = [makeWidget("model", "zhenzhen-image-nb-pro-lowprice"), makeWidget("size", "1:1")];
            this.inputs = [...Array.from({ length: 14 }, (_, i) => ({ name: `image${i + 1}`, link: null })), { name: "api_config", link: null }];
        }
    }
    await extension.beforeRegisterNodeDef(Node, { name });
    const node = new Node(); node.onNodeCreated(); flush();
    assert.equal(node.widgets[1].options.values.length, 11);
    assert.ok(node.inputs[1].hidden);
    node.widgets[0].value = "zhenzhen-image-nb-2.1-lowprice"; node.widgets[0].callback(); flush();
    assert.ok(node.widgets[1].options.values.includes("8:1"));
    node.widgets[1].value = "8:1";
    node.widgets[0].value = "zhenzhen-image-nb-pro-lowprice"; node.widgets[0].callback(); flush();
    assert.equal(node.widgets[1].value, "1:1");
    node.inputs[13].link = 14; node.onConnectionsChange(); flush();
    assert.ok(node.inputs.slice(0, 14).every((input) => !input.hidden));
    assert.equal(node.inputs.length, 15);
    node.widgets[1].type = "converted-widget"; node.widgets[1].value = "8:1";
    node.onConfigure(); flush();
    assert.equal(node.widgets[1].type, "converted-widget");
    assert.equal(node.widgets[1].value, "8:1");
}

class VoiceNode {
    constructor() {
        this.inputs = [{ name: "reference_audio", link: null }, { name: "api_config", link: null }];
        this.widgets = [makeWidget("model", "doubao-voice-clone"), makeWidget("advanced_mode", false),
            makeWidget("voice_model", "seed-tts-2.0-standard"), ...["audio_url", "speaker", "training_speaker_id", "context_texts", "bit_rate", "enable_subtitle"].map((name) => makeWidget(name, ""))];
    }
}
await extension.beforeRegisterNodeDef(VoiceNode, { name: "Doubao_Voice_Clone_ICL" });
const voice = new VoiceNode(); voice.onNodeCreated(); flush();
const widget = (name) => voice.widgets.find((item) => item.name === name);
const visible = (name) => !widget(name).type.startsWith("converted-widget");
assert.ok(visible("audio_url") && !visible("speaker") && !visible("training_speaker_id"));
widget("advanced_mode").value = true; widget("advanced_mode").callback(); flush();
assert.ok(visible("training_speaker_id") && !visible("bit_rate"));
widget("model").value = "doubao-seed-icl-2.0"; widget("model").callback(); flush();
assert.ok(visible("speaker") && visible("bit_rate") && !visible("audio_url") && !visible("context_texts"));
assert.ok(voice.inputs[0].hidden);
widget("voice_model").value = "api_default"; widget("voice_model").callback(); flush();
assert.ok(visible("context_texts"));
voice.inputs[0].link = 1; voice.onConnectionsChange(); flush();
assert.ok(!voice.inputs[0].hidden);
widget("speaker").type = "converted-widget";
widget("model").value = "doubao-voice-clone"; voice.onConfigure(); flush();
assert.equal(widget("speaker").type, "converted-widget");
assert.equal(voice.inputs.length, 2);
console.log("NB serial/concurrent ratios and 14 slots; Doubao modes, advanced controls and converted widgets passed.");
