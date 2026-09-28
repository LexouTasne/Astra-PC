from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2

from astra_pc.paths import data_dir


TUTORIAL_VERSION = 2
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
    timeout_seconds: float = 30.0


def _draw_hand(frame, hand) -> None:
    h, w = frame.shape[:2]
    points = [
        (int(max(0, min(w - 1, p.x * w))), int(max(0, min(h - 1, p.y * h))))
        for p in hand.points
    ]
    for a, b in HAND_CONNECTIONS:
        cv2.line(frame, points[a], points[b], (90, 220, 255), 2, cv2.LINE_AA)
    for idx, point in enumerate(points):
        radius = 5 if idx in {4, 8, 12, 16, 20} else 3
        cv2.circle(frame, point, radius, (70, 255, 120), -1, cv2.LINE_AA)


def _overlay(frame, title: str, instruction: str, status: str, progress: float) -> None:
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w, 118), (15, 15, 15), -1)
    cv2.putText(
        frame,
        title,
        (18, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.72,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        instruction[:92],
        (18, 61),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (220, 220, 220),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        status[:92],
        (18, 88),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (80, 255, 140),
        1,
        cv2.LINE_AA,
    )
    bar_w = max(1, w - 36)
    cv2.rectangle(frame, (18, 100), (18 + bar_w, 109), (70, 70, 70), -1)
    cv2.rectangle(
        frame,
        (18, 100),
        (18 + int(bar_w * max(0.0, min(1.0, progress))), 109),
        (80, 220, 120),
        -1,
    )
    cv2.putText(
        frame,
        "ESC/Q sair  |  S pular etapa",
        (18, h - 16),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.44,
        (210, 210, 210),
        1,
        cv2.LINE_AA,
    )


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
    steps = [
        TutorialStep(
            "1/7 - Mostre uma mao",
            "Deixe a mao inteira visivel e bem iluminada na camera.",
            lambda hands, out: len(hands) >= 1,
            hold_seconds=0.8,
        ),
        TutorialStep(
            "2/7 - Ponteiro",
            "Levante somente o indicador e mova ele devagar. O cursor deve acompanhar.",
            lambda hands, out: out.pointer is not None and out.label == "pointer",
            hold_seconds=1.2,
        ),
        TutorialStep(
            "3/7 - Clique",
            "Encoste polegar + indicador e solte. Isso e o clique esquerdo.",
            lambda hands, out: out.label in {"pinch", "click"},
        ),
        TutorialStep(
            "4/7 - Arrastar",
            "Polegar + indicador: segure a pinca por um instante e mova a mao.",
            lambda hands, out: out.label == "drag",
            hold_seconds=0.55,
        ),
        TutorialStep(
            "5/7 - Scroll",
            "Levante indicador + medio, abaixe os outros e mova os dois para cima/baixo.",
            lambda hands, out: out.label == "scroll",
            hold_seconds=0.8,
        ),
        TutorialStep(
            "6/7 - Clique direito",
            "Encoste polegar + dedo medio sem encostar o indicador.",
            lambda hands, out: out.right_click or out.label == "right-click",
        ),
        TutorialStep(
            "7/7 - Pausar",
            "Abra a palma inteira uma vez. Repita depois para voltar ao modo ativo.",
            lambda hands, out: out.toggle_pause,
        ),
    ]

    print("\n============================================================")
    print(" ASTRA // TUTORIAL DE GESTOS")
    print("============================================================")
    print("A camera vai validar cada gesto antes do modo normal.")
    print("Durante o tutorial, apenas o movimento do ponteiro e enviado ao sistema.")
    print("Cliques/scroll ficam em modo treino para nao apertar nada sem querer.")
    print()

    window = "Astra - Tutorial de Gestos"
    skipped = 0
    try:
        for index, step in enumerate(steps):
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

                # Only pointer movement is live in tutorial so the user can
                # verify that the OS input backend actually works.
                if (
                    index == 1
                    and out.pointer is not None
                    and backend is not None
                    and map_pointer is not None
                ):
                    x, y = map_pointer(out.pointer, screen_w, screen_h)
                    backend.move(x, y)

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
                    f"Reconhecido: {last_label}"
                    if matched
                    else f"Vendo: {last_label} | maos: {len(hands)}"
                )
                _overlay(frame, step.title, step.instruction, status, progress)
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
                    if index == len(steps) - 1:
                        engine.set_paused(False)
                    time.sleep(0.25)
                    break

                if now - started > step.timeout_seconds:
                    print(
                        f"[gestures] nao consegui validar '{step.title}' em "
                        f"{int(step.timeout_seconds)}s."
                    )
                    print(
                        "Dica: afaste um pouco a camera, ilumine a mao e deixe "
                        "todos os dedos dentro do quadro."
                    )
                    return False

        # Final tutorial card.
        for _ in range(70):
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            if mirror:
                frame = cv2.flip(frame, 1)
            cv2.rectangle(frame, (0, 0), (frame.shape[1], frame.shape[0]), (15, 15, 15), -1)
            lines = [
                "Tutorial concluido!",
                "Avancados:",
                "- 2 maos afastando/aproximando = zoom",
                "- girar 2 maos = rotacao",
                "- 3 dedos + movimento lateral = swipe",
                "O modo normal vai iniciar agora.",
            ]
            y = 54
            for line in lines:
                cv2.putText(
                    frame,
                    line,
                    (24, y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.58 if y > 70 else 0.78,
                    (240, 240, 240),
                    2 if y <= 70 else 1,
                    cv2.LINE_AA,
                )
                y += 34
            cv2.imshow(window, frame)
            if cv2.waitKey(25) & 0xFF in (27, ord("q")):
                break

        if skipped == 0:
            mark_tutorial_completed()
        else:
            print(
                f"[gestures] {skipped} etapa(s) foram puladas; "
                "o tutorial sera oferecido novamente depois."
            )
        return True
    except cv2.error as exc:
        print("[gestures] nao foi possivel abrir a janela do tutorial:", exc)
        print("Use um desktop grafico ou rode: astra gestures --no-tutorial --show-camera")
        return False
    finally:
        try:
            cv2.destroyWindow(window)
        except Exception:
            pass
