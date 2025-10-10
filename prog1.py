import numpy as np
import pyModeS as pms
from datetime import datetime, timezone
import pytz
import argparse
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.widgets import Button

MAX_MESSAGE_LENGTH = 14


class ADSBMessage:
    def __init__(self):
        self.timestamp = np.float64(0.0)
        self.message = np.zeros(MAX_MESSAGE_LENGTH, dtype=np.uint8)
        self.message_length = 0


# парсинг строки из файла
def parse_ads_b_line(line):
    parts = line.strip().split()
    if len(parts) < 2:
        return None

    # парсинг времени
    try:
        timestamp = np.float64(parts[0]) # секунды с дробной частью
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

class IcaoGraphs:
    def __init__(self, alt_dict, spd_dict):
        # список бортов, у которых есть данные
        self.icao_list = sorted(set(alt_dict.keys()) | set(spd_dict.keys()))

        if not self.icao_list:
            print("Нет данных для построения графиков")
            return

        self.alt_dict = alt_dict
        self.spd_dict = spd_dict
        self.index = 0

        self.fig, self.ax = plt.subplots(figsize=(10, 5))
        plt.subplots_adjust(bottom=0.23)

        self.ax_prev = plt.axes([0.2, 0.05, 0.2, 0.065])
        self.ax_next = plt.axes([0.6, 0.05, 0.2, 0.065])
        self.btn_prev = Button(self.ax_prev, '<- Предыдущий', color='lightblue', hovercolor='skyblue')
        self.btn_next = Button(self.ax_next, '-> Следующий', color='lightblue', hovercolor='skyblue')

        self.btn_prev.on_clicked(self.prev)
        self.btn_next.on_clicked(self.next)

        # обработчик нажатия с клавиатуры
        self.fig.canvas.mpl_connect('key_press_event', self.on_key)
        
        self.plot_current()
        plt.show()

    def plot_current(self):
        self.ax.clear()

        # текущий ICAO и тип данных
        icao_index = self.index // 2
        show_speed = self.index % 2 == 1
        icao = self.icao_list[icao_index]

        # данные для отображения
        if show_speed:
            data = self.spd_dict.get(icao, [])
            label = "Скорость (узлы)"
            title = f"Изменение скорости борта {icao}"
            self.fig.canvas.manager.set_window_title(f"Скорость борта {icao}")
            data_type = "скорости"
        else:
            data = self.alt_dict.get(icao, [])
            label = "Высота (ft)"
            title = f"Изменение высоты борта {icao}"
            self.fig.canvas.manager.set_window_title(f"Высота борта {icao}")
            data_type = "высоты"

        # если данных нет, отображается сообщение
        if not data:
            self.ax.text(0.5, 0.5, f"Нет данных {data_type} для борта {icao}", 
                        ha='center', va='center', fontsize=14)
            self.ax.set_title(title)
            self.ax.grid(False)
        else:
            # строится график, если есть данные
            times = [timestamp_to_utc(t) for t, _ in data]
            values = [v for _, v in data]

            self.ax.plot(times, values, label=label, linewidth=2)
            self.ax.set_xlabel("Время (UTC)", labelpad=15)
            self.ax.set_ylabel(label, labelpad=15)
            self.ax.set_title(title)
            self.ax.grid(True, linestyle='--', alpha=0.7)
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
            self.fig.autofmt_xdate(rotation=30)
            self.ax.legend()

        self.fig.canvas.draw_idle()

    def next(self, event):
        self.index = (self.index + 1) % (len(self.icao_list) * 2)
        self.plot_current()

    def prev(self, event):
        self.index = (self.index - 1) % (len(self.icao_list) * 2)
        self.plot_current()

    def on_key(self, event):
        if event.key in ['right', 'down']:
            self.next()
        elif event.key in ['left', 'up']:
            self.prev()

# распознование командной строки
parser = argparse.ArgumentParser(description="Обработка ADS-B сообщений из файла.")
parser.add_argument("-f", "--file", required=True, help="Имя входного файла с ADS-B сообщениями")
parser.add_argument("-a", "--aircraft", help="ICAO адрес конкретного борта (если не указан — выводятся данные по всем бортам)")
args = parser.parse_args()

# файл
file_path = args.file
target_icao = args.aircraft.upper() if args.aircraft else None

# словарь для первого и последнего времени для каждого ICAO
icao_times = {}

# словарь для отслеживания координат
icao_coords = {}

# для графиков
icao_altitude = {}
icao_speed = {}

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

            # фильтрация по ICAO
            if target_icao and aa != target_icao:
                continue

            print(f"{msg.timestamp:.9f} {message_spaced} DF {df} ICAO {aa}")

            # обновление времени первого и последнего сообщения по ICAO
            if aa:
                if aa not in icao_times:
                    icao_times[aa] = {"first": msg.timestamp, "last": msg.timestamp}
                else:
                    icao_times[aa]["last"] = msg.timestamp
            # проверка наличия координат
            if aa and has_coords(message_str):
                icao_coords[aa] = True
            # высота
            try:
                alt = pms.adsb.altitude(message_str)
                if alt is not None:
                    icao_altitude.setdefault(aa, []).append((msg.timestamp, alt))
            except:
                pass
            # скорость
            try:
                gs, trk, vs, speed_type = pms.adsb.velocity(message_str)
                if gs is not None:
                    icao_speed.setdefault(aa, []).append((msg.timestamp, gs))
            except:
                pass

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
        
    print(f"\nВсего бортов: {len(icao_times)}\n")

    IcaoGraphs(icao_altitude, icao_speed)

except FileNotFoundError:
    print(f"Файл {file_path} не найден")
except Exception as e:
    print(f"Ошибка чтения файла: {e}")