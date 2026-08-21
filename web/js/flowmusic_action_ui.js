import { app } from "../../../scripts/app.js";
import {
    resizeSeedanceNode,
    setSeedanceInputVisible as setInputVisible,
    setSeedanceWidgetVisible as setWidgetVisible,
} from "./dynamic_widget_ui.js";

const FLOWMUSIC_NODE_NAME = "Flow_Music";
const ALWAYS_VISIBLE = new Set(["operation", "skip_error"]);
const ACTION_FIELDS = {
    "flowmusic-generation": [
        "version", "sound_prompt", "lyrics", "title", "bpm", "length", "seed",
    ],
    "flowmusic-lyrics": ["prompt"],
    "flowmusic-upload-audio": ["audio", "audio_url"],
    "flowmusic-extend": [
        "version", "clip_id", "extend_from_s", "extend_s", "instruction", "title", "seed",
    ],
    "flowmusic-replace": [
        "version", "clip_id", "start_s", "end_s", "instruction", "title", "seed",
    ],
    "flowmusic-cover": [
        "version", "clip_id", "instruction", "strength", "title", "seed",
    ],
    "flowmusic-stems": ["clip_id"],
    "flowmusic-download-audio": ["clip_id", "format"],
    "flowmusic-video-clip": ["clip_id", "preset"],
};
const MANAGED_FIELDS = new Set(
    Object.values(ACTION_FIELDS).flat().concat([...ALWAYS_VISIBLE]),
);

function refreshFlowMusicNode(node) {
    const operation = String(
        node.widgets?.find((widget) => widget.name === "operation")?.value
        ?? "flowmusic-generation",
    );
    const visible = new Set(ACTION_FIELDS[operation] ?? []);
    for (const field of ALWAYS_VISIBLE) {
        visible.add(field);
    }

    for (const widget of node.widgets ?? []) {
        if (MANAGED_FIELDS.has(widget.name)) {
            setWidgetVisible(widget, visible.has(widget.name));
        }
    }
    for (const input of node.inputs ?? []) {
        if (MANAGED_FIELDS.has(input.name)) {
            setInputVisible(node, input, visible.has(input.name));
        }
    }
    resizeSeedanceNode(node, 420);
}

function wrapRefresh(node, widgetName) {
    const widget = node.widgets?.find((item) => item.name === widgetName);
    if (!widget || widget.seedanceFlowMusicCallback) {
        return;
    }
    const originalCallback = widget.callback;
    widget.callback = (...args) => {
        const result = originalCallback?.apply(widget, args);
        refreshFlowMusicNode(node);
        return result;
    };
    widget.seedanceFlowMusicCallback = true;
}

app.registerExtension({
    name: "ComfyUI_Seedance.FlowMusicActionUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== FLOWMUSIC_NODE_NAME) {
            return;
        }

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            wrapRefresh(this, "operation");
            refreshFlowMusicNode(this);
            return result;
        };

        const originalOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalOnConfigure?.apply(this, arguments);
            refreshFlowMusicNode(this);
            return result;
        };

        const originalOnConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = originalOnConnectionsChange?.apply(this, arguments);
            refreshFlowMusicNode(this);
            return result;
        };
    },
});
