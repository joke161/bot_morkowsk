"""
bot.py — Отказоустойчивый RPA-скрипт для автоматизации фарма в игре «Морковск»
внутри мобильного приложения Ozon через эмулятор LDPlayer 9.

Стек: pyautogui, opencv-python, easyocr, subprocess, schedule, time, logging.
Платформа: Windows 10.
"""

import os
import sys
import time
import random
import logging
import subprocess
from datetime import datetime

import threading

import pyautogui
import schedule
import easyocr
import keyboard

# ──────────────────────────────────────────────────────────────
# Настройки
# ──────────────────────────────────────────────────────────────

# Путь к консольной утилите LDPlayer
LDCONSOLE_PATH = r"C:\LDPlayer\LDPlayer9\ldconsole.exe"

# Количество аккаунтов (индексы: 0, 1, 2)
ACCOUNTS_COUNT = 3

# Время ежедневного запуска фарма (задания обновляются в 00:00)
START_TIME = "01:00"

# ── Anti-Detect (антифрод) ──

# Начальная случайная задержка перед первым аккаунтом (секунды)
INITIAL_DELAY_MIN = 1      # 1 секунда
INITIAL_DELAY_MAX = 300    # 5 минут

# Пауза между аккаунтами после завершения одного и запуском следующего (секунды)
BETWEEN_ACCOUNTS_DELAY_MIN = 10   # 10 секунд
BETWEEN_ACCOUNTS_DELAY_MAX = 180  # 3 минуты

# Директория со скриншотами-шаблонами (относительно скрипта)
IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")

# Директория для хранения локальных моделей EasyOCR (предотвращает интернет-загрузки)
EASYOCR_MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "easyocr_models")

# ── Тайминги ──

# Загрузка целевой страницы после клика «ПОСЕТИТЬ РАЗДЕЛ» (секунды)
TASK_PAGE_LOAD_DELAY = 15

# Пауза после закрытия эмулятора — выгрузка из RAM (секунды)
EMULATOR_QUIT_DELAY = 10

# ── Explicit Wait (динамическое ожидание) ──

# Макс. ожидание загрузки эмулятора (появление иконки Ozon)
EMULATOR_BOOT_TIMEOUT = 120

# Макс. ожидание загрузки Ozon (появление кнопки профиля)
OZON_LOAD_TIMEOUT = 240

# Стандартный таймаут ожидания UI-элементов (секунды)
DEFAULT_ELEMENT_TIMEOUT = 120

# Интервал проверки экрана при динамическом ожидании (секунды)
WAIT_CHECK_INTERVAL = 0.5

# Человекоподобная задержка между кликами: мин / макс (секунды)
HUMAN_DELAY_MIN = 1.5
HUMAN_DELAY_MAX = 3.0

# ── OCR ──

# Кол-во пустых сканов подряд без «Посетите» для завершения OCR-цикла
OCR_EMPTY_SCANS_LIMIT = 2

# Маркеры платных заданий — строго ИГНОРИРУЕМ
PAID_TASK_MARKERS = ["Купите", "заказе", "подборки", "рублей"]

# Маркер бесплатного задания
FREE_TASK_MARKER = "Посетите"

# Маркеры задания "корзина" (Добавьте товар в корзину)
CART_TASK_MARKERS = ["корзину", "Добавьте"]

# ── pyautogui ──

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3

# ──────────────────────────────────────────────────────────────
# Логирование: консоль + файл bot.log
# ──────────────────────────────────────────────────────────────

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Ленивая инициализация EasyOCR (загрузка модели один раз)
# ──────────────────────────────────────────────────────────────

_ocr_reader: easyocr.Reader | None = None


def get_ocr_reader() -> easyocr.Reader | None:
    """
    Возвращает EasyOCR Reader, инициализируя его при первом вызове.
    Настроен на использование локальной папки easyocr_models для работы офлайн.
    """
    global _ocr_reader
    if _ocr_reader is None:
        # Создаем папку, если она не существует
        os.makedirs(EASYOCR_MODELS_DIR, exist_ok=True)

        detector_path = os.path.join(EASYOCR_MODELS_DIR, "craft_mlt_25k.pth")
        recognizer_path = os.path.join(EASYOCR_MODELS_DIR, "cyrillic_g2.pth")

        has_local_models = os.path.exists(detector_path) and os.path.exists(recognizer_path)

        if not has_local_models:
            logger.info("Локальные модели EasyOCR не найдены в %s", EASYOCR_MODELS_DIR)
            logger.info("Попытка автоматического скачивания моделей...")

        try:
            logger.info("Инициализация EasyOCR (ru)… Это может занять время при первом запуске.")
            _ocr_reader = easyocr.Reader(["ru"], gpu=False, model_storage_directory=EASYOCR_MODELS_DIR)
            logger.info("EasyOCR инициализирован успешно.")
        except Exception as exc:
            logger.error("❌ Сбой инициализации EasyOCR (ошибка сети/SSL/блокировка скачивания с серверов)!")
            logger.error("Подробности ошибки: %s", exc)
            logger.error("==========================================================================")
            logger.error("ДЛЯ РАБОТЫ БЕЗ ИНТЕРНЕТА СКАЧАЙТЕ МОДЕЛИ ВРУЧНУЮ:")
            logger.error("1. Скачайте Детектор: https://jaided.ai/read_download/craft_mlt_25k.zip")
            logger.error("   Распакуйте архив и положите файл 'craft_mlt_25k.pth' в папку:")
            logger.error("   %s", EASYOCR_MODELS_DIR)
            logger.error("2. Скачайте Распознаватель (русский): https://jaided.ai/read_download/cyrillic_g2.zip")
            logger.error("   Распакуйте архив и положите файл 'cyrillic_g2.pth' в папку:")
            logger.error("   %s", EASYOCR_MODELS_DIR)
            logger.error("==========================================================================")
            _ocr_reader = None

    return _ocr_reader


# ══════════════════════════════════════════════════════════════
# Вспомогательные функции
# ══════════════════════════════════════════════════════════════


def human_delay(
    min_sec: float = HUMAN_DELAY_MIN,
    max_sec: float = HUMAN_DELAY_MAX,
) -> None:
    """Случайная задержка для имитации поведения человека."""
    delay = round(random.uniform(min_sec, max_sec), 2)
    logger.debug("Пауза %.2f сек.", delay)
    time.sleep(delay)


def img(filename: str) -> str:
    """Возвращает полный путь к файлу шаблона в IMAGES_DIR."""
    return os.path.join(IMAGES_DIR, filename)


def run_ldconsole(command: str, index: int) -> bool:
    """
    Выполняет команду ldconsole.exe для указанного эмулятора асинхронно.

    Возвращает True, если процесс успешно стартовал, False — при ошибке (например, файл не найден).
    Не блокирует выполнение бота, предотвращая зависания на медленных ПК.
    """
    cmd = [LDCONSOLE_PATH, command, "--index", str(index)]
    cmd_str = " ".join(cmd)
    logger.info("CLI (async): %s", cmd_str)

    try:
        # Запуск процесса в фоновом режиме без ожидания завершения и без создания нового окна консоли
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        return True

    except FileNotFoundError:
        logger.error(
            "ldconsole.exe не найден: %s — проверьте LDCONSOLE_PATH.",
            LDCONSOLE_PATH,
        )
        return False
    except Exception as exc:
        logger.exception("Непредвиденная ошибка при вызове ldconsole: %s", exc)
        return False


def find_and_click(
    image_path: str,
    confidence: float = 0.8,
    timeout: int = 30,
    check_interval: float = 2.0,
) -> bool:
    """
    Ищет изображение на экране и кликает в его центр.

    Возвращает True, если клик выполнен; False — если за timeout секунд
    шаблон не обнаружен.
    """
    if not os.path.isfile(image_path):
        logger.error("Файл шаблона не найден: %s", image_path)
        return False

    basename = os.path.basename(image_path)
    logger.info("Ищу шаблон: %s (confidence=%.2f, timeout=%d, interval=%.1f)", basename, confidence, timeout, check_interval)

    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            location = pyautogui.locateCenterOnScreen(image_path, confidence=confidence)
        except pyautogui.ImageNotFoundException:
            location = None
        except Exception as exc:
            logger.warning("Ошибка поиска шаблона '%s': %s", basename, exc)
            location = None

        if location is not None:
            x, y = location
            micro_pause = round(random.uniform(0.3, 0.7), 3)
            logger.info("Найден '%s' -> клик (%d, %d) [пауза %.3f сек]", basename, x, y, micro_pause)
            time.sleep(micro_pause)
            pyautogui.click(x, y)
            return True

        time.sleep(check_interval)

    logger.warning("Шаблон НЕ найден за %d сек: %s", timeout, basename)
    return False


def safe_find_and_click(image_path: str, **kwargs) -> bool:
    """Обёртка find_and_click с перехватом любых исключений."""
    try:
        return find_and_click(image_path, **kwargs)
    except Exception as exc:
        logger.exception("Критическая ошибка при поиске '%s': %s", image_path, exc)
        return False


def take_screenshot() -> str | None:
    """
    Делает скриншот всего экрана и сохраняет во временный файл.
    Возвращает путь к файлу или None при ошибке.
    """
    try:
        screenshot_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "_screenshot_tmp.png",
        )
        screenshot = pyautogui.screenshot()
        screenshot.save(screenshot_path)
        return screenshot_path
    except Exception as exc:
        logger.exception("Ошибка при создании скриншота: %s", exc)
        return None


def emulator_swipe_down() -> None:
    """
    Эмулирует свайп вниз (прокрутку списка) в окне эмулятора.

    Перемещает курсор в центр нижней части экрана, зажимает ЛКМ,
    плавно тянет вверх за ~1 секунду, отпускает.
    """
    try:
        screen_w, screen_h = pyautogui.size()
        # Начинаем из нижней трети экрана по центру
        start_x = screen_w // 2
        start_y = int(screen_h * 0.75)
        end_y = int(screen_h * 0.35)

        logger.info("Свайп вниз: (%d, %d) → (%d, %d)", start_x, start_y, start_x, end_y)

        pyautogui.moveTo(start_x, start_y, duration=0.2)
        pyautogui.mouseDown()
        pyautogui.moveTo(start_x, end_y, duration=1.0)
        pyautogui.mouseUp()

        time.sleep(2)
    except Exception as exc:
        logger.exception("Ошибка при выполнении свайпа: %s", exc)


def wait_for_element(
    image_path: str,
    timeout: int = 45,
    check_interval: float = WAIT_CHECK_INTERVAL,
    confidence: float = 0.8,
) -> bool:
    """
    Динамическое ожидание (Explicit Wait).

    Каждые check_interval секунд проверяет экран на наличие шаблона.
    Как только шаблон найден — возвращает True.
    Если за timeout секунд не найден — возвращает False.

    В отличие от find_and_click, НЕ кликает по элементу.
    """
    if not os.path.isfile(image_path):
        logger.error("wait_for_element: файл не найден: %s", image_path)
        return False

    basename = os.path.basename(image_path)
    logger.info(
        "Ожидание элемента: %s (timeout=%d, interval=%.1f)",
        basename, timeout, check_interval,
    )

    deadline = time.time() + timeout
    attempt = 0

    while time.time() < deadline:
        attempt += 1
        try:
            location = pyautogui.locateCenterOnScreen(image_path, confidence=confidence)
        except pyautogui.ImageNotFoundException:
            location = None
        except Exception as exc:
            logger.warning("wait_for_element: ошибка проверки '%s': %s", basename, exc)
            location = None

        if location is not None:
            elapsed = timeout - (deadline - time.time())
            logger.info(
                "Элемент '%s' появился за %.1f сек (попытка #%d).",
                basename, elapsed, attempt,
            )
            return True

        # Проверка системного предупреждения "Приложение Ozon не отвечает" (кнопка "Подождать")
        if "anr_wait.png" not in basename:
            anr_path = os.path.join(IMAGES_DIR, "anr_wait.png")
            if os.path.isfile(anr_path):
                try:
                    anr_loc = pyautogui.locateCenterOnScreen(anr_path, confidence=0.8)
                    if anr_loc is not None:
                        logger.warning("⚠️ Обнаружена системная ошибка 'Приложение Ozon не отвечает'! Кликаю 'Подождать' (anr_wait.png).")
                        pyautogui.click(anr_loc)
                        time.sleep(1.5)
                except Exception:
                    pass

        time.sleep(check_interval)

    logger.warning(
        "Элемент '%s' НЕ появился за %d сек (%d попыток).",
        basename, timeout, attempt,
    )
    return False


# ══════════════════════════════════════════════════════════════
# Kill-Switch: экстренное завершение по Ctrl+Shift+K
# ══════════════════════════════════════════════════════════════


# Глобальная переменная для отслеживания текущего индекса эмулятора
_current_emulator_index: int | None = None


def emergency_shutdown() -> None:
    """
    Аварийная остановка бота:
    1. Закрывает активный эмулятор через ldconsole quit.
    2. Логирует: "[!] Бот экстренно остановлен пользователем."
    3. Блокирует закрытие консоли через input() для чтения логов.
    4. Завершает процесс через sys.exit(0).
    """
    logger.warning("⚠ Аварийная остановка бота! (Kill-Switch: Ctrl+Shift+K)")

    # Закрываем активный эмулятор (если известен)
    if _current_emulator_index is not None:
        try:
            run_ldconsole("quit", _current_emulator_index)
            logger.info("Активный эмулятор #%d закрыт.", _current_emulator_index)
        except Exception as exc:
            logger.error(
                "Ошибка при аварийном закрытии эмулятора #%d: %s",
                _current_emulator_index, exc,
            )
    else:
        logger.warning("Индекс активного эмулятора неизвестен — пропускаю quit.")

    logger.warning("[!] Бот экстренно остановлен пользователем.")
    # Используем os._exit(0) для немедленного убийства всего процесса, включая основной поток
    import os
    os._exit(0)


def register_kill_switch() -> None:
    """
    Регистрирует глобальный хоткей Ctrl+Shift+K в фоновом потоке.

    При нажатии комбинации вызывается emergency_shutdown().
    """
    def _listener() -> None:
        keyboard.add_hotkey("ctrl+shift+k", emergency_shutdown)
        logger.info("Kill-Switch зарегистрирован: Ctrl+Shift+K")
        # Блокируем поток, чтобы слушатель оставался активным
        keyboard.wait()

    thread = threading.Thread(target=_listener, daemon=True)
    thread.start()


# ══════════════════════════════════════════════════════════════
# Идемпотентный сброс состояния (Safe State Reset)
# ══════════════════════════════════════════════════════════════


def safe_state_reset_to_tasks() -> bool:
    """
    Гарантированно возвращает бота в список заданий из любой глубины
    навигации Ozon. НЕ использует ESC.

    Цепочка: click_profile -> enter_morkovsk -> open_tasks
    """
    logger.info("── Safe State Reset: возврат в список заданий ──")

    steps = [
        ("click_profile.png", "Профиль"),
        ("enter_morkovsk.png", "Вход в Морковск"),
        ("open_tasks.png", "Открытие заданий"),
    ]

    for filename, description in steps:
        human_delay()
        logger.info("Reset → %s", description)
        if not safe_find_and_click(img(filename), timeout=DEFAULT_ELEMENT_TIMEOUT):
            logger.warning("Reset: не удалось выполнить шаг '%s'", description)
            return False

    human_delay()
    return True


# ══════════════════════════════════════════════════════════════
# Смарт-блок заданий (EasyOCR + идемпотентный сброс)
# ══════════════════════════════════════════════════════════════


def process_tasks_with_ocr() -> bool:
    """
    Сканирует экран через EasyOCR, находит и выполняет ВСЕ бесплатные задания
    («Посетите») пока они полностью не пропадут из списка.

    - Платные задания (маркеры из PAID_TASK_MARKERS) — игнорируются.
    - Если бесплатных заданий на экране нет — свайп вниз + повтор.
    - Завершение: OCR_EMPTY_SCANS_LIMIT пустых сканов подряд без «Посетите».
    - При провале возврата в список заданий возвращает False (→ эмулятор закроется).
    - Интервал между сканами: 2 секунды (WAIT_CHECK_INTERVAL).

    Возвращает True при успехе, False при критической ошибке навигации.
    """
    logger.info("╔══ Смарт-блок заданий (EasyOCR) ══╗")

    reader = get_ocr_reader()
    if reader is None:
        logger.error("EasyOCR недоступен (Reader не инициализирован). Смарт-блок заданий пропущен.")
        return True

    # Счётчик последовательных сканов без бесплатных заданий
    consecutive_empty_scans = 0
    iteration = 0

    while True:
        iteration += 1
        logger.info("── OCR итерация #%d ──", iteration)

        # Пауза перед сканом (даём UI время отрисоваться)
        time.sleep(WAIT_CHECK_INTERVAL)

        # 1. Делаем скриншот
        screenshot_path = take_screenshot()
        if screenshot_path is None:
            logger.error("Не удалось сделать скриншот — пропускаю итерацию.")
            continue

        # 2. Распознаём текст
        try:
            results = reader.readtext(screenshot_path)
        except Exception as exc:
            logger.exception("Ошибка EasyOCR: %s", exc)
            continue

        logger.info("Распознано %d текстовых блоков.", len(results))

        # 3. Ищем первое доступное бесплатное задание
        found_free_task = False

        for bbox, text, conf in results:
            text_stripped = text.strip()

            # Платные задания — ИГНОРИРУЕМ
            if any(marker in text_stripped for marker in PAID_TASK_MARKERS):
                logger.debug("Платное задание (игнорируем): '%s'", text_stripped)
                continue

            # ── Задание "корзина" (Добавьте товар в корзину) ──
            if any(marker in text_stripped for marker in CART_TASK_MARKERS):
                logger.info("🛒 Задание 'корзина' найдено: '%s' (conf=%.2f)", text_stripped, conf)
                found_free_task = True
                consecutive_empty_scans = 0

                try:
                    # 1. Кликаем по координатам слова
                    xs = [point[0] for point in bbox]
                    ys = [point[1] for point in bbox]
                    center_x = int(sum(xs) / len(xs))
                    center_y = int(sum(ys) / len(ys))
                    logger.info("Клик по тексту задания 'корзина': (%d, %d)", center_x, center_y)
                    pyautogui.click(center_x, center_y)

                    # 2. Ждём появления окна задания
                    time.sleep(random.uniform(2.0, 3.0))

                    # 3. Ищем кнопку перехода к товарам и кликаем
                    if not safe_find_and_click(img("go_to_products.png"), timeout=DEFAULT_ELEMENT_TIMEOUT):
                        logger.warning("Кнопка 'go_to_products.png' не найдена — пропускаю задание корзины.")
                        if not safe_state_reset_to_tasks():
                            return False
                        break

                    # 4. Ждём прогрузки каталога
                    logger.info("Жёсткая пауза 15 сек (прогрузка каталога)…")
                    time.sleep(15)

                    # 5. Свайп вниз (обновляем ленту)
                    emulator_swipe_down()

                    # 6. Ищем кнопку "Добавить в корзину" и кликаем
                    if safe_find_and_click(img("add_to_cart.png"), timeout=DEFAULT_ELEMENT_TIMEOUT):
                        logger.info("✅ Товар добавлен в корзину!")
                    else:
                        logger.warning("Кнопка 'add_to_cart.png' не найдена — возможно, товар недоступен.")

                    # 7. State Reset: возврат через профиль в список заданий
                    if not safe_state_reset_to_tasks():
                        logger.warning("Не удалось вернуться в список заданий после задания 'корзина'.")
                        return False

                except Exception as exc:
                    logger.exception("Ошибка при выполнении задания 'корзина': %s", exc)
                    if not safe_state_reset_to_tasks():
                        return False

                # 8. Задание корзины всегда последнее — завершаем OCR-цикл
                logger.info("Задание 'корзина' выполнено — это последнее задание, завершаю OCR-цикл.")
                logger.info("╘══ Смарт-блок заданий завершён ══╝")
                return True

            # Бесплатное задание найдено
            if FREE_TASK_MARKER in text_stripped:
                logger.info("✓ Бесплатное задание: '%s' (conf=%.2f)", text_stripped, conf)
                found_free_task = True
                consecutive_empty_scans = 0

                try:
                    # Вычисляем центр bounding box и кликаем
                    xs = [point[0] for point in bbox]
                    ys = [point[1] for point in bbox]
                    center_x = int(sum(xs) / len(xs))
                    center_y = int(sum(ys) / len(ys))

                    logger.info("Клик по тексту задания: (%d, %d)", center_x, center_y)
                    pyautogui.click(center_x, center_y)
                    time.sleep(WAIT_CHECK_INTERVAL)

                    # 4. Нажимаем «ПОСЕТИТЬ РАЗДЕЛ»
                    if safe_find_and_click(img("complete_task.png"), timeout=DEFAULT_ELEMENT_TIMEOUT):
                        logger.info(
                            "Кнопка 'ПОСЕТИТЬ РАЗДЕЛ' нажата. Ожидаю загрузку страницы ( click_profile.png, макс %d сек)…",
                            DEFAULT_ELEMENT_TIMEOUT,
                        )
                        wait_for_element(img("click_profile.png"), timeout=DEFAULT_ELEMENT_TIMEOUT, check_interval=0.5)
                    else:
                        logger.warning("Кнопка 'ПОСЕТИТЬ РАЗДЕЛ' не найдена — пропускаю задание.")

                    # 5. Возврат в список заданий
                    if not safe_state_reset_to_tasks():
                        logger.warning(
                            "Не удалось вернуться в список заданий после %d итераций. "
                            "Прерываю OCR-цикл — закрываю эмулятор.",
                            iteration,
                        )
                        return False

                except Exception as exc:
                    logger.exception(
                        "Ошибка при выполнении задания '%s': %s", text_stripped, exc
                    )
                    # Пытаемся восстановиться
                    if not safe_state_reset_to_tasks():
                        logger.warning("Safe State Reset не удался — прерываю цикл.")
                        return False

                # Задание выполнено — делаем свежий скриншот с начала
                break

        # 6. Нет бесплатных заданий на экране
        if not found_free_task:
            consecutive_empty_scans += 1
            logger.info(
                "Бесплатных заданий не найдено (пустых сканов подряд: %d/%d).",
                consecutive_empty_scans,
                OCR_EMPTY_SCANS_LIMIT,
            )

            if consecutive_empty_scans >= OCR_EMPTY_SCANS_LIMIT:
                logger.info(
                    "Бесплатные задания отсутствуют или выполнены. Завершаю OCR-цикл."
                )
                break

            logger.info("Выполняю 1 контрольную проверку экрана без свайпа…")

    logger.info("╚══ Смарт-блок заданий завершён ══╝")
    return True


# ══════════════════════════════════════════════════════════════
# Основная логика фарма для одного аккаунта
# ══════════════════════════════════════════════════════════════


def run_farm_for_emulator(index: int) -> bool:
    """
    Полный цикл фарма для одного эмулятора (аккаунта):

    1. Запуск эмулятора (ldconsole launch) + динамическое ожидание иконки Ozon.
    2. Открытие Ozon (клик по иконке) + динамическое ожидание загрузки.
    3. Вход в игру: profile → morkovsk → basket → roulette → close basket → tasks.
    4. Сбор ежедневной награды (claim_daily) — ДО скроллинга.
    5. Смарт-блок заданий (EasyOCR) с Early Exit.
    6. Закрытие эмулятора (ldconsole quit) + ожидание 10 сек.

    Закрытие эмулятора гарантируется блоком finally.
    Все ожидания используют Explicit Wait (wait_for_element) вместо жёстких sleep.
    """
    logger.info("═" * 60)
    logger.info("  ФАРМ АККАУНТА #%d", index)
    logger.info("═" * 60)

    # Устанавливаем глобальный индекс для kill-switch
    global _current_emulator_index
    _current_emulator_index = index

    # ── 1. Запуск эмулятора ──
    if not run_ldconsole("launch", index):
        logger.error("Не удалось запустить эмулятор #%d — ПРОПУСК.", index)
        return False

    # Динамическое ожидание загрузки Android (ждём появления иконки Ozon)
    logger.info(
        "Ожидание загрузки Android (ищу open_ozon.png, макс %d сек)…",
        EMULATOR_BOOT_TIMEOUT,
    )
    if not wait_for_element(img("open_ozon.png"), timeout=EMULATOR_BOOT_TIMEOUT):
        logger.warning(
            "Аккаунт %d недоступен, разлогинен или завис. Пропускаю.",
            index,
        )
        run_ldconsole("quit", index)
        time.sleep(5)
        return False

    try:
        # ── 2. Открытие Ozon ──
        logger.info("── Шаг: Открытие Ozon ──")
        if not safe_find_and_click(img("open_ozon.png"), timeout=10):
            logger.warning(
                "Аккаунт %d недоступен, разлогинен или завис. Пропускаю.",
                index,
            )
            return False

        # Динамическое ожидание загрузки Ozon (ждём появления кнопки профиля)
        logger.info(
            "Ожидание загрузки Ozon (ищу click_profile.png, макс %d сек)…",
            OZON_LOAD_TIMEOUT,
        )
        if not wait_for_element(img("click_profile.png"), timeout=OZON_LOAD_TIMEOUT):
            logger.warning(
                "Аккаунт %d недоступен, разлогинен или завис. Пропускаю.",
                index,
            )
            return False

        # ── 3. Вход в игру: цепочка кликов ──
        entry_chain_pre_roulette = [
            ("click_profile.png", "Профиль"),
            ("enter_morkovsk.png", "Вход в Морковск"),
            ("open_basket.png", "Открытие Лукошка"),
        ]

        for filename, description in entry_chain_pre_roulette:
            human_delay()
            logger.info("── Шаг: %s ──", description)
            if not safe_find_and_click(img(filename), timeout=DEFAULT_ELEMENT_TIMEOUT):
                if filename in ("click_profile.png", "enter_morkovsk.png"):
                    logger.warning(
                        "Аккаунт %d недоступен, разлогинен или завис. Пропускаю.",
                        index,
                    )
                    return False
                logger.warning("Шаг '%s' не выполнен — продолжаю.", description)

        # ── Шаг: ПОЙМАТЬ ПРИЗ (рулетка) ──
        human_delay()
        logger.info("── Шаг: ПОЙМАТЬ ПРИЗ (рулетка) ──")
        if safe_find_and_click(img("spin_roulette.png"), timeout=DEFAULT_ELEMENT_TIMEOUT):
            logger.info("Кнопка 'ПОЙМАТЬ ПРИЗ' нажата. Жёсткое ожидание 20 сек (анимация рулетки)…")
            time.sleep(20)
        else:
            logger.warning("Шаг 'ПОЙМАТЬ ПРИЗ (рулетка)' не выполнен — продолжаю.")

        # ── Шаг: Закрытие Лукошка (с интервалом 2 сек, таймаут 30 сек) ──
        human_delay()
        logger.info("── Шаг: Закрытие Лукошка ──")
        if not safe_find_and_click(img("close_basket.png"), timeout=30, check_interval=2):
            logger.warning("Шаг 'Закрытие Лукошка' не выполнен за 30 сек — продолжаю.")

        # ── Шаг: Открытие заданий (с интервалом 2 сек, таймаут 30 сек) ──
        human_delay()
        logger.info("── Шаг: Открытие заданий ──")
        if not safe_find_and_click(img("open_tasks.png"), timeout=30, check_interval=2):
            logger.warning("Шаг 'Открытие заданий' не выполнен за 30 сек — продолжаю.")

        # ── 4. Сбор ежедневной награды (ДО скроллинга, пока кнопка на экране) ──
        logger.info("── Шаг: Сбор ежедневной награды ──")
        human_delay()
        if safe_find_and_click(img("claim_daily.png"), timeout=10):
            logger.info("Ежедневная награда собрана!")
        else:
            logger.info("Кнопка 'ЗАБРАТЬ' не найдена (возможно, уже собрана).")

        # ── 5. Смарт-блок заданий (EasyOCR) ──
        try:
            ok = process_tasks_with_ocr()
            if not ok:
                logger.warning(
                    "Смарт-блок вернул ошибку навигации для #%d — "
                    "завершаю фарм аккаунта.",
                    index,
                )
                return False
        except Exception as exc:
            logger.exception("Ошибка в смарт-блоке заданий: %s", exc)

        return True

    except Exception as exc:
        logger.exception("Критическая ошибка фарма на эмуляторе #%d: %s", index, exc)
        return False

    finally:
        # ── 6. Гарантированное закрытие эмулятора ──
        logger.info("Teardown: закрываю эмулятор #%d…", index)
        if not run_ldconsole("quit", index):
            logger.error(
                "Не удалось закрыть эмулятор #%d — может потребоваться ручное закрытие.",
                index,
            )

        logger.info("Ожидание выгрузки из RAM: %d сек…", EMULATOR_QUIT_DELAY)
        time.sleep(EMULATOR_QUIT_DELAY)

        # Сбрасываем глобальный индекс
        _current_emulator_index = None


# ══════════════════════════════════════════════════════════════
# Главная функция: цикл по всем аккаунтам
# ══════════════════════════════════════════════════════════════

# Дата последнего запуска фарма (защита от двойного запуска в один день)
_last_farm_date: str | None = None


def run_farm(force_now: bool = False) -> None:
    """
    Послеводательно обрабатывает все аккаунты (эмуляторы 0..ACCOUNTS_COUNT-1).

    Единичный сбой одного аккаунта не влияет на обработку остальных.
    Защита от двойного запуска: не более одного цикла в сутки.
    """
    global _last_farm_date

    today = datetime.now().strftime("%Y-%m-%d")
    if _last_farm_date == today:
        logger.info(
            "Фарм уже выполнялся сегодня (%s). Пропускаю до завтра.", today
        )
        return

    start_time = datetime.now()
    logger.info("╔" + "═" * 58 + "╗")
    logger.info(
        "║  ЗАПУСК ФАРМ-ЦИКЛА  —  %s  ║",
        start_time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    logger.info("╚" + "═" * 58 + "╝")

    results: dict[int, bool] = {}

    # ── Anti-Detect: начальная случайная задержка перед первым аккаунтом (только если не форсированный запуск) ──
    if not force_now:
        initial_delay = random.randint(INITIAL_DELAY_MIN, INITIAL_DELAY_MAX)
        logger.info(
            "⏳ Начальная задержка %.1f сек для сдвига времени старта…",
            initial_delay,
        )
        time.sleep(initial_delay)
    else:
        logger.info("⚡ Форсированный запуск: начальная задержка пропущена.")

    for idx in range(ACCOUNTS_COUNT):
        try:
            # ── Anti-Detect: пауза между аккаунтами (кроме первого) ──
            if idx > 0:
                between_delay = random.randint(BETWEEN_ACCOUNTS_DELAY_MIN, BETWEEN_ACCOUNTS_DELAY_MAX)
                logger.info(
                    "⏳ Ожидание %.1f сек перед запуском аккаунта #%d "
                    "для имитации действий человека…",
                    between_delay, idx,
                )
                time.sleep(between_delay)

            success = run_farm_for_emulator(idx)
            results[idx] = success
            if not success:
                logger.info("Аккаунт #%d пропущен. Перехожу к следующему.", idx)
                continue
        except KeyboardInterrupt:
            logger.info("Прервано пользователем (Ctrl+C).")
            raise
        except Exception as exc:
            logger.exception("Необработанная ошибка для эмулятора #%d: %s", idx, exc)
            results[idx] = False
            # Гарантированно закрываем зависший эмулятор
            run_ldconsole("quit", idx)
            time.sleep(5)
            continue

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("─" * 60)
    logger.info("Итоги цикла (%.1f сек):", elapsed)
    for idx, ok in results.items():
        status = "✓ OK" if ok else "✗ ОШИБКА"
        logger.info("  Аккаунт #%d: %s", idx, status)
    logger.info("Следующий запуск завтра в %s.", START_TIME)
    logger.info("─" * 60)

    # Запоминаем дату запуска (защита от двойного запуска)
    _last_farm_date = datetime.now().strftime("%Y-%m-%d")


# ══════════════════════════════════════════════════════════════
# Точка входа
# ══════════════════════════════════════════════════════════════


def main() -> None:
    """Запуск с выбором: немедленно или по расписанию."""
    logger.info("╔══════════════════════════════════════════════════╗")
    logger.info("║     Бот Морковск v4.0 — Запущен                 ║")
    logger.info("║     Kill-Switch: Ctrl+Shift+K                   ║")
    logger.info("╚══════════════════════════════════════════════════╝")
    logger.info("Расписание: ежедневно в %s", START_TIME)
    logger.info("Антифрод: старт +%d–%d сек, между аккаунтами %d–%d сек",
        INITIAL_DELAY_MIN, INITIAL_DELAY_MAX,
        BETWEEN_ACCOUNTS_DELAY_MIN, BETWEEN_ACCOUNTS_DELAY_MAX,
    )
    logger.info("Аккаунтов: %d (индексы 0..%d)", ACCOUNTS_COUNT, ACCOUNTS_COUNT - 1)
    logger.info("ldconsole: %s", LDCONSOLE_PATH)
    logger.info("Шаблоны: %s", IMAGES_DIR)
    logger.info("Для остановки: Ctrl+C или Ctrl+Shift+K (аварийная).")
    logger.info("")

    # Регистрация Kill-Switch в фоновом потоке
    register_kill_switch()

    # ── Выбор режима запуска ──
    print("=" * 50)
    print("  Выберите режим запуска:")
    print("  [1] Запустить фарм СЕЙЧАС (по умолчанию)")
    print("  [2] Ждать расписание (%s)" % START_TIME)
    print("=" * 50)

    try:
        choice = input("  Ваш выбор (1/2): ").strip()
    except (EOFError, KeyboardInterrupt):
        choice = "1"

    if choice == "2":
        logger.info("Режим: ожидание расписания. Фарм запустится в %s.", START_TIME)
    else:
        logger.info("Режим: немедленный запуск.")
        run_farm(force_now=True)

    # Ежедневный планировщик
    schedule.every().day.at(START_TIME).do(run_farm)

    # Бесконечный цикл ожидания расписания
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем (Ctrl+C). Выход.")
        sys.exit(0)


if __name__ == "__main__":
    main()
