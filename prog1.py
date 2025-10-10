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


def parse_adsb_line(line):
    
    parts = line.strip().split() # делим строку по пробелам
    if len(parts) < 2: return None # если в строке меньше двух частей, она неверная

    try:
        timestamp = np.float64(parts[0]) # пытаемся превратить первую часть в число
    except ValueError:
        return None 

    msg_str = ''.join(parts[1:]).upper().strip() # остальное склеиваем в одну hex-строку
    if not all(c in "0123456789ABCDEF" for c in msg_str): return None # проверяем, что там только hex-символы
    if len(msg_str) < MAX_MESSAGE_LENGTH * 2: return None # проверяем, что сообщение не слишком короткое
    
    return timestamp, msg_str # если всё хорошо, возвращаем результат

# переводит время в utc
def timestamp_to_utc(timestamp):
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)

def get_coords(msg_str, icao, messages_dict):
    try:
        tc = pms.adsb.typecode(msg_str) # узнаём тип сообщения
        if not (9 <= tc <= 18): return None, None # нас интересуют только позиционные сообщения

        # создаём ячейку для чётного и нечётного сообщений
        messages_dict.setdefault(icao, [None, None])
        oe_flag = pms.adsb.oe_flag(msg_str) # определяем, чётное (0) или нечётное (1)
        
        # кладём в ячейку само сообщение и его время
        timestamp = float(str(datetime.now(timezone.utc).timestamp())) # получаем текущее время для сообщения
        messages_dict[icao][oe_flag] = (msg_str, timestamp)
        
        if all(messages_dict[icao]): # если обе ячейки заполнены, у нас есть пара
            msg0, t0 = messages_dict[icao][0]
            msg1, t1 = messages_dict[icao][1]
            if abs(t0 - t1) < 10: # проверяем, что сообщения "свежие"
                lat, lon = pms.adsb.position(msg0, msg1, t0, t1) # главная функция декодирования
                messages_dict[icao] = [None, None] # очищаем ячейки для поиска новой пары
                return lat, lon # возвращаем результат
    except Exception:
        return None, None
    
    return None, None # если пара ещё не собрана, возвращаем ничего

def get_course(msg_str):
    """пытается извлечь курс из сообщения 19-го типа."""
    try:
        tc = pms.adsb.typecode(msg_str) # узнаём тип сообщения
        if tc == 19: # если это сообщение со скоростью/курсом
            _, h, _, _ = pms.adsb.velocity(msg_str)
            return h # возвращаем курс
    except Exception:
        return None # если что-то пошло не так, возвращаем ничего
    return None

class IcaoGraphs:
    """этот класс отвечает за создание и управление окном с графиками."""
    def __init__(self, coords_dict, course_dict):
        self.icao_list = sorted(set(coords_dict.keys()) | set(course_dict.keys()))
        if not self.icao_list:
            print("нет данных для построения графиков.")
            return

        self.coords_dict = coords_dict
        self.course_dict = course_dict
        self.index = 0
        self.plot_modes = ['main', 'track'] # режимы: основной и трек
        self.plot_mode_idx = 0

        self.fig, self.ax = plt.subplots(figsize=(8, 8)) # создаём квадратное окно
        plt.subplots_adjust(bottom=0.2)

        # создаём и размещаем кнопки под графиком
        ax_prev = plt.axes([0.15, 0.05, 0.25, 0.075]); ax_next = plt.axes([0.45, 0.05, 0.25, 0.075])
        ax_switch = plt.axes([0.75, 0.05, 0.15, 0.075])
        self.btn_prev = Button(ax_prev, '<- Предыдущий', color='lightblue', hovercolor='skyblue')
        self.btn_next = Button(ax_next, 'Следующий ->', color='lightblue', hovercolor='skyblue')
        self.btn_switch = Button(ax_switch, 'Режим', color='lightgreen', hovercolor='limegreen')
        
        # назначаем кнопкам действия
        self.btn_prev.on_clicked(self.prev)
        self.btn_next.on_clicked(self.next)
        self.btn_switch.on_clicked(self.switch_mode)

        self.fig.canvas.mpl_connect('key_press_event', self.on_key)
        self.plot_current()
        plt.show()

    def switch_mode(self, event):
        """переключает режим отображения."""
        self.plot_mode_idx = (self.plot_mode_idx + 1) % len(self.plot_modes)
        self.index = 0
        self.plot_current()

    def plot_current(self):
        """главная функция, которая рисует текущий график."""
        self.ax.clear()
        if not self.icao_list: return

        current_mode = self.plot_modes[self.plot_mode_idx]

        if current_mode == 'main':
            icao_index = self.index // 2; show_course = self.index % 2 == 1
        else:
            icao_index = self.index
        
        if icao_index >= len(self.icao_list): icao_index = 0
        icao = self.icao_list[icao_index]

        self.ax.set_aspect('auto', adjustable='box')

        # готовим данные, заголовок и подписи для нужного графика
        if current_mode == 'track':
            data, label, title = self.coords_dict.get(icao, []), "Трек", f"Схема трека полёта для {icao}"
        else:
            if show_course:
                data, label, title = self.course_dict.get(icao, []), "Курс (°)", f"Изменение курса борта {icao}"
            else:
                data, label, title = self.coords_dict.get(icao, []), "Широта (°)", f"Изменение координат борта {icao}"
        
        if hasattr(self.fig.canvas.manager, 'set_window_title'):
            self.fig.canvas.manager.set_window_title(title)

        if not data:
            self.ax.text(0.5, 0.5, f"Нет данных для этого графика", ha='center', va='center', fontsize=14)
        else:
            if current_mode == 'track':
                lons = [lon for _, lat, lon in data]; lats = [lat for _, lat, lon in data]
                self.ax.plot(lons, lats, 'o', markersize=2, label=label) # рисуем точками
                self.ax.set_xlabel("Долгота (°)"); self.ax.set_ylabel("Широта (°)")
                self.ax.set_aspect('equal', adjustable='box') # делаем оси пропорциональными
            else:
                times = [timestamp_to_utc(t) for t, *_ in data]
                if self.index % 2 == 1: values = [v for _, v in data]
                else: values = [lat for _, lat, lon in data]
                
                self.ax.plot(times, values, 'o-', label=label, linewidth=2, markersize=3)
                self.ax.set_xlabel("Время (UTC)"); self.ax.set_ylabel(label)
                self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
                self.fig.autofmt_xdate(rotation=30)
        
        self.ax.set_title(title); self.ax.grid(True, linestyle='--', alpha=0.7); self.ax.legend()
        self.fig.canvas.draw_idle()

    # переключает на следующий график
    def next(self, event=None):
        limit = len(self.icao_list) * 2 if self.plot_modes[self.plot_mode_idx] == 'main' else len(self.icao_list)
        self.index = (self.index + 1) % limit
        self.plot_current()

    # переключает на предыдущий график
    def prev(self, event=None):
        limit = len(self.icao_list) * 2 if self.plot_modes[self.plot_mode_idx] == 'main' else len(self.icao_list)
        self.index = (self.index - 1 + limit) % limit
        self.plot_current()

    # обрабатывает нажатия клавиш
    def on_key(self, event):
        if event.key in ['right', 'down']: self.next()
        elif event.key in ['left', 'up']: self.prev()
        elif event.key == 'm': self.switch_mode(event)


# настраиваем и парсим аргументы командной строки
parser = argparse.ArgumentParser()
parser.add_argument("-f", "--file")
parser.add_argument("-a", "--aircraft")
args = parser.parse_args()

file_path = args.file if args.file else DEFAULT_FILE
target_icao = args.aircraft.upper() if args.aircraft else None

# создаём пустые словари, куда будем складывать все найденные данные
icao_times = {}
icao_positions = {}
icao_course = {}
icao_messages = {} # временный словарь для сборки пар сообщений

try:
    with open(file_path, "r") as f:
        for line_num, line in enumerate(f, 1): # используем enumerate для получения номера строки
            if not line.strip(): continue # пропускаем пустые строки
            
            parsed = parse_adsb_line(line)
            if parsed is None:
                print(f"строка {line_num}: ошибка парсинга") # обработка ошибок как в примере
                continue
            timestamp, msg_str = parsed

            try:
                aa = pms.icao(msg_str) # достаём icao-адрес борта
                if pms.df(msg_str) != 17: continue # нас интересуют только сообщения ads-b
            except Exception as e:
                print(f"строка {line_num}: ошибка pyModeS ({e})") # обработка ошибок как в примере
                continue

            if target_icao and aa != target_icao: # если ищем конкретный борт, а это не он, пропускаем
                continue

            # обновляем время первого и последнего появления борта
            if aa not in icao_times:
                icao_times[aa] = {"first": timestamp, "last": timestamp}
            else:
                icao_times[aa]["last"] = timestamp
            
            # получение координат
            lat, lon = get_coords(msg_str, aa, icao_messages)
            if lat is not None and lon is not None:
                icao_positions.setdefault(aa, []).append((timestamp, lat, lon))
            
            # получение курса
            course = get_course(msg_str)
            if course is not None:
                icao_course.setdefault(aa, []).append((timestamp, course))

    # выводим итоговую таблицу в консоль
    print("=" * 130)
    print(" " * 40 + "ТАБЛИЦА ПЕРВОГО И ПОСЛЕДНЕГО СООБЩЕНИЯ")
    print("=" * 130)
    print(f"{'ICAO':<8} {'Первое (UTC)':<22} {'Первое (МСК)':<22} "
          f"{'Последнее (UTC)':<22} {'Последнее (МСК)':<22} {'Координаты':<12} {'Курс':<12}")
    print("=" * 130)

    tz_msk = pytz.timezone('Europe/Moscow')

    for icao, times in sorted(icao_times.items()):
        first_utc = timestamp_to_utc(times["first"])
        last_utc = timestamp_to_utc(times["last"])
        first_msk = first_utc.astimezone(tz_msk)
        last_msk = last_utc.astimezone(tz_msk)
        coord_flag = "да" if icao in icao_positions and icao_positions[icao] else "нет"
        course_flag = "да" if icao in icao_course and icao_course[icao] else "нет"
        
        print(f"{icao:<8} {first_utc.strftime('%Y-%m-%d %H:%M:%S'):<22} "
              f"{first_msk.strftime('%Y-%m-%d %H:%M:%S'):<22} "
              f"{last_utc.strftime('%Y-%m-%d %H:%M:%S'):<22} "
              f"{last_msk.strftime('%Y-%m-%d %H:%M:%S'):<22} "
              f"{coord_flag:<12} {course_flag:<12}")

    print(f"\nвсего бортов обработано: {len(icao_times)}\n")
    
    IcaoGraphs(icao_positions, icao_course)

except FileNotFoundError:
    print(f"ошибка: файл '{file_path}' не найден.")
except Exception as e:
    print(f"произошла непредвиденная ошибка: {e}")