import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import {
    resizeSeedanceNode,
    setSeedanceInputVisible,
    setSeedanceWidgetVisible,
} from "./dynamic_widget_ui.js";

const OMNI12 = "Zhenzhen_Video_G_Omni_1_2_Flash_Lowprice";
const NAMES = new Set(["Kling_V4_Custom_Element", "Kling_V4_Custom_Voice", "Kling_V4_T2V", "Kling_V4_I2V", "Kling_V4_Omni", OMNI12]);
const INSTALLED = Symbol("seedanceKling4Installed");

function progressive(node, prefix, max, minimum = 1) {
    let highest = minimum - 1;
    for (const input of node.inputs ?? []) {
        if (input.name.startsWith(prefix) && input.link != null) {
            const index = Number(input.name.slice(prefix.length));
            if (Number.isInteger(index)) highest = Math.max(highest, index);
        }
    }
    const visible = Math.min(max, Math.max(minimum, highest + 1));
    for (const input of node.inputs ?? []) {
        if (new RegExp(`^${prefix}[1-9][0-9]*$`).test(input.name)) {
            setSeedanceInputVisible(node, input, Number(input.name.slice(prefix.length)) <= visible);
        }
    }
}

function refresh(node) {
    const name = node.seedanceKling4Name;
    const widget = (name) => node.widgets?.find((item) => item.name === name);
    if (name === "Kling_V4_Custom_Element") {
        const video = widget("reference_type")?.value === "video_refer";
        for (const input of node.inputs ?? []) {
            if (/^image[1-4]$/.test(input.name)) setSeedanceInputVisible(node, input, !video);
            if (input.name === "input_video") setSeedanceInputVisible(node, input, video);
        }
        setSeedanceWidgetVisible(widget("video_url"), video);
        if (!video) progressive(node, "image", 4, 2);
    }
    if (name === "Kling_V4_Custom_Voice") {
        const audio = widget("source_mode")?.value !== "video_id";
        setSeedanceWidgetVisible(widget("audio_url"), audio);
        setSeedanceWidgetVisible(widget("video_id"), !audio);
        for (const input of node.inputs ?? []) {
            if (input.name === "audio") setSeedanceInputVisible(node, input, audio);
        }
    }
    if (name === "Kling_V4_Omni" || name === OMNI12) {
        const flash = name === OMNI12 || widget("model")?.value === "zhenzhen-video-kling-v4-flash";
        const imageLinked = node.inputs?.some((input) => /^image\d+$/.test(input.name) && input.link != null);
        const videoLinked = node.inputs?.some((input) => /^video\d+$/.test(input.name) && input.link != null)
            || String(widget("video_urls")?.value ?? "").trim().length > 0;
        progressive(node, "image", flash && videoLinked ? 0 : 10);
        progressive(node, "video", flash && imageLinked ? 0 : name === OMNI12 ? 1 : 5);
        if (name === "Kling_V4_Omni") {
            for (const field of ["watermark", "image_element_ids", "video_element_ids", "voice_ids"]) setSeedanceWidgetVisible(widget(field), !flash);
            const resolution = widget("resolution");
            if (resolution?.options) resolution.options.values = flash ? ["720p"] : ["720p", "1080p"];
            if (flash && resolution?.value !== "720p" && !node.inputs?.some((input) => input.name === "resolution" && input.link != null)) resolution.value = "720p";
            const ratio = widget("ratio");
            if (ratio?.options) ratio.options.values = flash ? ["21:9", "16:9", "1:1", "9:16"] : ["21:9", "16:9", "1:1", "9:16", "adaptive"];
            if (flash && ratio?.value === "adaptive" && !node.inputs?.some((input) => input.name === "ratio" && input.link != null)) ratio.value = "16:9";
            const seconds = widget("seconds");
            if (seconds?.options) seconds.options.max = flash ? 20 : 30;
            if (flash && seconds?.value > 20 && !node.inputs?.some((input) => input.name === "seconds" && input.link != null)) seconds.value = 20;
        }
    }
    resizeSeedanceNode(node, 460, (node.inputs ?? []).filter((input) => !input.hidden || input.link != null).length);
}

function schedule(node) {
    if (node.seedanceKling4Frame != null) cancelAnimationFrame(node.seedanceKling4Frame);
    node.seedanceKling4Frame = requestAnimationFrame(() => {
        node.seedanceKling4Frame = null;
        refresh(node);
    });
}

function install(node, name) {
    if (node[INSTALLED]) return;
    node[INSTALLED] = true;
    node.seedanceKling4Name = name;
    for (const name of ["reference_type", "source_mode", "model", "video_urls"]) {
        const widget = node.widgets?.find((item) => item.name === name);
        if (!widget) continue;
        const callback = widget.callback;
        widget.callback = (...args) => {
            const result = callback?.apply(widget, args);
            schedule(node);
            return result;
        };
    }
    schedule(node);
}

app.registerExtension({
    name: "ComfyUI_Seedance.Kling4UI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const name = originalSeedanceNodeName(nodeData.name);
        if (!NAMES.has(name)) return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            install(this, name);
            return result;
        };
        for (const name of ["onConfigure", "onConnectionsChange", "onAfterGraphConfigured"]) {
            const previous = nodeType.prototype[name];
            nodeType.prototype[name] = function () {
                const result = previous?.apply(this, arguments);
                schedule(this);
                return result;
            };
        }
    },
    async nodeCreated(node) {
        const name = originalSeedanceNodeName(node.comfyClass ?? node.constructor?.comfyClass
            ?? node.constructor?.nodeData?.name ?? node.type ?? "");
        if (NAMES.has(name)) install(node, name);
    },
});
