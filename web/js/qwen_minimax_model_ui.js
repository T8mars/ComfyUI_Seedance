import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import {
    resizeSeedanceNode,
    setSeedanceInputVisible as setInputVisible,
    setSeedanceWidgetVisible as setWidgetVisible,
} from "./dynamic_widget_ui.js";

const QWEN_NODE_NAME = "Qwen_Image_3_0";
const MINIMAX_NODE_NAME = "Minimax_H3_OW_Video";
const QWEN_DEFAULT_MODEL = "qwen-image-3.0-t2i";
const MINIMAX_DEFAULT_MODEL = "minimax-h3-ow-t2v";

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

function refreshMinimaxNode(node) {
    const model = String(widgetByName(node, "model")?.value ?? MINIMAX_DEFAULT_MODEL);
    const needsImage = model.endsWith("-i2v") || model.endsWith("-r2v");
    for (const input of node.inputs ?? []) {
        const allowed = input.name === "api_config" || (
            input.name === "image1" && needsImage
        );
        setInputVisible(node, input, allowed);
    }
    resizeSeedanceNode(node, 380);
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

app.registerExtension({
    name: "ComfyUI_Seedance.QwenMinimaxModelUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const originalName = originalSeedanceNodeName(nodeData.name);
        if (![QWEN_NODE_NAME, MINIMAX_NODE_NAME].includes(originalName)) {
            return;
        }
        const refresh = originalName === QWEN_NODE_NAME
            ? refreshQwenNode
            : refreshMinimaxNode;

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            wrapRefreshWidget(this, "model", refresh, "seedanceQwenMinimaxModelCallback");
            if (originalName === QWEN_NODE_NAME) {
                wrapRefreshWidget(this, "sizing_mode", refresh, "seedanceQwenSizingCallback");
            }
            refresh(this);
            return result;
        };

        const originalOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalOnConfigure?.apply(this, arguments);
            refresh(this);
            return result;
        };

        const originalOnConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = originalOnConnectionsChange?.apply(this, arguments);
            refresh(this);
            return result;
        };
    },
});
