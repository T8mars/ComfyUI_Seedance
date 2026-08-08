import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import {
    resizeSeedanceNode,
    setSeedanceInputVisible as setInputVisible,
    setSeedanceWidgetVisible as setWidgetVisible,
} from "./dynamic_widget_ui.js";

const FLUX3_NODE_NAME = "Flux_3_Video";
const FLUX3_DEFAULT_MODEL = "flux-3-video-t2v";
const IMAGE_INPUT = /^image([1-9]|10)$/;
const MEDIA_SOCKET_INPUTS = new Set(["input_video", "api_config"]);

function widgetByName(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function flux3Mode(model) {
    if (model.endsWith("-draft-enhance")) {
        return "draft-enhance";
    }
    if (model.endsWith("-i2v")) {
        return "i2v";
    }
    if (model.endsWith("-v2v")) {
        return "v2v";
    }
    return "t2v";
}

function nextVisibleImageSlot(node) {
    let highestConnected = 0;
    for (const input of node.inputs ?? []) {
        const match = IMAGE_INPUT.exec(input.name);
        if (match && input.link != null) {
            highestConnected = Math.max(highestConnected, Number(match[1]));
        }
    }
    return Math.min(highestConnected + 1, 10);
}

function inputAllowed(mode, input, nextImage) {
    if (input.name === "api_config") {
        return true;
    }
    const imageMatch = IMAGE_INPUT.exec(input.name);
    if (imageMatch) {
        return mode === "i2v" && Number(imageMatch[1]) <= nextImage;
    }
    if (input.name === "input_video" || input.name === "video_url") {
        return mode === "v2v";
    }
    if (input.name === "draft_cache") {
        return mode === "draft-enhance";
    }
    return false;
}

function refreshFlux3Node(node) {
    const model = String(widgetByName(node, "model")?.value ?? FLUX3_DEFAULT_MODEL);
    const mode = flux3Mode(model);
    const nextImage = nextVisibleImageSlot(node);

    setWidgetVisible(widgetByName(node, "prompt"), mode !== "draft-enhance");
    setWidgetVisible(widgetByName(node, "draft"), mode !== "draft-enhance");
    setWidgetVisible(widgetByName(node, "video_url"), mode === "v2v");
    setWidgetVisible(widgetByName(node, "draft_cache"), mode === "draft-enhance");

    for (const input of node.inputs ?? []) {
        if (IMAGE_INPUT.test(input.name) || MEDIA_SOCKET_INPUTS.has(input.name)) {
            setInputVisible(node, input, inputAllowed(mode, input, nextImage));
        }
    }
    resizeSeedanceNode(node, 440);
}

function scheduleFlux3Refresh(node) {
    if (node.seedanceFlux3RefreshFrame != null) {
        cancelAnimationFrame(node.seedanceFlux3RefreshFrame);
    }
    node.seedanceFlux3RefreshFrame = requestAnimationFrame(() => {
        node.seedanceFlux3RefreshFrame = null;
        refreshFlux3Node(node);
    });
}

function wrapModelRefresh(node) {
    const widget = widgetByName(node, "model");
    if (!widget || widget.seedanceFlux3Callback) {
        return;
    }
    const originalCallback = widget.callback;
    widget.callback = (...args) => {
        const result = originalCallback?.apply(widget, args);
        scheduleFlux3Refresh(node);
        return result;
    };
    widget.seedanceFlux3Callback = true;
}

app.registerExtension({
    name: "ComfyUI_Seedance.Flux3ModelUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (originalSeedanceNodeName(nodeData.name) !== FLUX3_NODE_NAME) {
            return;
        }

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            wrapModelRefresh(this);
            scheduleFlux3Refresh(this);
            return result;
        };

        const originalOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalOnConfigure?.apply(this, arguments);
            scheduleFlux3Refresh(this);
            return result;
        };

        const originalOnConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = originalOnConnectionsChange?.apply(this, arguments);
            scheduleFlux3Refresh(this);
            return result;
        };
    },
});
