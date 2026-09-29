/*
 * Astra Continuous Rotation — KWin scripted effect.
 *
 * Rotates every EffectWindow around the center of KWin's virtual desktop.
 * The Astra daemon drives it through KGlobalAccel actions so applications
 * never need native rotation support.
 */
/*global effects, set, cancel, retarget, registerShortcut, Effect, QEasingCurve */

"use strict";

const AstraRotation = {
    angle: 0,

    virtualCenter() {
        const geo = effects.virtualScreenGeometry;
        return {
            x: geo.x + geo.width / 2,
            y: geo.y + geo.height / 2,
        };
    },

    windowGeometry(window) {
        return window.geometry || window.frameGeometry;
    },

    translationFor(window, angle) {
        const geo = this.windowGeometry(window);
        if (!geo) {
            return { x: 0, y: 0 };
        }

        const center = this.virtualCenter();
        const wx = geo.x + geo.width / 2;
        const wy = geo.y + geo.height / 2;
        const dx = wx - center.x;
        const dy = wy - center.y;
        const radians = angle * Math.PI / 180;
        const cos = Math.cos(radians);
        const sin = Math.sin(radians);

        const rx = center.x + dx * cos - dy * sin;
        const ry = center.y + dx * sin + dy * cos;
        return {
            x: rx - wx,
            y: ry - wy,
        };
    },

    canManage(window) {
        return window !== null
            && window !== undefined
            && window.deleted !== true;
    },

    clearWindow(window) {
        if (window.astraRotationIds !== undefined) {
            cancel(window.astraRotationIds);
            window.astraRotationIds = undefined;
        }
    },

    applyWindow(window) {
        if (!this.canManage(window)) {
            return;
        }

        if (this.angle === 0) {
            this.clearWindow(window);
            return;
        }

        const translation = this.translationFor(window, this.angle);
        const targetTranslation = {
            value1: translation.x,
            value2: translation.y,
        };

        if (
            window.astraRotationIds !== undefined
            && window.astraRotationIds.length >= 2
        ) {
            const rotationOk = retarget(
                window.astraRotationIds[0],
                this.angle,
                16
            );
            const translationOk = retarget(
                window.astraRotationIds[1],
                targetTranslation,
                16
            );
            if (rotationOk && translationOk) {
                return;
            }
            this.clearWindow(window);
        }

        window.astraRotationIds = set({
            window: window,
            duration: 16,
            curve: QEasingCurve.Linear,
            animations: [
                {
                    type: Effect.Rotation,
                    // Qt::ZAxis == 2. Rotate in the 2D desktop plane.
                    axis: 2,
                    from: this.angle,
                    to: this.angle,
                },
                {
                    type: Effect.Translation,
                    from: targetTranslation,
                    to: targetTranslation,
                },
            ],
        });
    },

    applyAll() {
        for (const window of effects.stackingOrder) {
            this.applyWindow(window);
        }
    },

    rotate(delta) {
        this.angle += delta;
        this.applyAll();
    },

    reset() {
        this.angle = 0;
        for (const window of effects.stackingOrder) {
            this.clearWindow(window);
        }
    },

    manage(window) {
        if (!this.canManage(window)) {
            return;
        }
        this.applyWindow(window);

        // Keep the global transform correct when a window moves/resizes while
        // the desktop is rotated.
        try {
            window.windowFrameGeometryChanged.connect(() => {
                AstraRotation.applyWindow(window);
            });
        } catch (_) {
            // Older EffectWindow wrappers can omit this signal.
        }
    },

    init() {
        registerShortcut(
            "AstraRotatePlus1",
            "Astra rotation +1 degree",
            "",
            () => this.rotate(1)
        );
        registerShortcut(
            "AstraRotateMinus1",
            "Astra rotation -1 degree",
            "",
            () => this.rotate(-1)
        );
        registerShortcut(
            "AstraRotatePlus5",
            "Astra rotation +5 degrees",
            "",
            () => this.rotate(5)
        );
        registerShortcut(
            "AstraRotateMinus5",
            "Astra rotation -5 degrees",
            "",
            () => this.rotate(-5)
        );
        registerShortcut(
            "AstraRotatePlus15",
            "Astra rotation +15 degrees",
            "",
            () => this.rotate(15)
        );
        registerShortcut(
            "AstraRotateMinus15",
            "Astra rotation -15 degrees",
            "",
            () => this.rotate(-15)
        );
        registerShortcut(
            "AstraRotateReset",
            "Astra rotation reset",
            "",
            () => this.reset()
        );

        effects.windowAdded.connect((window) => this.manage(window));
        effects.windowClosed.connect((window) => this.clearWindow(window));
        effects.virtualScreenGeometryChanged.connect(() => this.applyAll());

        for (const window of effects.stackingOrder) {
            this.manage(window);
        }
    },
};

AstraRotation.init();
