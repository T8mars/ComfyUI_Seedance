import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import {
    resizeSeedanceNode,
    setSeedanceInputVisible as setInputVisible,
    setSeedanceWidgetVisible as setWidgetVisible,
} from "./dynamic_widget_ui.js";

const WAN30_NODE_NAME = "Wan_3_0_Video";
const WAN30_DEFAULT_MODEL = "wan-3.0-i2v";
const THINKING_MODELS = new Set([
    "wan-3.0-global-i2v",
    "wan-3.0-global-r2v",
]);
const IMAGE_INPUT = /^image([1-9]|10)$/;
const VIDEO_INPUT = /^video([1-5])$/;
const AUDIO_INPUT = /^audio([1-5])$/;

function widgetByName(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function nextVisibleSlot(node, pattern, maximum) {
    let highestConnected = 0;
    for (const input of node.inputs ?? []) {
        const match = pattern.exec(input.name);
        if (match && input.link != null) {
            highestConnected = Math.max(highestConnected, Number(match[1]));
        }
    }
    return Math.min(maximum, highestConnected + 1);
}

function inputAllowed(model, input, limits) {
    if (input.name === "api_config") {
        return true;
    }
    const imageMatch = IMAGE_INPUT.exec(input.name);
    if (imageMatch) {
        const index = Number(imageMatch[1]);
        return model.endsWith("-i2v")
            ? index <= 2
            : index <= limits.images;
    }
    const videoMatch = VIDEO_INPUT.exec(input.name);
    if (videoMatch) {
        return model.endsWith("-r2v")
            && Number(videoMatch[1]) <= limits.videos;
    }
    const audioMatch = AUDIO_INPUT.exec(input.name);
    if (audioMatch) {
        return model.endsWith("-r2v")
            && Number(audioMatch[1]) <= limits.audios;
    }
    return false;
}

function refreshWan30Node(node) {
    const model = String(widgetByName(node, "model")?.value ?? WAN30_DEFAULT_MODEL);
    const isR2V = model.endsWith("-r2v");
    const supportsThinking = THINKING_MODELS.has(model);
    const limits = {
        images: nextVisibleSlot(node, IMAGE_INPUT, 10),
        videos: nextVisibleSlot(node, VIDEO_INPUT, 5),
        audios: nextVisibleSlot(node, AUDIO_INPUT, 5),
    };

    setWidgetVisible(widgetByName(node, "enable_thinking"), supportsThinking);
    setWidgetVisible(widgetByName(node, "file_url"), isR2V);
    setWidgetVisible(widgetByName(node, "link_url"), isR2V);

    for (const input of node.inputs ?? []) {
        if (
            input.name === "api_config"
            || IMAGE_INPUT.test(input.name)
            || VIDEO_INPUT.test(input.name)
            || AUDIO_INPUT.test(input.name)
        ) {
            setInputVisible(node, input, inputAllowed(model, input, limits));
        }
    }
    resizeSeedanceNode(node, 430);
}

function scheduleWan30Refresh(node) {
    if (node.seedanceWan30RefreshFrame != null) {
        cancelAnimationFrame(node.seedanceWan30RefreshFrame);
    }
    node.seedanceWan30RefreshFrame = requestAnimationFrame(() => {
        node.seedanceWan30RefreshFrame = null;
        refreshWan30Node(node);
    });
}

function wrapModelRefresh(node) {
    const widget = widgetByName(node, "model");
    if (!widget || widget.seedanceWan30Callback) {
        return;
    }
    const originalCallback = widget.callback;
    widget.callback = (...args) => {
        const result = originalCallback?.apply(widget, args);
        scheduleWan30Refresh(node);
        return result;
    };
    widget.seedanceWan30Callback = true;
}

app.registerExtension({
    name: "ComfyUI_Seedance.Wan30ModelUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (originalSeedanceNodeName(nodeData.name) !== WAN30_NODE_NAME) {
            return;
        }

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            wrapModelRefresh(this);
            scheduleWan30Refresh(this);
            return result;
        };

        const originalOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalOnConfigure?.apply(this, arguments);
            scheduleWan30Refresh(this);
            return result;
        };

        const originalOnConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = originalOnConnectionsChange?.apply(this, arguments);
            scheduleWan30Refresh(this);
            return result;
        };

        const originalOnAfterGraphConfigured = nodeType.prototype.onAfterGraphConfigured;
        nodeType.prototype.onAfterGraphConfigured = function () {
            const result = originalOnAfterGraphConfigured?.apply(this, arguments);
            scheduleWan30Refresh(this);
            return result;
        };
    },
});
