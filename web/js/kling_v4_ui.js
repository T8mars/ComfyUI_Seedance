import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import {
    resizeSeedanceNode,
    setSeedanceInputVisible,
    setSeedanceWidgetVisible,
} from "./dynamic_widget_ui.js";

const NAMES = new Set(["Kling_V4_Custom_Element", "Kling_V4_Custom_Voice", "Kling_V4_T2V", "Kling_V4_I2V", "Kling_V4_Omni"]);
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
    if (name === "Kling_V4_Omni") {
        progressive(node, "image", 10);
        progressive(node, "video", 5);
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
    for (const name of ["reference_type", "source_mode"]) {
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
