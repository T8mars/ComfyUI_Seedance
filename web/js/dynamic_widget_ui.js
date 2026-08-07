const CONVERTED_WIDGET_PREFIX = "converted-widget";
const DYNAMIC_HIDDEN_WIDGET_TYPE = `${CONVERTED_WIDGET_PREFIX}:seedance-hidden`;
const ORIGINAL_WIDGET_STATE = Symbol("seedanceDynamicWidgetOriginal");
const ORIGINAL_INPUT_POSITION = Symbol("seedanceDynamicInputOriginalPosition");
const ORIGINAL_INPUT_WIDGET = Symbol("seedanceDynamicInputOriginalWidget");
const ORIGINAL_CONCRETE_INPUT_STATE = Symbol("seedanceDynamicConcreteInputOriginal");
const INPUT_POSITION_STATE = Symbol("seedanceDynamicInputPosition");
const INPUT_LAYOUT_STATE = Symbol("seedanceDynamicInputLayout");
const CONCRETE_INPUT_VISIBILITY_STATE = Symbol("seedanceDynamicConcreteInputVisibility");
const INPUT_SERIALIZATION_STATE = Symbol("seedanceDynamicInputSerialization");
const HIDDEN_WIDGET_SIZE = () => [0, -4];
const HIDDEN_INPUT_OFFSET = -100000;
const HIDDEN_INPUT_WIDGET_NAME = "__seedance_hidden_input__";

function hasOwn(object, property) {
    return Object.prototype.hasOwnProperty.call(object ?? {}, property);
}

function isExternalConvertedWidget(widget) {
    const type = String(widget?.type ?? "");
    return (
        hasOwn(widget, "origType")
        || (
            type.startsWith(CONVERTED_WIDGET_PREFIX)
            && type !== DYNAMIC_HIDDEN_WIDGET_TYPE
        )
    );
}

export function setSeedanceWidgetVisible(widget, visible) {
    if (!widget || isExternalConvertedWidget(widget)) {
        return false;
    }

    if (!widget[ORIGINAL_WIDGET_STATE]) {
        widget[ORIGINAL_WIDGET_STATE] = {
            type: widget.type,
            computeSize: widget.computeSize,
        };
    }
    const original = widget[ORIGINAL_WIDGET_STATE];
    const nextType = visible ? original.type : DYNAMIC_HIDDEN_WIDGET_TYPE;
    const nextComputeSize = visible ? original.computeSize : HIDDEN_WIDGET_SIZE;
    const changed = (
        widget.type !== nextType
        || widget.computeSize !== nextComputeSize
    );

    widget.type = nextType;
    widget.computeSize = nextComputeSize;
    return changed;
}

function installSeedanceInputPositioning(node) {
    if (!node || node[INPUT_POSITION_STATE]) {
        return;
    }
    const originalGetConnectionPos = node.getConnectionPos;
    if (typeof originalGetConnectionPos !== "function") {
        return;
    }
    node.getConnectionPos = function (isInput, slotNumber, out) {
        const inputs = this.inputs ?? [];
        const input = isInput ? inputs[slotNumber] : null;
        if (input?.hidden && input.link == null) {
            const result = out ?? new Float32Array(2);
            result[0] = Number(this.pos?.[0] ?? 0) + HIDDEN_INPUT_OFFSET;
            result[1] = Number(this.pos?.[1] ?? 0) + HIDDEN_INPUT_OFFSET;
            return result;
        }
        if (isInput) {
            const visibleInputs = inputs.filter(
                (candidate) => !candidate?.hidden || candidate.link != null,
            );
            const visibleSlot = visibleInputs.indexOf(input);
            if (visibleSlot >= 0 && visibleInputs.length !== inputs.length) {
                this.inputs = visibleInputs;
                try {
                    return originalGetConnectionPos.call(
                        this,
                        true,
                        visibleSlot,
                        out,
                    );
                } finally {
                    this.inputs = inputs;
                }
            }
        }
        return originalGetConnectionPos.apply(this, arguments);
    };
    node[INPUT_POSITION_STATE] = true;
}

function installSeedanceInputLayout(node) {
    if (!node || node[INPUT_LAYOUT_STATE]) {
        return;
    }
    const originalComputeSize = node.computeSize;
    if (typeof originalComputeSize !== "function") {
        return;
    }
    node.computeSize = function () {
        const inputs = this.inputs ?? [];
        const visibleInputs = inputs.filter(
            (input) => !input?.hidden || input.link != null,
        );
        if (visibleInputs.length === inputs.length) {
            return originalComputeSize.apply(this, arguments);
        }
        this.inputs = visibleInputs;
        try {
            return originalComputeSize.apply(this, arguments);
        } finally {
            this.inputs = inputs;
        }
    };
    node[INPUT_LAYOUT_STATE] = true;
}

function syncSeedanceConcreteInputVisibility(node) {
    const inputs = node?.inputs ?? [];
    const concreteInputs = node?._concreteInputs;
    if (!Array.isArray(concreteInputs)) {
        return;
    }
    concreteInputs.forEach((concreteInput, index) => {
        const input = inputs[index];
        if (!concreteInput || !input) {
            return;
        }
        if (!concreteInput[ORIGINAL_CONCRETE_INPUT_STATE]) {
            const currentWidget = concreteInput.widget;
            const isHiddenPlaceholder = (
                currentWidget?.name === HIDDEN_INPUT_WIDGET_NAME
            );
            const savedRawWidget = input[ORIGINAL_INPUT_WIDGET];
            const originalWidget = savedRawWidget?.hadWidget
                ? savedRawWidget.widget
                : currentWidget;
            concreteInput[ORIGINAL_CONCRETE_INPUT_STATE] = {
                hadWidget: (
                    Boolean(savedRawWidget?.hadWidget)
                    || (hasOwn(concreteInput, "widget") && !isHiddenPlaceholder)
                ),
                widget: isHiddenPlaceholder && !savedRawWidget?.hadWidget
                    ? undefined
                    : originalWidget,
                alwaysVisible: concreteInput.alwaysVisible,
            };
        }
        const original = concreteInput[ORIGINAL_CONCRETE_INPUT_STATE];
        if (input.hidden && input.link == null) {
            // Current ComfyUI draws non-widget concrete slots even when their
            // raw input is hidden. Mark only the concrete view as a widget slot
            // so the frontend omits it without changing workflow serialization.
            concreteInput.widget = { name: HIDDEN_INPUT_WIDGET_NAME };
            concreteInput.alwaysVisible = false;
            concreteInput.pos = [HIDDEN_INPUT_OFFSET, HIDDEN_INPUT_OFFSET];
        } else {
            if (original.hadWidget) {
                concreteInput.widget = original.widget;
            } else {
                delete concreteInput.widget;
            }
            concreteInput.alwaysVisible = original.alwaysVisible;
            concreteInput.pos = input.pos;
        }
    });
}

function installSeedanceConcreteInputVisibility(node) {
    if (!node || node[CONCRETE_INPUT_VISIBILITY_STATE]) {
        return;
    }
    const originalSetConcreteSlots = node._setConcreteSlots;
    if (typeof originalSetConcreteSlots === "function") {
        node._setConcreteSlots = function () {
            const result = originalSetConcreteSlots.apply(this, arguments);
            syncSeedanceConcreteInputVisibility(this);
            return result;
        };
    }
    const originalDrawSlots = node.drawSlots;
    if (typeof originalDrawSlots === "function") {
        node.drawSlots = function () {
            syncSeedanceConcreteInputVisibility(this);
            return originalDrawSlots.apply(this, arguments);
        };
    }
    node[CONCRETE_INPUT_VISIBILITY_STATE] = true;
    syncSeedanceConcreteInputVisibility(node);
}

function installSeedanceInputSerialization(node) {
    if (!node || node[INPUT_SERIALIZATION_STATE]) {
        return;
    }
    const originalOnSerialize = node.onSerialize;
    node.onSerialize = function (serialized) {
        const result = originalOnSerialize?.apply(this, arguments);
        for (const [index, input] of (this.inputs ?? []).entries()) {
            const savedPosition = input?.[ORIGINAL_INPUT_POSITION];
            const savedWidget = input?.[ORIGINAL_INPUT_WIDGET];
            const serializedInput = serialized?.inputs?.[index];
            if (!serializedInput || (!savedPosition && !savedWidget)) {
                continue;
            }
            if (savedWidget?.hadWidget) {
                serializedInput.widget = {
                    name: savedWidget.widget?.name,
                };
            } else if (savedWidget) {
                delete serializedInput.widget;
            }
            if (savedPosition?.hadPosition) {
                serializedInput.pos = [...savedPosition.position];
            } else if (savedPosition) {
                delete serializedInput.pos;
            }
        }
        return result;
    };
    node[INPUT_SERIALIZATION_STATE] = true;
}

function setSeedanceRawInputHidden(input, hidden) {
    if (!input[ORIGINAL_INPUT_WIDGET]) {
        input[ORIGINAL_INPUT_WIDGET] = {
            hadWidget: "widget" in input && Boolean(input.widget),
            widget: input.widget,
        };
    }
    const original = input[ORIGINAL_INPUT_WIDGET];
    if (hidden) {
        input.widget = { name: HIDDEN_INPUT_WIDGET_NAME };
    } else if (original.hadWidget) {
        input.widget = original.widget;
    } else {
        delete input.widget;
    }
}

export function setSeedanceInputVisible(node, input, visible) {
    if (!node || !input) {
        return false;
    }
    installSeedanceInputPositioning(node);
    installSeedanceInputLayout(node);
    installSeedanceConcreteInputVisibility(node);
    installSeedanceInputSerialization(node);
    const shouldShow = Boolean(visible || input.link != null);
    const nextHidden = !shouldShow;
    const changed = Boolean(input.hidden) !== nextHidden;
    if (!input[ORIGINAL_INPUT_POSITION]) {
        input[ORIGINAL_INPUT_POSITION] = {
            hadPosition: Array.isArray(input.pos) || ArrayBuffer.isView(input.pos),
            position: input.pos ? Array.from(input.pos) : null,
        };
    }
    input.hidden = nextHidden;
    setSeedanceRawInputHidden(input, nextHidden);
    if (nextHidden) {
        input.pos = [HIDDEN_INPUT_OFFSET, HIDDEN_INPUT_OFFSET];
    } else {
        const original = input[ORIGINAL_INPUT_POSITION];
        if (original.hadPosition) {
            input.pos = [...original.position];
        } else {
            delete input.pos;
        }
    }
    syncSeedanceConcreteInputVisibility(node);
    return changed;
}

export function resizeSeedanceNode(node, minimumWidth = 320, inputRows = null) {
    if (!node) {
        return;
    }
    if (node.seedanceDynamicResizeFrame != null) {
        cancelAnimationFrame(node.seedanceDynamicResizeFrame);
    }
    node.seedanceDynamicResizeFrame = requestAnimationFrame(() => {
        node.seedanceDynamicResizeFrame = null;
        const computed = node.computeSize?.();
        if (computed) {
            const currentWidth = Number(node.size?.[0]) || minimumWidth;
            const width = Math.max(
                currentWidth,
                Number(computed[0]) || 0,
                minimumWidth,
            );
            let height = Math.max(Number(computed[1]) || 0, 120);
            if (Number.isInteger(inputRows) && inputRows >= 0) {
                const slotHeight = 20;
                const slotStart = Number(node.constructor?.slot_start_y) || 0;
                const rows = Math.max(
                    inputRows,
                    Number(node.outputs?.length) || 0,
                    1,
                );
                const widgetsHeight = (node.widgets ?? []).reduce(
                    (total, widget) => {
                        const widgetHeight = widget.computeSize
                            ? Number(widget.computeSize(width)?.[1]) || 0
                            : 20;
                        return total + widgetHeight + 4;
                    },
                    (node.widgets?.length ?? 0) ? 8 : 0,
                );
                const slotHeightTotal = slotStart + rows * slotHeight;
                if (node.widgets_up) {
                    height = Math.max(slotHeightTotal, widgetsHeight) + 6;
                } else if (node.widgets_start_y != null) {
                    height = Math.max(
                        slotHeightTotal,
                        widgetsHeight + Number(node.widgets_start_y),
                    ) + 6;
                } else {
                    height = slotHeightTotal + widgetsHeight + 6;
                }
                height = Math.max(height, 120);
            }
            node.setSize?.([
                width,
                height,
            ]);
        }
        node.setDirtyCanvas?.(true, true);
    });
}

export const seedanceDynamicWidgetInternals = Object.freeze({
    convertedWidgetPrefix: CONVERTED_WIDGET_PREFIX,
    hiddenWidgetType: DYNAMIC_HIDDEN_WIDGET_TYPE,
    hiddenInputOffset: HIDDEN_INPUT_OFFSET,
});
