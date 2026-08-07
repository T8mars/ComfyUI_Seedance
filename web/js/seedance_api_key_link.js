import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import {
    resizeSeedanceNode,
    setSeedanceInputVisible,
} from "./dynamic_widget_ui.js";

const PLUGIN_MODULE = "custom_nodes.ComfyUI_Seedance";
const API_KEY_BUTTON_LABEL = "获取平价版APIKEY";
const API_KEY_SIGNUP_URL = "https://api.seedance.nz/sign-up?aff=5f4w";
const EXCLUDED_NODE_NAMES = new Set(["Seedance_Config"]);
const SEEDANCE25_NODE_NAME = "Seedance_2_5_Video";
const SEEDANCE25_MEDIA_LIMITS = { image: 30, video: 10, audio: 10 };
const SEEDANCE25_MEDIA_INPUT = /^(image|video|audio)([1-9]\d*)$/;

function widgetByName(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function seedance25Mode(model) {
    if (model.endsWith("-i2v")) {
        return "i2v";
    }
    if (model.endsWith("-multi")) {
        return "multi";
    }
    return "t2v";
}

function seedance25MediaInput(name) {
    const match = SEEDANCE25_MEDIA_INPUT.exec(String(name));
    if (!match) {
        return null;
    }
    return { family: match[1], index: Number(match[2]) };
}

function seedance25NextVisibleSlots(node) {
    const highestConnected = { image: 0, video: 0, audio: 0 };
    for (const input of node.inputs ?? []) {
        const media = seedance25MediaInput(input.name);
        if (media && input.link != null) {
            highestConnected[media.family] = Math.max(
                highestConnected[media.family],
                media.index,
            );
        }
    }
    return Object.fromEntries(
        Object.entries(SEEDANCE25_MEDIA_LIMITS).map(([family, limit]) => [
            family,
            Math.min(highestConnected[family] + 1, limit),
        ]),
    );
}

function seedance25InputAllowed(mode, name, nextVisible) {
    if (name === "api_config") {
        return true;
    }
    if (mode === "i2v") {
        return name === "image1" || name === "image2";
    }
    if (mode === "multi") {
        const media = seedance25MediaInput(name);
        return Boolean(
            media
            && media.index <= SEEDANCE25_MEDIA_LIMITS[media.family]
            && media.index <= nextVisible[media.family]
        );
    }
    return false;
}

function refreshSeedance25Node(node) {
    const model = String(widgetByName(node, "model")?.value ?? "");
    const mode = seedance25Mode(model);
    const nextVisible = seedance25NextVisibleSlots(node);
    for (const input of node.inputs ?? []) {
        if (!seedance25MediaInput(input.name) && input.name !== "api_config") {
            continue;
        }
        setSeedanceInputVisible(
            node,
            input,
            seedance25InputAllowed(mode, input.name, nextVisible),
        );
    }
    const visibleInputs = (node.inputs ?? []).filter(
        (input) => (
            (seedance25MediaInput(input.name) || input.name === "api_config")
            && (!input.hidden || input.link != null)
        ),
    );
    const slotStart = Number(node.constructor?.slot_start_y) || 0;
    visibleInputs.forEach((input, index) => {
        input.pos = [10, slotStart + (index + 0.7) * 20];
    });
    resizeSeedanceNode(node, 440, visibleInputs.length);
}

function wrapSeedance25ModelRefresh(node) {
    const widget = widgetByName(node, "model");
    if (!widget || widget.seedance25Callback) {
        return;
    }
    const originalCallback = widget.callback;
    widget.callback = (...args) => {
        const result = originalCallback?.apply(widget, args);
        refreshSeedance25Node(node);
        return result;
    };
    widget.seedance25Callback = true;
}

function scheduleSeedance25Refresh(node) {
    if (node.seedance25RefreshFrame != null) {
        cancelAnimationFrame(node.seedance25RefreshFrame);
    }
    node.seedance25RefreshFrame = requestAnimationFrame(() => {
        node.seedance25RefreshFrame = null;
        wrapSeedance25ModelRefresh(node);
        refreshSeedance25Node(node);
    });
}

function belongsToSeedancePlugin(nodeData) {
    const pythonModule = String(nodeData.python_module ?? "");
    return pythonModule === PLUGIN_MODULE || pythonModule.startsWith(`${PLUGIN_MODULE}.`);
}

app.registerExtension({
    name: "ComfyUI_Seedance.APIKeyLink",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!belongsToSeedancePlugin(nodeData) || EXCLUDED_NODE_NAMES.has(nodeData.name)) {
            return;
        }

        const isSeedance25 = (
            originalSeedanceNodeName(nodeData.name) === SEEDANCE25_NODE_NAME
        );

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);

            if (isSeedance25) {
                scheduleSeedance25Refresh(this);
            }

            if (!this.widgets?.some((widget) => widget.seedanceApiKeyLink)) {
                const button = this.addWidget("button", API_KEY_BUTTON_LABEL, null, () => {
                    window.open(API_KEY_SIGNUP_URL, "_blank", "noopener,noreferrer");
                });
                button.serialize = false;
                button.seedanceApiKeyLink = true;
            }

            return result;
        };

        if (isSeedance25) {
            const originalOnConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function () {
                const result = originalOnConfigure?.apply(this, arguments);
                scheduleSeedance25Refresh(this);
                return result;
            };

            const originalOnConnectionsChange = nodeType.prototype.onConnectionsChange;
            nodeType.prototype.onConnectionsChange = function () {
                const result = originalOnConnectionsChange?.apply(this, arguments);
                scheduleSeedance25Refresh(this);
                return result;
            };
        }
    },
});
