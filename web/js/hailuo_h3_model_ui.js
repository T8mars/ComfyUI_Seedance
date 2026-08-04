import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import {
    resizeSeedanceNode,
    setSeedanceWidgetVisible as setWidgetVisible,
} from "./dynamic_widget_ui.js";

const HAILUO_H3_NODE_NAME = "Hailuo_H3_Video";
const T2V_MODEL = "hailuo-h3-t2v";
const I2V_MODEL = "hailuo-h3-i2v";
const MULTI_MODEL = "hailuo-h3-multi";

function widgetByName(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function inputAllowed(model, name) {
    if (name === "api_config") {
        return true;
    }
    if (model === I2V_MODEL) {
        return name === "image1" || name === "image2";
    }
    if (model === MULTI_MODEL) {
        return /^(image[1-9]|video[1-3]|audio[1-3])$/.test(name);
    }
    return false;
}

function refreshHailuoH3Node(node) {
    const model = String(widgetByName(node, "model")?.value ?? T2V_MODEL);
    setWidgetVisible(widgetByName(node, "ratio"), model !== I2V_MODEL);

    for (const input of node.inputs ?? []) {
        const connected = input.link != null;
        input.hidden = !inputAllowed(model, input.name) && !connected;
    }

    resizeSeedanceNode(node, 420);
}

function wrapModelRefresh(node) {
    const widget = widgetByName(node, "model");
    if (!widget || widget.seedanceHailuoH3Callback) {
        return;
    }
    const originalCallback = widget.callback;
    widget.callback = (...args) => {
        const result = originalCallback?.apply(widget, args);
        refreshHailuoH3Node(node);
        return result;
    };
    widget.seedanceHailuoH3Callback = true;
}

app.registerExtension({
    name: "ComfyUI_Seedance.HailuoH3ModelUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (originalSeedanceNodeName(nodeData.name) !== HAILUO_H3_NODE_NAME) {
            return;
        }

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            wrapModelRefresh(this);
            refreshHailuoH3Node(this);
            return result;
        };

        const originalOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalOnConfigure?.apply(this, arguments);
            refreshHailuoH3Node(this);
            return result;
        };

        const originalOnConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = originalOnConnectionsChange?.apply(this, arguments);
            refreshHailuoH3Node(this);
            return result;
        };
    },
});
