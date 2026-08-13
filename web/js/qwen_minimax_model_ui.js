import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import {
    resizeSeedanceNode,
    setSeedanceInputVisible as setInputVisible,
    setSeedanceWidgetVisible as setWidgetVisible,
} from "./dynamic_widget_ui.js";

const QWEN_NODE_NAME = "Qwen_Image_3_0";
const MINIMAX_NODE_NAME = "Minimax_H3_OW_Video";
const MINIMAX_FAST_NODE_NAME = "Minimax_H3_OW_Fast_Video";
const CONTEXT_IR_NODE_NAME = "Minimax_H3_Context_IR";
const QWEN_DEFAULT_MODEL = "qwen-image-3.0-t2i";
const MINIMAX_DEFAULT_MODEL = "minimax-h3-ow-t2v";
const MINIMAX_FAST_DEFAULT_MODEL = "minimax-h3-ow-i2v-fast";
const CONTEXT_IR_DEFAULT_MODEL = "minmax-h3-context-ir-text";
const CONTEXT_IR_MEDIA_INPUT = /^(image[1-9]|video[1-3]|audio[1-3])$/;

function widgetByName(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function isQwenI2I(model) {
    return String(model).endsWith("-i2i");
}

function refreshQwenNode(node) {
    const model = String(widgetByName(node, "model")?.value ?? QWEN_DEFAULT_MODEL);
    const sizingMode = String(widgetByName(node, "sizing_mode")?.value ?? "auto");
    setWidgetVisible(widgetByName(node, "resolution"), sizingMode === "ratio");
    setWidgetVisible(widgetByName(node, "ratio"), sizingMode === "ratio");
    setWidgetVisible(widgetByName(node, "custom_size"), sizingMode === "custom_size");

    for (const input of node.inputs ?? []) {
        const allowed = input.name === "api_config" || (
            isQwenI2I(model) && /^image[1-3]$/.test(input.name)
        );
        setInputVisible(node, input, allowed);
    }
    resizeSeedanceNode(node, 380);
}

function refreshMinimaxNode(node, fallbackModel = MINIMAX_DEFAULT_MODEL) {
    const model = String(widgetByName(node, "model")?.value ?? fallbackModel);
    const isAudioDrive = model.includes("-audio-drive-fast");
    const maxImages = model.endsWith("-r2v-fast")
        ? 9
        : (isAudioDrive || model.includes("-i2v") || model.includes("-r2v") ? 1 : 0);
    for (const input of node.inputs ?? []) {
        const imageMatch = /^image([1-9])$/.exec(input.name);
        const allowed = input.name === "api_config"
            || (input.name === "audio" && isAudioDrive)
            || (
            imageMatch && Number(imageMatch[1]) <= maxImages
        );
        setInputVisible(node, input, allowed);
    }
    resizeSeedanceNode(node, 380);
}

function contextIRInputAllowed(model, name) {
    if (name === "api_config") {
        return true;
    }
    if (model.endsWith("-image")) {
        return name === "image1" || name === "image2";
    }
    if (model.endsWith("-multimodal")) {
        return CONTEXT_IR_MEDIA_INPUT.test(name);
    }
    return false;
}

function refreshContextIRNode(node) {
    const model = String(widgetByName(node, "model")?.value ?? CONTEXT_IR_DEFAULT_MODEL);
    setWidgetVisible(widgetByName(node, "ratio"), !model.endsWith("-image"));
    for (const input of node.inputs ?? []) {
        if (input.name === "api_config" || CONTEXT_IR_MEDIA_INPUT.test(input.name)) {
            setInputVisible(node, input, contextIRInputAllowed(model, input.name));
        }
    }
    resizeSeedanceNode(node, 420);
}

function wrapRefreshWidget(node, name, refresh, marker) {
    const widget = widgetByName(node, name);
    if (!widget || widget[marker]) {
        return;
    }
    const originalCallback = widget.callback;
    widget.callback = (...args) => {
        const result = originalCallback?.apply(widget, args);
        refresh(node);
        return result;
    };
    widget[marker] = true;
}

function scheduleQwenMinimaxRefresh(node, refresh) {
    if (node.seedanceQwenMinimaxRefreshFrame != null) {
        cancelAnimationFrame(node.seedanceQwenMinimaxRefreshFrame);
    }
    node.seedanceQwenMinimaxRefreshFrame = requestAnimationFrame(() => {
        node.seedanceQwenMinimaxRefreshFrame = null;
        refresh(node);
    });
}

app.registerExtension({
    name: "ComfyUI_Seedance.QwenMinimaxModelUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const originalName = originalSeedanceNodeName(nodeData.name);
        if (![
            QWEN_NODE_NAME,
            MINIMAX_NODE_NAME,
            MINIMAX_FAST_NODE_NAME,
            CONTEXT_IR_NODE_NAME,
        ].includes(originalName)) {
            return;
        }
        let refresh;
        if (originalName === QWEN_NODE_NAME) {
            refresh = refreshQwenNode;
        } else if (originalName === CONTEXT_IR_NODE_NAME) {
            refresh = refreshContextIRNode;
        } else {
            refresh = (node) => refreshMinimaxNode(
                node,
                originalName === MINIMAX_FAST_NODE_NAME
                    ? MINIMAX_FAST_DEFAULT_MODEL
                    : MINIMAX_DEFAULT_MODEL,
            );
        }

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            wrapRefreshWidget(this, "model", refresh, "seedanceQwenMinimaxModelCallback");
            if (originalName === QWEN_NODE_NAME) {
                wrapRefreshWidget(this, "sizing_mode", refresh, "seedanceQwenSizingCallback");
            }
            scheduleQwenMinimaxRefresh(this, refresh);
            return result;
        };

        const originalOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalOnConfigure?.apply(this, arguments);
            scheduleQwenMinimaxRefresh(this, refresh);
            return result;
        };

        const originalOnConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = originalOnConnectionsChange?.apply(this, arguments);
            scheduleQwenMinimaxRefresh(this, refresh);
            return result;
        };

        const originalOnAfterGraphConfigured = nodeType.prototype.onAfterGraphConfigured;
        nodeType.prototype.onAfterGraphConfigured = function () {
            const result = originalOnAfterGraphConfigured?.apply(this, arguments);
            scheduleQwenMinimaxRefresh(this, refresh);
            return result;
        };
    },
});
