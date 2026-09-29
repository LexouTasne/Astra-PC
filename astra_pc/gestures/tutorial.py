from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2

from astra_pc.paths import data_dir


TUTORIAL_VERSION = 7
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
)


def tutorial_state_path() -> Path:
    return data_dir() / "gestures.json"


def tutorial_completed() -> bool:
    path = tutorial_state_path()
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return int(payload.get("tutorial_version", 0)) >= TUTORIAL_VERSION
    except Exception:
        return False


def mark_tutorial_completed() -> None:
    path = tutorial_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "tutorial_version": TUTORIAL_VERSION,
        "completed_at": time.time(),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@dataclass(slots=True)
class TutorialStep:
    title: str
    instruction: str
    predicate: Callable
    hold_seconds: float = 0.0
    timeout_seconds: float = 35.0
    hint: str = ""


def _draw_hand(frame, hand) -> None:
    h, w = frame.shape[:2]
    points = [
        (int(max(0, min(w - 1, p.x * w))), int(max(0, min(h - 1, p.y * h))))
        for p in hand.points
    ]
    for a, b in HAND_CONNECTIONS:
        cv2.line(frame, points[a], points[b], (175, 175, 175), 2, cv2.LINE_AA)
    for idx, point in enumerate(points):
        radius = 5 if idx in {4, 8, 12, 16, 20} else 3
        shade = 245 if idx in {4, 8, 12, 16, 20} else 205
        cv2.circle(frame, point, radius, (shade, shade, shade), -1, cv2.LINE_AA)


def _put_line(frame, text: str, y: int, scale: float, shade: int, thickness: int = 1) -> None:
    cv2.putText(
        frame,
        text,
        (20, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (shade, shade, shade),
        thickness,
        cv2.LINE_AA,
    )


def _overlay(
    frame,
    title: str,
    instruction: str,
    status: str,
    progress: float,
    hint: str = "",
) -> None:
    h, w = frame.shape[:2]
    top_h = 146 if hint else 124
    cv2.rectangle(frame, (0, 0), (w, top_h), (12, 12, 12), -1)
    cv2.line(frame, (0, top_h), (w, top_h), (55, 55, 55), 1)

    _put_line(frame, title, 31, 0.70, 250, 2)
    _put_line(frame, instruction[:96], 61, 0.47, 220)
    _put_line(frame, status[:96], 88, 0.47, 250)
    if hint:
        _put_line(frame, f"Dica: {hint[:88]}", 113, 0.42, 155)

    bar_y = top_h - 13
    bar_w = max(1, w - 40)
    cv2.rectangle(frame, (20, bar_y), (20 + bar_w, bar_y + 5), (55, 55, 55), -1)
    cv2.rectangle(
        frame,
        (20, bar_y),
        (20 + int(bar_w * max(0.0, min(1.0, progress))), bar_y + 5),
        (235, 235, 235),
        -1,
    )
    _put_line(frame, "ESC/Q sair  |  S pular etapa", h - 15, 0.42, 180)


def _steps(include_drag: bool = False) -> list[TutorialStep]:
    return [
        TutorialStep(
            "1/10 - Enquadramento",
            "Mostre uma mao inteira, incluindo pulso e pontas dos dedos.",
            lambda hands, out: len(hands) >= 1,
            hold_seconds=0.8,
            hint="Mao inteira no quadro e luz vindo da frente.",
        ),
        TutorialStep(
            "2/10 - Scroll para cima",
            "Indicador + medio levantados. Mova a mao para CIMA.",
            lambda hands, out: out.scroll > 0 and out.label == "scroll-up",
        ),
        TutorialStep(
            "3/10 - Scroll para baixo",
            "Indicador + medio levantados. Mova a mao para BAIXO.",
            lambda hands, out: out.scroll < 0 and out.label == "scroll-down",
        ),
        TutorialStep(
            "4/10 - Clique direito",
            "Encoste polegar + dedo medio, mantendo o indicador separado.",
            lambda hands, out: out.right_click or out.label == "right-click",
        ),
        TutorialStep(
            "5/10 - Swipe esquerda",
            "Levante indicador + medio + anelar e mova a mao para a ESQUERDA.",
            lambda hands, out: out.swipe == "left",
        ),
        TutorialStep(
            "6/10 - Swipe direita",
            "Mesma pose de tres dedos e mova a mao para a DIREITA.",
            lambda hands, out: out.swipe == "right",
        ),
        TutorialStep(
            "7/10 - Pinça de zoom",
            "Levante so o indicador e encoste polegar + indicador.",
            lambda hands, out: out.label in {"pinch-ready", "transform-ready", "transform"},
            hint="Nao precisa segurar: a pinça entra no modo zoom imediatamente.",
        ),
        TutorialStep(
            "8/10 - Zoom aproximar",
            "Faca a pinça e ABRA polegar + indicador.",
            lambda hands, out: out.zoom_steps > 0,
            hint="O zoom e global do desktop, nao do aplicativo.",
        ),
        TutorialStep(
            "9/10 - Zoom afastar",
            "Faca a pinça, abra um pouco e depois FECHE os dedos.",
            lambda hands, out: out.zoom_steps < 0,
        ),
        TutorialStep(
            "10/10 - Rotacao",
            "Faca a pinça e gire a linha entre polegar e indicador.",
            lambda hands, out: out.rotate_steps != 0,
            hint="A rotacao acompanha o angulo em graus, nao em blocos de 90.",
        ),
    ]


def run_gesture_tutorial(
    cap,
    tracker,
    engine,
    *,
    mirror: bool,
    backend=None,
    map_pointer=None,
    screen_w: int = 1920,
    screen_h: int = 1080,
) -> bool:
    steps = _steps(engine.feature_enabled("drag"))

    print("\n============================================================")
    print(" ASTRA // CALIBRACAO DE GESTOS V7")
    print("============================================================")
    print("O tutorial valida direcao, estabilidade e conflitos de cada gesto.")
    print("Nenhuma acao real de mouse/teclado e enviada durante a calibracao.")
    print()

    window = "Astra - Calibracao de Gestos"
    skipped = 0
    try:
        for step in steps:
            engine.reset_tracking()
            matched_since = None
            started = time.monotonic()
            last_label = "idle"

            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    if time.monotonic() - started > 5:
                        print("[gestures] camera parou de entregar frames.")
                        return False
                    continue

                if mirror:
                    frame = cv2.flip(frame, 1)

                hands = tracker.process(frame)
                out = engine.update(hands)
                last_label = out.label

                matched = bool(step.predicate(hands, out))
                now = time.monotonic()
                if matched:
                    if matched_since is None:
                        matched_since = now
                else:
                    matched_since = None

                held = 0.0 if matched_since is None else now - matched_since
                required = max(0.01, step.hold_seconds)
                progress = 1.0 if step.hold_seconds <= 0 and matched else min(
                    1.0,
                    held / required,
                )

                for hand in hands:
                    _draw_hand(frame, hand)

                status = (
                    f"OK: {last_label}"
                    if matched
                    else f"Detectado: {last_label} | maos: {len(hands)}"
                )
                _overlay(
                    frame,
                    step.title,
                    step.instruction,
                    status,
                    progress,
                    step.hint,
                )
                cv2.imshow(window, frame)
                key = cv2.waitKey(1) & 0xFF

                if key in (27, ord("q")):
                    print("[gestures] tutorial cancelado.")
                    return False
                if key == ord("s"):
                    skipped += 1
                    print(f"[gestures] etapa pulada: {step.title}")
                    break

                complete = matched and (
                    step.hold_seconds <= 0 or held >= step.hold_seconds
                )
                if complete:
                    print(f"[OK] {step.title} -> {last_label}")
                    time.sleep(0.18)
                    break

                if now - started > step.timeout_seconds:
                    print(f"[gestures] nao validei '{step.title}' em {int(step.timeout_seconds)}s.")
                    print("Dica: afaste a camera, melhore a luz e mantenha pulso + dedos no quadro.")
                    return False

        engine.reset_tracking()

        for _ in range(75):
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            if mirror:
                frame = cv2.flip(frame, 1)
            cv2.rectangle(
                frame,
                (0, 0),
                (frame.shape[1], frame.shape[0]),
                (12, 12, 12),
                -1,
            )
            lines = [
                ("Calibracao concluida", 0.78, 250),
                ("Scroll agora detecta cima E baixo.", 0.52, 220),
                ("Gestos possuem filtros contra jitter e conflito.", 0.52, 220),
                ("Voce pode controlar recursos falando com a Astra:", 0.52, 220),
                ('"desativa o scroll por gestos"', 0.48, 175),
                ('"ativa o zoom por gestos"', 0.48, 175),
                ('"desativa todos os gestos"', 0.48, 175),
                ("O modo normal vai iniciar.", 0.52, 220),
            ]
            y = 55
            for line, scale, shade in lines:
                _put_line(frame, line, y, scale, shade, 2 if y == 55 else 1)
                y += 34
            cv2.imshow(window, frame)
            if cv2.waitKey(24) & 0xFF in (27, ord("q")):
                break

        if skipped == 0:
            mark_tutorial_completed()
        else:
            print(
                f"[gestures] {skipped} etapa(s) puladas; "
                "a calibracao sera oferecida novamente."
            )
        return True
    except cv2.error as exc:
        print("[gestures] nao foi possivel abrir a janela do tutorial:", exc)
        print("Use desktop grafico ou rode: astra gestures --no-tutorial --show-camera")
        return False
    finally:
        try:
            cv2.destroyWindow(window)
        except Exception:
            pass
