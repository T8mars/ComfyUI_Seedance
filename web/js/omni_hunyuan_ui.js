import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import {
    resizeSeedanceNode,
    setSeedanceInputVisible,
    setSeedanceWidgetVisible,
} from "./dynamic_widget_ui.js";

const LOWPRICE_NODE = "Zhenzhen_Video_G_Omni_Flash_Lowprice";
const HUNYUAN_NODE = "Hunyuan3D_V3_1";

function widgetByName(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function wrapWidgetRefresh(node, name, refresh) {
    const widget = widgetByName(node, name);
    const marker = `seedanceOmniHunyuan_${name}`;
    if (!widget || widget[marker]) {
        return;
    }
    const original = widget.callback;
    widget.callback = (...args) => {
        const result = original?.apply(widget, args);
        refresh(node);
        return result;
    };
    widget[marker] = true;
}

function refreshLowprice(node) {
    const mode = String(widgetByName(node, "mode")?.value ?? "text");
    const visibleImages = mode === "frame" ? 1 : mode === "reference_images" ? 3 : 0;
    for (const input of node.inputs ?? []) {
        const imageMatch = /^image([1-3])$/.exec(input.name);
        if (imageMatch) {
            setSeedanceInputVisible(node, input, Number(imageMatch[1]) <= visibleImages);
        } else if (input.name === "input_video") {
            setSeedanceInputVisible(node, input, mode === "reference_video");
        }
    }
    setSeedanceWidgetVisible(widgetByName(node, "video_url"), mode === "reference_video");
    setSeedanceWidgetVisible(widgetByName(node, "seconds"), mode !== "reference_video");
    resizeSeedanceNode(node, 360);
}

function refreshHunyuan(node) {
    const model = String(widgetByName(node, "model")?.value ?? "");
    const imageMode = model === "hunyuan3d-v3.1-image-to-3d";
    for (const input of node.inputs ?? []) {
        if (/^image[1-8]$/.test(input.name)) {
            setSeedanceInputVisible(node, input, imageMode);
        }
    }
    resizeSeedanceNode(node, 390);
}

app.registerExtension({
    name: "ComfyUI_Seedance.OmniHunyuanUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const originalName = originalSeedanceNodeName(nodeData.name);
        if (![LOWPRICE_NODE, HUNYUAN_NODE].includes(originalName)) {
            return;
        }
        const refresh = originalName === LOWPRICE_NODE ? refreshLowprice : refreshHunyuan;
        const selector = originalName === LOWPRICE_NODE ? "mode" : "model";

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            wrapWidgetRefresh(this, selector, refresh);
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
