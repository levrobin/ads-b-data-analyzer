import numpy as np 
import pyModeS as pms 
from datetime import datetime, timezone 
import pytz 
import argparse 
import matplotlib.pyplot as plt 
import matplotlib.dates as mdates 
from matplotlib.widgets import Button 
import tkinter as tk
from tkinter import ttk

MAX_MESSAGE_LENGTH = 14 
DEFAULT_FILE = "2025-10-03.1759515715.074510429.t4433" # использует этот файл по умолчанию

def parse_adsb_line(line):
    # делим строку по пробелам
    parts = line.strip().split() 
    # если в строке меньше двух частей, она неверная
    if len(parts) < 2: return None 
    try:
        # пытаемся превратить первую часть в число
        timestamp = np.float64(parts[0]) 
    except ValueError:
        return None 
    # остальное склеиваем в одну hex-строку
    msg_str = ''.join(parts[1:]).upper().strip() 
    # проверяем, что там только hex-символы
    if not all(c in "0123456789ABCDEF" for c in msg_str): return None 
    # проверяем, что сообщение не слишком короткое
    if len(msg_str) < MAX_MESSAGE_LENGTH * 2: return None 
    # если всё хорошо, возвращаем результат
    return timestamp, msg_str 

# переводит время в utc
def timestamp_to_utc(timestamp):
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)

# пытается извлечь курс из сообщения 19-го типа
def get_course(msg_str):
    try:
        # узнаём тип сообщения
        tc = pms.adsb.typecode(msg_str) 
        if tc == 19: 
            _, h, _, _ = pms.adsb.velocity(msg_str)
            return h 
    except Exception:
        return None 
    return None

# этот класс отвечает за создание и управление окном с графиками
class IcaoGraphs:
    def __init__(self, coords_dict, course_dict):
        self.icao_list = sorted(set(coords_dict.keys()) | set(course_dict.keys()))
        if not self.icao_list:
            root_info = tk.Tk()
            root_info.withdraw()
            tk.messagebox.showinfo("Нет данных", "Нет данных для построения графиков.")
            root_info.destroy()
            return

        self.coords_dict = coords_dict
        self.course_dict = course_dict
        self.index = 0
        self.plot_modes = ['main', 'track'] 
        self.plot_mode_idx = 0

        self.fig, self.ax = plt.subplots(figsize=(8, 8)) 
        plt.subplots_adjust(bottom=0.2)

        ax_prev = plt.axes([0.15, 0.05, 0.25, 0.075]); ax_next = plt.axes([0.45, 0.05, 0.25, 0.075])
        ax_switch = plt.axes([0.75, 0.05, 0.15, 0.075])
        self.btn_prev = Button(ax_prev, '<- Предыдущий', color='lightblue', hovercolor='skyblue')
        self.btn_next = Button(ax_next, 'Следующий ->', color='lightblue', hovercolor='skyblue')
        self.btn_switch = Button(ax_switch, 'Режим', color='lightgreen', hovercolor='limegreen')
        
        self.btn_prev.on_clicked(self.prev)
        self.btn_next.on_clicked(self.next)
        self.btn_switch.on_clicked(self.switch_mode)

        self.fig.canvas.mpl_connect('key_press_event', self.on_key)
        self.plot_current()
        plt.show()

    # переключает режим отображения
    def switch_mode(self, event):
        self.plot_mode_idx = (self.plot_mode_idx + 1) % len(self.plot_modes)
        self.index = 0
        self.plot_current()

    # главная функция, которая рисует текущий график
    def plot_current(self):
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
                self.ax.plot(lons, lats, 'o', markersize=2, label=label) 
                self.ax.set_xlabel("Долгота (°)"); self.ax.set_ylabel("Широта (°)")
                self.ax.set_aspect('equal', adjustable='box') 
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

    def next(self, event=None):
        limit = len(self.icao_list) * 2 if self.plot_modes[self.plot_mode_idx] == 'main' else len(self.icao_list)
        self.index = (self.index + 1) % limit
        self.plot_current()

    def prev(self, event=None):
        limit = len(self.icao_list) * 2 if self.plot_modes[self.plot_mode_idx] == 'main' else len(self.icao_list)
        self.index = (self.index - 1 + limit) % limit
        self.plot_current()

    def on_key(self, event):
        if event.key in ['right', 'down']: self.next()
        elif event.key in ['left', 'up']: self.prev()
        elif event.key == 'm': self.switch_mode(event)

# создает и управляет главным окном с таблицей бортов
class AircraftTableGUI:
    def __init__(self, master, all_data):
        self.master = master
        self.all_data = all_data
        self.master.title("Таблица бортов (двойной клик для графиков)")
        self.master.geometry("950x500")

        self.tree = ttk.Treeview(master, columns=("icao", "first_utc", "first_msk", "last_utc", "last_msk", "coords", "course"), show="headings")
        
        self.tree.heading("icao", text="ICAO")
        self.tree.heading("first_utc", text="Первое (UTC)")
        self.tree.heading("first_msk", text="Первое (МСК)")
        self.tree.heading("last_utc", text="Последнее (UTC)")
        self.tree.heading("last_msk", text="Последнее (МСК)")
        self.tree.heading("coords", text="Координаты")
        self.tree.heading("course", text="Курс")

        for col in self.tree['columns']: self.tree.column(col, anchor='center', width=120)
        self.tree.column("icao", width=80)

        self.populate_table()

        scrollbar = ttk.Scrollbar(master, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.bind("<Double-1>", self.on_double_click)

    def populate_table(self):
        icao_times = self.all_data['times']
        icao_positions = self.all_data['positions']
        icao_course = self.all_data['course']
        tz_msk = pytz.timezone('Europe/Moscow')

        for icao, times in sorted(icao_times.items()):
            first_utc = timestamp_to_utc(times["first"])
            last_utc = timestamp_to_utc(times["last"])
            first_msk = first_utc.astimezone(tz_msk)
            last_msk = last_utc.astimezone(tz_msk)
            coord_flag = "да" if icao in icao_positions and icao_positions[icao] else "нет"
            course_flag = "да" if icao in icao_course and icao_course[icao] else "нет"
            
            self.tree.insert("", "end", values=(
                icao,
                first_utc.strftime('%Y-%m-%d %H:%M:%S'),
                first_msk.strftime('%Y-%m-%d %H:%M:%S'),
                last_utc.strftime('%Y-%m-%d %H:%M:%S'),
                last_msk.strftime('%Y-%m-%d %H:%M:%S'),
                coord_flag,
                course_flag
            ))

    def on_double_click(self, event):
        selected_item = self.tree.focus()
        if not selected_item: return
        
        selected_icao = self.tree.item(selected_item, "values")[0]
        print(f"Выбран борт {selected_icao}, открываем графики...")

        coords_to_plot = {selected_icao: self.all_data['positions'].get(selected_icao, [])}
        course_to_plot = {selected_icao: self.all_data['course'].get(selected_icao, [])}

        IcaoGraphs(coords_to_plot, course_to_plot)


if __name__ == "__main__":
    # настраиваем и парсим аргументы командной строки
    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--file", default=DEFAULT_FILE)
    parser.add_argument("-a", "--aircraft", help="ICAO борта для фильтрации")
    args = parser.parse_args()
    
    target_icao = args.aircraft.upper() if args.aircraft else None

    print(f"Идет обработка файла {args.file}, пожалуйста, подождите...")
    
    # создаём пустые словари, куда будем складывать все найденные данные
    icao_times, icao_positions, icao_course = {}, {}, {}
    cpr_messages = {} 

    try:
        with open(args.file, "r") as f:
            # используем enumerate для получения номера строки
            for line_num, line in enumerate(f, 1):
                if not line.strip(): continue 
                
                parsed = parse_adsb_line(line)
                if not parsed: continue
                timestamp, msg_str = parsed

                try:
                    aa = pms.icao(msg_str) 
                    if pms.df(msg_str) != 17: continue 
                except Exception:
                    continue
                
                # Логика фильтрации
                if target_icao and aa != target_icao:
                    continue

                # обновляем время первого и последнего появления борта
                if aa not in icao_times:
                    icao_times[aa] = {"first": timestamp, "last": timestamp}
                else:
                    icao_times[aa]["last"] = timestamp
                
                # получение координат
                try:
                    tc = pms.adsb.typecode(msg_str) 
                    if 9 <= tc <= 18:
                        cpr_messages.setdefault(aa, [None, None])
                        oe_flag = pms.adsb.oe_flag(msg_str) 
                        cpr_messages[aa][oe_flag] = (msg_str, timestamp)

                        # если обе ячейки заполнены, у нас есть пара
                        if all(cpr_messages[aa]):
                            msg0, t0 = cpr_messages[aa][0]
                            msg1, t1 = cpr_messages[aa][1]
                            
                            # проверяем, что сообщения "свежие"
                            if abs(t0 - t1) < 10:
                                # главная функция декодирования
                                pos = pms.adsb.position(msg0, msg1, t0, t1)
                                if pos:
                                    lat, lon = pos
                                    icao_positions.setdefault(aa, []).append((timestamp, lat, lon))
                                # очищаем ячейки для поиска новой пары
                                cpr_messages[aa] = [None, None]
                except Exception:
                    pass
                
                # получение курса
                course = get_course(msg_str)
                if course is not None:
                    icao_course.setdefault(aa, []).append((timestamp, course))

        all_aircraft_data = {
            'times': icao_times,
            'positions': icao_positions,
            'course': icao_course
        }

        print("Обработка завершена. Запуск интерфейса...")
        root = tk.Tk()
        app = AircraftTableGUI(root, all_aircraft_data)
        root.mainloop()

    except FileNotFoundError:
        print(f"ошибка: файл '{args.file}' не найден.")
    except Exception as e:
        print(f"произошла непредвиденная ошибка: {e}")