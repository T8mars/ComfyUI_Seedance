import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import { resizeSeedanceNode } from "./dynamic_widget_ui.js";

const REGION_NODE = "Zhenzhen_Image_GK_V2_Region_Edit";
const MODE_DEFAULTS = {
    object_indices: "[0]",
    boxes: "[[0, 0, 512, 512]]",
    selection_regions: '[{"x": 0, "y": 0, "width": 512, "height": 512}]',
};

function widgetByName(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function refreshRegionNode(node, previousMode = null) {
    const modeWidget = widgetByName(node, "selection_mode");
    const jsonWidget = widgetByName(node, "selection_json");
    const mode = String(modeWidget?.value ?? "object_indices");
    if (jsonWidget) {
        const current = String(jsonWidget.value ?? "").trim();
        const knownDefault = !current || Object.values(MODE_DEFAULTS).includes(current);
        if (knownDefault && previousMode !== mode) {
            jsonWidget.value = MODE_DEFAULTS[mode] ?? MODE_DEFAULTS.object_indices;
            jsonWidget.callback?.(jsonWidget.value);
        }
        jsonWidget.options ??= {};
        jsonWidget.options.tooltip = `JSON ${mode}`;
    }
    node.seedanceGKV2LastMode = mode;
    resizeSeedanceNode(node, 380);
}

app.registerExtension({
    name: "ComfyUI_Seedance.GKV2ToolsUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (originalSeedanceNodeName(nodeData.name) !== REGION_NODE) {
            return;
        }
        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            const modeWidget = widgetByName(this, "selection_mode");
            if (modeWidget && !modeWidget.seedanceGKV2RegionCallback) {
                const originalCallback = modeWidget.callback;
                modeWidget.callback = (...args) => {
                    const previousMode = String(this.seedanceGKV2LastMode ?? "");
                    const callbackResult = originalCallback?.apply(modeWidget, args);
                    refreshRegionNode(this, previousMode);
                    return callbackResult;
                };
                modeWidget.seedanceGKV2RegionCallback = true;
            }
            refreshRegionNode(this);
            return result;
        };

        const originalOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalOnConfigure?.apply(this, arguments);
            refreshRegionNode(this);
            return result;
        };
    },
});
