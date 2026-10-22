import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import {
    resizeSeedanceNode,
    setSeedanceInputVisible as setInputVisible,
    setSeedanceWidgetVisible as setWidgetVisible,
} from "./dynamic_widget_ui.js";

const NB_NODE = "Zhenzhen_Image_NB_Lowprice";
const VOICE_NODE = "Doubao_Voice_Clone_ICL";
const STANDARD_SIZES = ["auto", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"];
const CLONE_FIELDS = new Set([
    "audio_url", "custom_speaker_id", "language", "reference_text",
    "enable_audio_denoise", "disable_volume_normalization",
]);
const SYNTH_FIELDS = new Set([
    "speaker", "voice_model", "output_format", "sample_rate", "speech_rate",
    "loudness_rate", "pitch", "explicit_language",
]);
const ADVANCED_SYNTH_FIELDS = new Set([
    "bit_rate", "max_length_to_filter_parenthesis", "silence_duration", "enable_subtitle",
    "disable_markdown_filter", "disable_emoji_filter", "enable_latex_tn", "aigc_watermark",
    "disable_default_bit_rate", "tone_fidelity", "aigc_metadata_enable", "latex_parser",
    "section_id", "aigc_metadata_content_producer", "aigc_metadata_produce_id",
    "aigc_metadata_content_propagator", "aigc_metadata_propagate_id",
]);

function refresh(node, name) {
    const widget = (key) => node.widgets?.find((item) => item.name === key);
    if (name === NB_NODE) {
        const sizes = widget("model")?.value === "zhenzhen-image-nb-2.1-lowprice"
            ? [...STANDARD_SIZES, "1:4", "4:1", "1:8", "8:1"] : STANDARD_SIZES;
        const size = widget("size");
        if (size && !String(size.type).startsWith("converted-widget")) {
            size.options ??= {};
            size.options.values = [...sizes];
            if (!sizes.includes(size.value)) size.value = "1:1";
        }
        const last = Math.max(0, ...(node.inputs ?? []).filter((input) => /^image\d+$/.test(input.name) && input.link != null)
            .map((input) => Number(input.name.slice(5))));
        for (const input of node.inputs ?? []) {
            if (/^image\d+$/.test(input.name)) setInputVisible(node, input, Number(input.name.slice(5)) <= last + 1);
        }
    } else {
        const clone = widget("model")?.value !== "doubao-seed-icl-2.0";
        const advanced = Boolean(widget("advanced_mode")?.value);
        for (const field of CLONE_FIELDS) setWidgetVisible(widget(field), clone);
        for (const field of SYNTH_FIELDS) setWidgetVisible(widget(field), !clone);
        for (const field of ADVANCED_SYNTH_FIELDS) setWidgetVisible(widget(field), !clone && advanced);
        setWidgetVisible(widget("training_speaker_id"), clone && advanced);
        setWidgetVisible(widget("context_texts"), !clone && widget("voice_model")?.value === "api_default");
        for (const input of node.inputs ?? []) {
            if (input.name === "reference_audio") setInputVisible(node, input, clone);
        }
    }
    resizeSeedanceNode(node, name === NB_NODE ? 440 : 480);
}

function schedule(node, name) {
    if (node.seedanceNBDoubaoFrame != null) cancelAnimationFrame(node.seedanceNBDoubaoFrame);
    node.seedanceNBDoubaoFrame = requestAnimationFrame(() => {
        node.seedanceNBDoubaoFrame = null;
        refresh(node, name);
    });
}

function install(node, name) {
    if (node.seedanceNBDoubaoInstalled) return;
    node.seedanceNBDoubaoInstalled = true;
    for (const key of ["model", "advanced_mode", "voice_model"]) {
        const widget = node.widgets?.find((item) => item.name === key);
        if (!widget) continue;
        const callback = widget.callback;
        widget.callback = (...args) => {
            const result = callback?.apply(widget, args);
            schedule(node, name);
            return result;
        };
    }
    schedule(node, name);
}

app.registerExtension({
    name: "ComfyUI_Seedance.NBLowpriceDoubaoUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const name = originalSeedanceNodeName(nodeData.name);
        if (![NB_NODE, VOICE_NODE].includes(name)) return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            install(this, name);
            return result;
        };
        for (const key of ["onConfigure", "onConnectionsChange", "onAfterGraphConfigured"]) {
            const original = nodeType.prototype[key];
            nodeType.prototype[key] = function () {
                const result = original?.apply(this, arguments);
                schedule(this, name);
                return result;
            };
        }
    },
    async nodeCreated(node) {
        const name = originalSeedanceNodeName(node.comfyClass ?? node.constructor?.comfyClass
            ?? node.constructor?.nodeData?.name ?? node.type ?? "");
        if ([NB_NODE, VOICE_NODE].includes(name)) install(node, name);
    },
});
