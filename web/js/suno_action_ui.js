import { app } from "../../../scripts/app.js";
import {
    resizeSeedanceNode,
    setSeedanceInputVisible as setInputVisible,
    setSeedanceWidgetVisible as setWidgetVisible,
} from "./dynamic_widget_ui.js";

const SUNO_NODE_NAME = "Suno_Music";
const ALWAYS_VISIBLE = new Set(["operation", "skip_error"]);
const AUDIO_FIELDS = [
    "audio1",
    "audio_url1",
    "audio2",
    "audio_url2",
    "audio3",
    "audio_url3",
    "audio4",
    "audio_url4",
];

const ACTION_FIELDS = {
    "suno-generation": ["prompt", "version", "custom", "instrumental", "title", "style", "vocal_gender"],
    "suno-lyrics": ["prompt"],
    "suno-upload": ["audio1", "audio_url1"],
    "suno-extend": ["version", "task_id", "audio_index", "continue_at"],
    "suno-cover-song": ["prompt", "version", "task_id", "audio_index"],
    "suno-inspo": ["version", ...AUDIO_FIELDS],
    "suno-mashup": ["prompt", "version", "task_id", "task_id_2"],
    "suno-upsample-tags": ["tags"],
    "suno-sounds": ["prompt", "version"],
    "suno-create-voice": ["audio1", "audio_url1"],
    "suno-stems": ["task_id", "audio_index"],
    "suno-stems-all": ["task_id", "audio_index"],
    "suno-wav": ["task_id", "audio_index"],
    "suno-generate-mp4": ["task_id", "audio_index"],
    "suno-concat": ["task_id", "audio_index"],
    "suno-crop": ["task_id", "audio_index", "start_s", "end_s"],
    "suno-fade-in": ["task_id", "audio_index", "duration_s"],
    "suno-fade-out": ["task_id", "audio_index", "duration_s"],
    "suno-remove-section": ["task_id", "audio_index", "start_s", "end_s"],
    "suno-replace-music": ["version", "task_id", "audio_index", "start_s", "end_s"],
    "suno-adjust-speed": ["task_id", "audio_index", "speed"],
    "suno-remaster": ["version", "task_id", "audio_index"],
    "suno-midi": ["task_id", "audio_index"],
    "suno-bpm": ["task_id", "audio_index"],
    "suno-aligned-lyrics": ["task_id", "audio_index"],
    "suno-persona": ["task_id", "audio_index", "name"],
    "suno-vox": ["task_id", "audio_index"],
    "suno-sample": ["prompt", "version", "task_id", "audio_index", "start_s", "end_s"],
    "suno-add-vocals": ["prompt", "version", "task_id", "audio_index"],
    "suno-add-instrumental": ["prompt", "version", "task_id", "audio_index"],
    "suno-add-stem": ["prompt", "version", "task_id", "audio_index"],
};

const MANAGED_FIELDS = new Set(
    Object.values(ACTION_FIELDS).flat().concat([...ALWAYS_VISIBLE]),
);

function refreshSunoNode(node) {
    const operationWidget = node.widgets?.find((widget) => widget.name === "operation");
    const operation = String(operationWidget?.value ?? "suno-generation");
    const fields = new Set(ACTION_FIELDS[operation] ?? []);
    for (const name of ALWAYS_VISIBLE) {
        fields.add(name);
    }

    for (const widget of node.widgets ?? []) {
        if (MANAGED_FIELDS.has(widget.name)) {
            setWidgetVisible(widget, fields.has(widget.name));
        }
    }

    for (const input of node.inputs ?? []) {
        if (!MANAGED_FIELDS.has(input.name)) {
            continue;
        }
        setInputVisible(node, input, fields.has(input.name));
    }

    resizeSeedanceNode(node, 320);
}

app.registerExtension({
    name: "ComfyUI_Seedance.SunoActionUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== SUNO_NODE_NAME) {
            return;
        }

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            const operationWidget = this.widgets?.find(
                (widget) => widget.name === "operation",
            );
            if (operationWidget && !operationWidget.seedanceSunoCallback) {
                const originalCallback = operationWidget.callback;
                operationWidget.callback = (...args) => {
                    const callbackResult = originalCallback?.apply(operationWidget, args);
                    refreshSunoNode(this);
                    return callbackResult;
                };
                operationWidget.seedanceSunoCallback = true;
            }
            refreshSunoNode(this);
            return result;
        };

        const originalOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalOnConfigure?.apply(this, arguments);
            refreshSunoNode(this);
            return result;
        };

        const originalOnConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = originalOnConnectionsChange?.apply(this, arguments);
            refreshSunoNode(this);
            return result;
        };
    },
});
