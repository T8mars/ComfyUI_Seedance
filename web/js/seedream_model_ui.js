import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import {
    resizeSeedanceNode,
    setSeedanceWidgetVisible as setWidgetVisible,
} from "./dynamic_widget_ui.js";

const NODE_NAME = "Seedream_V5_Pro_Image";
const PRO_RESOLUTIONS = ["1k", "2k", "custom"];
const FLASH_RESOLUTIONS = ["1k", "1.5k", "2k", "custom"];
const INSTALL_MARKER = Symbol("seedanceSeedreamModelUiInstalled");

function widgetByName(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function updateCombo(widget, values, preferred) {
    if (!widget) {
        return;
    }
    widget.options ??= {};
    widget.options.values = [...values];
    if (!values.includes(String(widget.value))) {
        widget.value = values.includes(preferred) ? preferred : values[0];
        widget.callback?.(widget.value);
    }
}

function refreshSeedreamNode(node) {
    const family = String(widgetByName(node, "model_family")?.value ?? "");
    const isFlash = family.includes("-flash ");
    const resolution = widgetByName(node, "resolution");
    updateCombo(
        resolution,
        isFlash ? FLASH_RESOLUTIONS : PRO_RESOLUTIONS,
        "2k",
    );
    const isCustom = String(resolution?.value ?? "") === "custom";
    setWidgetVisible(widgetByName(node, "width"), isCustom);
    setWidgetVisible(widgetByName(node, "height"), isCustom);
    resizeSeedanceNode(node, 420);
}

function scheduleRefresh(node) {
    if (node.seedanceSeedreamRefreshFrame != null) {
        cancelAnimationFrame(node.seedanceSeedreamRefreshFrame);
    }
    node.seedanceSeedreamRefreshFrame = requestAnimationFrame(() => {
        node.seedanceSeedreamRefreshFrame = null;
        refreshSeedreamNode(node);
    });
}

function wrapRefresh(node, widgetName) {
    const widget = widgetByName(node, widgetName);
    const marker = `seedanceSeedreamCallback_${widgetName}`;
    if (!widget || widget[marker]) {
        return;
    }
    const originalCallback = widget.callback;
    widget.callback = (...args) => {
        const result = originalCallback?.apply(widget, args);
        scheduleRefresh(node);
        return result;
    };
    widget[marker] = true;
}

function installSeedreamModelUi(node) {
    if (!node || node[INSTALL_MARKER]) {
        return;
    }
    node[INSTALL_MARKER] = true;
    wrapRefresh(node, "model_family");
    wrapRefresh(node, "resolution");
    scheduleRefresh(node);
}

function nodeClassName(node) {
    return (
        node?.comfyClass
        ?? node?.constructor?.comfyClass
        ?? node?.constructor?.nodeData?.name
        ?? node?.type
        ?? ""
    );
}

app.registerExtension({
    name: "ComfyUI_Seedance.SeedreamModelUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (originalSeedanceNodeName(nodeData.name) !== NODE_NAME) {
            return;
        }

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            installSeedreamModelUi(this);
            return result;
        };

        const originalOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalOnConfigure?.apply(this, arguments);
            scheduleRefresh(this);
            return result;
        };
    },
    async nodeCreated(node) {
        if (originalSeedanceNodeName(nodeClassName(node)) === NODE_NAME) {
            installSeedreamModelUi(node);
        }
    },
});
