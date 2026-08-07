const CONVERTED_WIDGET_PREFIX = "converted-widget";
const DYNAMIC_HIDDEN_WIDGET_TYPE = `${CONVERTED_WIDGET_PREFIX}:seedance-hidden`;
const ORIGINAL_WIDGET_STATE = Symbol("seedanceDynamicWidgetOriginal");
const ORIGINAL_INPUT_POSITION = Symbol("seedanceDynamicInputOriginalPosition");
const INPUT_POSITION_STATE = Symbol("seedanceDynamicInputPosition");
const INPUT_LAYOUT_STATE = Symbol("seedanceDynamicInputLayout");
const HIDDEN_WIDGET_SIZE = () => [0, -4];
const HIDDEN_INPUT_OFFSET = -100000;

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

export function setSeedanceInputVisible(node, input, visible) {
    if (!node || !input) {
        return false;
    }
    installSeedanceInputPositioning(node);
    installSeedanceInputLayout(node);
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
