import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import {
    resizeSeedanceNode,
    setSeedanceInputVisible as setInputVisible,
    setSeedanceWidgetVisible as setWidgetVisible,
} from "./dynamic_widget_ui.js";

const HAILUO_H3_NODE_NAME = "Hailuo_H3_Video";
const HAILUO_H3_MAX_NODE_NAME = "Hailuo_H3_Max_Video";
const HAILUO_H3_NODE_NAMES = new Set([
    HAILUO_H3_NODE_NAME,
    HAILUO_H3_MAX_NODE_NAME,
]);
const T2V_MODEL = "hailuo-h3-t2v";
const HAILUO_MEDIA_INPUT = /^(image[1-9]|video[1-3]|audio[1-3])$/;
const HAILUO_H3_MAX_STANDARD_RESOLUTIONS = ["480P", "768P"];
const HAILUO_H3_MAX_TURBO_RESOLUTIONS = ["480p", "768p"];

function widgetByName(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function inputAllowed(model, name) {
    if (name === "api_config") {
        return true;
    }
    if (model.endsWith("-i2v")) {
        return name === "image1" || name === "image2";
    }
    if (model.endsWith("-multi")) {
        return /^(image[1-9]|video[1-3]|audio[1-3])$/.test(name);
    }
    return false;
}

function refreshHailuoH3MaxResolution(node, model) {
    if (node.seedanceHailuoH3NodeName !== HAILUO_H3_MAX_NODE_NAME) {
        return;
    }
    const widget = widgetByName(node, "resolution");
    if (!widget) {
        return;
    }
    const isTurbo = model.includes("-max-turbo-");
    const values = isTurbo
        ? HAILUO_H3_MAX_TURBO_RESOLUTIONS
        : HAILUO_H3_MAX_STANDARD_RESOLUTIONS;
    const normalized = isTurbo
        ? String(widget.value ?? values[0]).toLowerCase()
        : String(widget.value ?? values[0]).toUpperCase();
    widget.options ??= {};
    widget.options.values = [...values];
    widget.value = values.includes(normalized) ? normalized : values[0];
}

function refreshHailuoH3Node(node) {
    const model = String(widgetByName(node, "model")?.value ?? T2V_MODEL);
    refreshHailuoH3MaxResolution(node, model);
    setWidgetVisible(widgetByName(node, "ratio"), !model.endsWith("-i2v"));

    for (const input of node.inputs ?? []) {
        if (input.name === "api_config" || HAILUO_MEDIA_INPUT.test(input.name)) {
            setInputVisible(node, input, inputAllowed(model, input.name));
        }
    }

    resizeSeedanceNode(node, 420);
}

function scheduleHailuoH3Refresh(node) {
    if (node.seedanceHailuoH3RefreshFrame != null) {
        cancelAnimationFrame(node.seedanceHailuoH3RefreshFrame);
    }
    node.seedanceHailuoH3RefreshFrame = requestAnimationFrame(() => {
        node.seedanceHailuoH3RefreshFrame = null;
        refreshHailuoH3Node(node);
    });
}

function wrapModelRefresh(node) {
    const widget = widgetByName(node, "model");
    if (!widget || widget.seedanceHailuoH3Callback) {
        return;
    }
    const originalCallback = widget.callback;
    widget.callback = (...args) => {
        const result = originalCallback?.apply(widget, args);
        scheduleHailuoH3Refresh(node);
        return result;
    };
    widget.seedanceHailuoH3Callback = true;
}

app.registerExtension({
    name: "ComfyUI_Seedance.HailuoH3ModelUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const originalNodeName = originalSeedanceNodeName(nodeData.name);
        if (!HAILUO_H3_NODE_NAMES.has(originalNodeName)) {
            return;
        }
        nodeType.prototype.seedanceHailuoH3NodeName = originalNodeName;

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            wrapModelRefresh(this);
            scheduleHailuoH3Refresh(this);
            return result;
        };

        const originalOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalOnConfigure?.apply(this, arguments);
            scheduleHailuoH3Refresh(this);
            return result;
        };

        const originalOnConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = originalOnConnectionsChange?.apply(this, arguments);
            scheduleHailuoH3Refresh(this);
            return result;
        };
    },
});
