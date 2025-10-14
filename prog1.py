import numpy as np
import pyModeS as pms
from datetime import datetime, timezone
import pytz
import argparse
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.widgets import Button

MAX_MESSAGE_LENGTH = 14
DEFAULT_FILE = "2025-10-03.1759515715.074510429.t4433"

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
        # только ADS-B сообщения имеют координаты DF=17 и DF=18
        if df not in [17, 18]:
            return False
        # type code ADS-B сообщения
        tc = pms.adsb.typecode(msg_str)
        # является ли сообщение позиционным (воздушные и наземные сообщения)
        if (5 <= tc <= 8) or (9 <= tc <= 18) or (20 <= tc <= 22):
            return True
        return False
    except:
        return False

# функция для получения высоты
def get_altitude(msg_str):
    try:
        df = pms.df(msg_str)
        # только ADS-B сообщения (DF=17 и DF=18)
        if df not in [17, 18]:
            return None
        tc = pms.adsb.typecode(msg_str)
        if 9 <= tc <= 18:
            alt = pms.adsb.altitude(msg_str)
            return alt
        return None
    except:
        return None

# функция для получения скорости
def get_velocity(msg_str):
    try:
        df = pms.df(msg_str)
        # только ADS-B сообщения (DF=17 и DF=18)
        if df not in [17, 18]:
            return None
        tc = pms.adsb.typecode(msg_str)
        if tc == 19:
            result = pms.adsb.velocity(msg_str)
            if result and result[0] is not None:
                return result[0]
        return None
    except:
        return None

# функция для получения выбранной высоты из сообщения типа 29 подтипа 1
def get_selected_altitude(msg_str):
    try:
        if len(msg_str) < 28:
            return None

        df = pms.df(msg_str)
        if df not in [17, 18]:
            return None

        tc = pms.adsb.typecode(msg_str)
        if tc != 29:
            return None

        # полезная нагрузка после DF (5 бит) и ICAO (24 бита)
        payload_hex = msg_str[8:]  
        payload_bin = bin(int(payload_hex, 16))[2:].zfill(80)  # 80 бит полезной нагрузки

        # подтип — биты 33–35 (индексы 32–35)
        subtype = int(payload_bin[32:35], 2)
        if subtype != 1:
            return None

        # выбранная высота — биты 34–45 (индексы 33–45)
        sel_alt_raw = int(payload_bin[33:45], 2)
        selected_alt = sel_alt_raw * 32  # шаг 32 фута

        # режимы — биты 46–51 (индексы 45–51)
        modes = set()
        if len(payload_bin) >= 52:
            if payload_bin[45] == '1': modes.add("AP")     # Autopilot
            if payload_bin[46] == '1': modes.add("VNAV")   # VNAV
            if payload_bin[47] == '1': modes.add("ALT")    # Alt Hold
            if payload_bin[48] == '1': modes.add("APP")    # Approach
            if payload_bin[49] == '1': modes.add("LNAV")   # LNAV
            if payload_bin[50] == '1': modes.add("TCAS")   # TCAS

        if -2000 <= selected_alt <= 50000:
            return selected_alt, modes
        return None

    except Exception as e:
        print(f"Ошибка извлечения выбранной высоты: {e}")
        return None

# функция для получения номера рейса
def get_callsign(msg_str):
    try:
        df = pms.df(msg_str)
        # только ADS-B сообщения
        if df not in [17, 18]:
            return None
        tc = pms.adsb.typecode(msg_str)
        # номер рейса передается в сообщениях с типом 1-4
        if 1 <= tc <= 4:
            callsign = pms.adsb.callsign(msg_str)
            if not callsign:
                return None
            # удаление подчеркивания, пробелы и неалфавитные символы
            clean = ''.join(c for c in callsign if c.isalnum())
            return clean
        return None
    except:
        return None

class IcaoGraphs:
    def __init__(self, alt_dict, spd_dict, adsb_icao_list, icao_callsigns, icao_sel_alt):
        # список бортов, у которых есть данные и которые передают ADS-B сообщения
        self.icao_list = sorted(set(alt_dict.keys()) | set(spd_dict.keys()))
        # только те ICAO, которые есть в списке ADS-B бортов
        self.icao_list = [icao for icao in self.icao_list if icao in adsb_icao_list]

        if not self.icao_list:
            print("Нет данных для построения графиков")
            return

        self.alt_dict = alt_dict
        self.spd_dict = spd_dict
        self.icao_callsigns = icao_callsigns  # словарь с номерами рейсов
        self.sel_alt_dict = icao_sel_alt if icao_sel_alt else {}
        self.index = 0

        # словари для хранения масштаба для каждого борта и типа данных
        self.alt_ylim = {}  # для высот
        self.spd_ylim = {}  # для скоростей
        
        # начальные масштабы по умолчанию
        self.default_alt_ylim = (-1200, 40000)
        self.default_spd_ylim = (0, 500)

        self.fig, self.ax = plt.subplots(figsize=(12, 6))
        plt.subplots_adjust(bottom=0.23)

        self.ax_prev = plt.axes([0.2, 0.05, 0.2, 0.065])
        self.ax_next = plt.axes([0.6, 0.05, 0.2, 0.065])
        self.btn_prev = Button(self.ax_prev, '<- Предыдущий', color='lightblue', hovercolor='skyblue')
        self.btn_next = Button(self.ax_next, '-> Следующий', color='lightblue', hovercolor='skyblue')

        self.btn_prev.on_clicked(self.prev)
        self.btn_next.on_clicked(self.next)

        # обработчик нажатия с клавиатуры
        self.fig.canvas.mpl_connect('key_press_event', self.on_key)
        # обработчик колесика мыши для масштабирования
        self.fig.canvas.mpl_connect('scroll_event', self.on_scroll)
        
        # флаг для отслеживания активного режима навигации
        self.current_tool = None
        
        # включение навигации
        self.fig.canvas.manager.toolbar.update()

        # режим перетаскивания стоит по умолчанию
        if hasattr(self.fig.canvas, 'toolbar') and self.fig.canvas.toolbar is not None:
            # активация инструмента перетаскивания
            self.fig.canvas.toolbar.pan()
            self.current_tool = 'pan'
        
        self.plot_current()
        plt.show()

    # текущий ICAO и тип данных
    def get_current_icao_and_type(self):
        icao_index = self.index // 2
        show_speed = self.index % 2 == 1
        icao = self.icao_list[icao_index]
        return icao, show_speed

    # текущие пределы масштабирования для данного борта и типа данных
    def get_current_ylim(self, icao, show_speed):
        if show_speed:
            return self.spd_ylim.get(icao, self.default_spd_ylim)
        else:
            return self.alt_ylim.get(icao, self.default_alt_ylim)

    # пределы масштабирования для данного борта и типа данных
    def set_current_ylim(self, icao, show_speed, ylim):
        if show_speed:
            self.spd_ylim[icao] = ylim
        else:
            self.alt_ylim[icao] = ylim

    # текущее состояние инструментов навигации
    def current_tool_state(self):
        if hasattr(self.fig.canvas, 'toolbar') and self.fig.canvas.toolbar is not None:
            # текущий активный инструмент
            if hasattr(self.fig.canvas.toolbar, '_active'):
                self.current_tool = self.fig.canvas.toolbar._active
            else:
                self.current_tool = None

    # восстановления состояния инструментов навигации
    def restore_tool_state(self):
        if hasattr(self.fig.canvas, 'toolbar') and self.fig.canvas.toolbar is not None:
            # предыдущий активный инструмент
            if self.current_tool and hasattr(self.fig.canvas.toolbar, self.current_tool):
                # активация инструмента
                getattr(self.fig.canvas.toolbar, self.current_tool).trigger()

    def plot_current(self):
        # состояние инструментов перед перерисовкой
        self.current_tool_state()
        
        self.ax.clear()

        icao, show_speed = self.get_current_icao_and_type()

        # получение номера рейса для текущего ICAO
        callsign = self.icao_callsigns.get(icao, "N/A")

        # получение активных режимов для заголовка
        modes_key = f"{icao}_modes"
        modes = self.icao_callsigns.get(modes_key, set())
        mode_str = ""
        if modes:
            mode_str = " (" + ", ".join(sorted(modes)) + ")"
        
        # данные для отображения
        if show_speed:
            data = self.spd_dict.get(icao, [])
            label = "Скорость (узлы)"
            title = f"Изменение скорости борта "
            if callsign != "N/A":
                title += f"{callsign}"
            title += f" ({icao})"
            self.fig.canvas.manager.set_window_title(f"Скорость борта {icao} - {callsign}")
            data_type = "скорости"
        else:
            data = self.alt_dict.get(icao, [])
            label = "Высота (ft)"
            title = f"Изменение высоты борта "
            if callsign != "N/A":
                title += f"{callsign}"
            title += f" ({icao}){mode_str}"
            self.fig.canvas.manager.set_window_title(f"Высота борта {icao} - {callsign}")
            data_type = "высоты"

        # получение текущего масштаба
        current_ylim = self.get_current_ylim(icao, show_speed)

        # если данных нет, отображается сообщение
        if show_speed:
            if not data:
                self.ax.text(0.5, 0.5, f"Нет данных {data_type} для борта {icao}", 
                            ha='center', va='center', fontsize=14)
                self.ax.set_title(title)
                self.ax.grid(False)
            else:
                # строится график скорости, если есть данные
                data_sorted = sorted(data)
                times = [timestamp_to_utc(t) for t, _ in data_sorted]
                values = [v for _, v in data_sorted]

                self.ax.plot(times, values, label='Скорость', linewidth=2, color='green')
                self.ax.set_xlabel("Время (UTC)", labelpad=15)
                self.ax.set_ylabel(label, labelpad=15)
                self.ax.set_title(title)
                self.ax.grid(True, linestyle='--', alpha=0.7)
                self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
                self.fig.autofmt_xdate(rotation=30)
                
                # добавление номера рейса в легенду
                if callsign != "N/A":
                    self.ax.legend([f"Скорость - {callsign}"])
                else:
                    self.ax.legend(["Скорость"])

                # установка сохраненного масштаба
                self.ax.set_ylim(current_ylim)
        else:
            # график высоты
            if not data and icao not in self.sel_alt_dict:
                self.ax.text(0.5, 0.5, f"Нет данных {data_type} для борта {icao}", 
                            ha='center', va='center', fontsize=14)
                self.ax.set_title(title)
                self.ax.grid(False)
            else:
                # отображение барометрической высоты
                if data:
                    data_sorted = sorted(data)
                    times = [timestamp_to_utc(t) for t, _ in data_sorted]
                    values = [v for _, v in data_sorted]
                    self.ax.plot(times, values, label='Барометрическая высота', 
                               linewidth=2, color='blue', marker='o', markersize=3)

                # отображение выбранной высоты
                if icao in self.sel_alt_dict:
                    sel_data = sorted(self.sel_alt_dict[icao])
                    sel_times = [timestamp_to_utc(t) for t, _ in sel_data]
                    sel_values = [v for _, v in sel_data]
                    self.ax.plot(sel_times, sel_values, label='Выбранная высота', 
                               linewidth=2, color='red', marker='s', markersize=4, linestyle='--')

                self.ax.set_xlabel("Время (UTC)", labelpad=15)
                self.ax.set_ylabel(label, labelpad=15)
                self.ax.set_title(title)
                self.ax.grid(True, linestyle='--', alpha=0.7)
                self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
                self.fig.autofmt_xdate(rotation=30)
                
                # создание легенд с обоими типами данных
                legend_items = []
                if data:
                    legend_items.append('Барометрическая высота')
                if icao in self.sel_alt_dict:
                    legend_items.append('Выбранная высота')
                
                if callsign != "N/A":
                    legend_title = f"{callsign}"
                else:
                    legend_title = None
                
                self.ax.legend(legend_items, title=legend_title)

                # установка сохраненного масштаба
                self.ax.set_ylim(current_ylim)


        # восстановление состояния инструментов после перерисовки
        self.restore_tool_state()
        
        self.fig.canvas.draw_idle()

    # масштабирование
    def on_scroll(self, event):
        # масштабирование для графиков
        if event.inaxes == self.ax:
            # базовый шаг масштабирования
            scale_factor = 1.1
            
            # текущие границы
            ylim = self.ax.get_ylim()
            y_range = ylim[1] - ylim[0]
            
            # центр масштабирования - положение курсора или центр графика
            if event.ydata is not None:
                mouse_y = event.ydata
            else:
                mouse_y = (ylim[0] + ylim[1]) / 2
            
            if event.button == 'down':
                # увеличение - увеличение диапазона
                new_range = y_range / scale_factor
            elif event.button == 'up':
                # уменьшение - уменьшение диапазона
                new_range = y_range * scale_factor
            else:
                return
            
            # новые границы с сохранением позиции мыши
            new_low = mouse_y - (mouse_y - ylim[0]) * (new_range / y_range)
            new_high = new_low + new_range
            
            # ограничение минимального масштаба
            min_range = 50  # минимальный диапазон 50 единиц
            if new_range >= min_range:
                self.ax.set_ylim(new_low, new_high)
                
                # сохранение нового масштаба
                icao, show_speed = self.get_current_icao_and_type()
                self.set_current_ylim(icao, show_speed, (new_low, new_high))
                
                self.fig.canvas.draw_idle()

    def next(self, event=None):
        self.index = (self.index + 1) % (len(self.icao_list) * 2)
        self.plot_current()

    def prev(self, event=None):
        self.index = (self.index - 1) % (len(self.icao_list) * 2)
        self.plot_current()

    def on_key(self, event):
        if event.key in ['right', 'down']:
            self.next()
        elif event.key in ['left', 'up']:
            self.prev()

# распознование командной строки
parser = argparse.ArgumentParser()
parser.add_argument("-f", "--file", help="Имя входного файла с ADS-B сообщениями")
parser.add_argument("-a", "--aircraft", help="ICAO адрес конкретного борта (если не указан — выводятся данные по всем бортам)")
args = parser.parse_args()

# файл
file_path = args.file if args.file else DEFAULT_FILE
target_icao = args.aircraft.upper() if args.aircraft else None

# словарь для первого и последнего времени для каждого ICAO
icao_times = {}

# словарь для отслеживания координат
icao_coords = {}

# для графиков
icao_altitude = {}
icao_speed = {}

# для номеров рейсов
icao_callsigns = {}

icao_selected_altitude = {}

icao_has_selected_alt = {}

# список ICAO, которые передают ADS-B сообщения (DF=17 и DF=18)
adsb_icao_list = set()

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

            # фильтрация по ADS-B сообщениям
            if df not in [17, 18]:
                continue

            # фильтрация по ICAO (если указан целевой борт)
            if target_icao and aa != target_icao:
                continue

            # print(f"{msg.timestamp:.9f} {message_spaced} DF {df} ICAO {aa}")

            # добавление ICAO в список ADS-B бортов
            adsb_icao_list.add(aa)

            # обновление времени первого и последнего сообщения по ICAO (ТОЛЬКО ADS-B)
            if aa:
                if aa not in icao_times:
                    icao_times[aa] = {"first": msg.timestamp, "last": msg.timestamp}
                else:
                    icao_times[aa]["last"] = msg.timestamp
            
            # проверка наличия координат
            if aa and has_coords(message_str):
                icao_coords[aa] = True
                
            # получение высоты
            alt = get_altitude(message_str)
            # проверка диапазона высот
            if alt is not None and -1000 <= alt <= 50000:
                icao_altitude.setdefault(aa, []).append((msg.timestamp, alt))

            # получение выбранной высоты
            sel_alt = get_selected_altitude(message_str)
            if sel_alt:
                sel_alt_value, modes = sel_alt
                icao_selected_altitude.setdefault(aa, []).append((msg.timestamp, sel_alt_value))
                icao_has_selected_alt[aa] = True

                # сохраняем активные режимы в набор (для вывода в заголовке)
                modes_key = f"{aa}_modes"
                existing_modes = icao_callsigns.get(modes_key, set())
                icao_callsigns[modes_key] = existing_modes.union(modes)
                
            # получение скорости  
            gs = get_velocity(message_str)
            # проверка диапазона скоростей
            if gs is not None and 0 <= gs <= 1000:
                icao_speed.setdefault(aa, []).append((msg.timestamp, gs))

            # получение номера рейса
            cs = get_callsign(message_str)
            if cs:
                icao_callsigns[aa] = cs

    # вывод таблицы (только для ADS-B бортов)
    print("=" * 155)
    print("\t"*8 + "Таблица появления и исчезновения ADS-B бортов")
    print("=" * 155)
    print(f"{'ICAO':<8} {'Номер рейса':<15} {'Первое по UTC':<22} {'Первое по МСК':<22} {'Последнее по UTC':<22} {'Последнее по МСК':<22} {'Координаты':<15} {'Выбранная высота':<12}")
    print("=" * 155)

    tz_msk = pytz.timezone('Europe/Moscow')

    for icao, times in sorted(icao_times.items()):
        first_utc = timestamp_to_utc(times["first"])
        last_utc = timestamp_to_utc(times["last"])

        first_msk = first_utc.astimezone(tz_msk)
        last_msk = last_utc.astimezone(tz_msk)

        callsign = icao_callsigns.get(icao, "N/A")
        sel_alt_flag = ""
        if icao_has_selected_alt.get(icao, False):
            sel_alt_flag = "Да"
        else: 
            sel_alt_flag = "Нет"
        coord_flag = ""
        if icao_coords.get(icao, False):
            coord_flag = "Да"
        else:
            coord_flag = "Нет"

        print(f"{icao:<8} {callsign:<15} {first_utc.strftime('%Y-%m-%d %H:%M:%S'):<22} "
              f"{first_msk.strftime('%Y-%m-%d %H:%M:%S'):<22} "
              f"{last_utc.strftime('%Y-%m-%d %H:%M:%S'):<22} "
              f"{last_msk.strftime('%Y-%m-%d %H:%M:%S'):<22} "
              f"{coord_flag:<15} {sel_alt_flag:<12}")
        
    print(f"\nВсего бортов: {len(icao_times)}\n")

    IcaoGraphs(icao_altitude, icao_speed, adsb_icao_list, icao_callsigns, icao_selected_altitude)


except FileNotFoundError:
    print(f"Файл {file_path} не найден")
except Exception as e:
    print(f"Ошибка чтения файла: {e}")