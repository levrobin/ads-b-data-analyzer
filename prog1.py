import numpy as np
import pyModeS as pms
from datetime import datetime, timezone
import pytz

MAX_MESSAGE_LENGTH = 14


class ADSBMessage:
    def __init__(self):
        self.timestamp = np.int64(0)
        self.message = np.zeros(MAX_MESSAGE_LENGTH, dtype=np.uint8)
        self.message_length = 0


# парсинг строки из файла
def parse_ads_b_line(line):
    parts = line.strip().split()
    if len(parts) < 2:
        return None

    # парсинг времени
    try:
        timestamp = np.int64(float(parts[0]))  # секунды с дробной частью
    except ValueError:
        return None

    # объединение всех чатсей hex сообщения
    message_spaced = ' '.join(parts[1:]).upper().strip()

    message_str = message_spaced.replace(" ", "")

    # проверка корректности hex строки
    if len(message_str) == 0 or not all(c in "0123456789ABCDEF" for c in message_str):
        return None

    msg = ADSBMessage()
    msg.timestamp = timestamp

    # перевод hex в байты
    bytes_list = [int(message_str[i:i + 2], 16) for i in range(0, len(message_str), 2)]
    msg.message_length = min(len(bytes_list), MAX_MESSAGE_LENGTH)
    for i in range(msg.message_length):
        msg.message[i] = np.uint8(bytes_list[i])        
    return msg, message_spaced, message_str


# конвертация timestamp в UTC datetime
def timestamp_to_utc(timestamp):
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)

# функция для проверки передачи сообщением координат
def has_coords(msg_str):
    try:
        # получение DF
        df = pms.df(msg_str)
        # только ADS-B сообщения имеют координаты
        if df != 17:
            return False
        # type code ADS-B сообщения
        tc = pms.adsb.typecode(msg_str)
        # является ли сообщение позиционным (воздушные и наземные сообщения)
        if (5 <= tc <= 8) or (9 <= tc <= 18) or (20 <= tc <= 22):
            return True
        return False
    except:
        return False

# файл
file_path = "2025-10-03.1759515715.074510429.t4433"

# словарь для первого и последнего времени для каждого ICAO
icao_times = {}

# словарь для отслеживания координат
icao_coords = {}

try:
    with open(file_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            # пропуск пустых строк
            if not line.strip():
                continue  

            parsed = parse_ads_b_line(line)
            if parsed is None:
                print(f"Строка {line_num}: ошибка парсинга\n")
                continue

            msg, message_spaced, message_str = parsed

            try:
                # выделение полей через pyModeS
                df = pms.df(message_str)
                aa = pms.icao(message_str)
            except Exception as e:
                print(f"{line_num}: ошибка pyModeS ({e})\n")
                continue

            print(f"{line_num} {msg.timestamp} {message_spaced} DF {df} ICAO {aa}\n")

            # обновление времени первого и последнего сообщения по ICAO
            if aa:
                if aa not in icao_times:
                    icao_times[aa] = {"first": msg.timestamp, "last": msg.timestamp}
                else:
                    icao_times[aa]["last"] = msg.timestamp
            # проверка наличия координат
            if aa and has_coords(message_str):
                icao_coords[aa] = True


    # вывод таблицы
    print("=" * 125)
    print("\t"*5 + "Таблица появления и исчезновения бортов")
    print("=" * 125)
    print(f"{'ICAO':<8} {'Первое по UTC':<22} {'Первое по МСК':<22} {'Последнее по UTC':<22} {'Последнее по МСК':<22} {'Переданы ли координаты':<15}")
    print("=" * 125)

    tz_msk = pytz.timezone('Europe/Moscow')

    for icao, times in sorted(icao_times.items()):
        first_utc = timestamp_to_utc(times["first"])
        last_utc = timestamp_to_utc(times["last"])

        first_msk = first_utc.astimezone(tz_msk)
        last_msk = last_utc.astimezone(tz_msk)

        coord_flag = ""
        if icao_coords.get(icao, False):
            coord_flag = "Да"
        else:
            coord_flag = "Нет"

        print(f"{icao:<8} {first_utc.strftime('%Y-%m-%d %H:%M:%S'):<22} "
              f"{first_msk.strftime('%Y-%m-%d %H:%M:%S'):<22} "
              f"{last_utc.strftime('%Y-%m-%d %H:%M:%S'):<22} "
              f"{last_msk.strftime('%Y-%m-%d %H:%M:%S'):<22} "
              f"{coord_flag:<15}")
        print("-" * 125)
        
    print(f"\nВсего бортов: {len(icao_times)}\n")

except FileNotFoundError:
    print(f"Файл {file_path} не найден")
except Exception as e:
    print(f"Ошибка чтения файла: {e}")