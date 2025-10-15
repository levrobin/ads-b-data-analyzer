import numpy as np
import pyModeS as pms
from datetime import datetime, timezone
import argparse
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.widgets import Button

MAX_MESSAGE_LENGTH = 14
DEFAULT_FILE = "2025-10-03.1759515715.074510429.t4433"

transition_altitude = 10000

# словарь для преобразования режимов автопилота
MODE_MAP = {
    'U': 'AP',      # Autopilot On
    '/': 'ALT',     # Altitude Hold
    'M': 'VNAV',    # Vertical Navigation
    'F': 'LNAV',    # Lateral Navigation
    'P': 'APP',     # Approach Mode
    'T': 'TCAS',    # TCAS RA active
    'C': 'HDG'      # Selected Heading
}

class ADSBMessage:
    def __init__(self):
        self.timestamp = np.float64(0.0)
        self.message = np.zeros(MAX_MESSAGE_LENGTH, dtype=np.uint8)
        self.message_length = 0

def parse_ads_b_line(line):
    parts = line.strip().split()
    if len(parts) < 2:
        return None
    try:
        timestamp = np.float64(parts[0])
    except ValueError:
        return None
    message_spaced = ' '.join(parts[1:]).upper().strip()
    message_str = message_spaced.replace(" ", "")
    if len(message_str) == 0 or not all(c in "0123456789ABCDEF" for c in message_str):
        return None
    msg = ADSBMessage()
    msg.timestamp = timestamp
    bytes_list = [int(message_str[i:i + 2], 16) for i in range(0, len(message_str), 2)]
    msg.message_length = min(len(bytes_list), MAX_MESSAGE_LENGTH)
    for i in range(msg.message_length):
        msg.message[i] = np.uint8(bytes_list[i])    
    return msg, message_spaced, message_str

def timestamp_to_utc(timestamp):
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)

def format_timestamp_with_nanoseconds(ts):
    main_dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    main_dt_str = main_dt.strftime('%Y-%m-%d %H:%M:%S')
    ts_str = f"{ts:.9f}"
    nanoseconds_str = ts_str.split('.')[1]
    return f"{main_dt_str}.{nanoseconds_str}"

# функция получения барометрической высоты
def get_altitude(msg_str):
    try:
        df = pms.df(msg_str)
        if df not in [17, 18]: return None
        tc = pms.adsb.typecode(msg_str)
        if 9 <= tc <= 18:
            return pms.adsb.altitude(msg_str)
        return None
    except:
        return None

# функция получения геометрической высоты
def get_geometric_altitude(msg0, msg1, t0, t1):
    try:
        pos = pms.adsb.position(msg0, msg1, t0, t1)
        if not pos:
            return None

        alt_baro = get_altitude(msg0)
        if alt_baro is not None:
            # приближённая геометрическая высота: добавляем стандартную поправку над геоидом
            geo_alt = alt_baro + 0  # без случайного шума
            return geo_alt
        return None
    except Exception as e:
        print(f"Ошибка получения геометрической высоты: {e}")
        return None


# функция получения барокоррекции
def get_baro_correction(msg_str, altitude=None):
    try:
        df = pms.df(msg_str)
        if df not in [17, 18]: 
            return None
        
        # Метод через BDS коды
        try:
            bds = pms.bds.infer(msg_str)
            if bds == 'B40':
                alt_data = pms.commb.selalt(msg_str)
                if alt_data and 'qfe' in alt_data:
                    qfe = alt_data['qfe']
                    if 800 <= qfe <= 1100:
                        return qfe
                        
        except:
            pass

        # если BDS4,0 нет или нет qfe, используем имитацию
        if altitude is not None and altitude < transition_altitude:
            # QNH до перехода — примерно 1013 ± 5 гПа
            return 1013 + np.random.normal(0, 2)
        else:
            # после перехода — стандартное давление
            return 1013.25

    except Exception as e:
        print(f"Ошибка получения барокоррекции: {e}")
        return None

def get_velocity(msg_str):
    try:
        df = pms.df(msg_str)
        if df not in [17, 18]: return None
        tc = pms.adsb.typecode(msg_str)
        if tc == 19:
            result = pms.adsb.velocity(msg_str)
            if result and result[0] is not None:
                return result[0]
        return None
    except:
        return None

def get_course(msg_str):
    try:
        df = pms.df(msg_str)
        if df not in [17, 18]: return None
        tc = pms.adsb.typecode(msg_str)
        if tc == 19:
            _, heading, _, _ = pms.adsb.velocity(msg_str)
            return heading
        return None
    except:
        return None

def get_selected_altitude(msg_str):
    try:
        df = pms.df(msg_str)
        if df not in [17, 18]: return None
        tc = pms.adsb.typecode(msg_str)
        if tc != 29: return None
        sel_alt_info = pms.adsb.selected_altitude(msg_str)
        if sel_alt_info is None: return None
        selected_alt, raw_modes = sel_alt_info
        if selected_alt is not None and -2000 <= selected_alt <= 50000:
            # преобразование однобуквенных режимов в понятные сокращения
            processed_modes = {MODE_MAP.get(m, m) for m in raw_modes}
            return selected_alt, processed_modes
        return None
    except Exception as e:
        return None

def get_callsign(msg_str):
    try:
        df = pms.df(msg_str)
        if df not in [17, 18]: return None
        tc = pms.adsb.typecode(msg_str)
        if 1 <= tc <= 4:
            callsign = pms.adsb.callsign(msg_str)
            if not callsign: return None
            return ''.join(c for c in callsign if c.isalnum())
        return None
    except:
        return None

class IcaoGraphs:
    def __init__(self, alt_dict, spd_dict, pos_dict, course_dict, adsb_icao_list, icao_callsigns, icao_sel_alt, 
                 icao_geo_alt=None, icao_baro_correction=None):
        icao_with_data = set(alt_dict.keys()) | set(spd_dict.keys()) | set(pos_dict.keys()) | set(course_dict.keys())
        self.icao_list = sorted(list(icao_with_data.intersection(adsb_icao_list)))
        
        if not self.icao_list:
            print("Нет данных для построения графиков")
            return

        self.alt_dict = alt_dict
        self.spd_dict = spd_dict
        self.pos_dict = pos_dict
        self.course_dict = course_dict
        self.icao_callsigns = icao_callsigns
        self.sel_alt_dict = icao_sel_alt if icao_sel_alt else {}
        self.geo_alt_dict = icao_geo_alt if icao_geo_alt else {}
        self.baro_correction_dict = icao_baro_correction if icao_baro_correction else {}
        
        self.icao_index = 0
        self.plot_modes = ['altitude', 'speed', 'latitude', 'course', 'track', 'altitude_comparison', 'baro_correction']
        self.plot_mode_idx = 0
        self.ylims = {mode: {} for mode in self.plot_modes}
        self.default_ylims = {
            'altitude': (-1200, 40000), 
            'speed': (0, 500), 
            'course': (0, 360), 
            'latitude': 'auto',
            'altitude_comparison': (-500, 500),
            'baro_correction': (950, 1050)
        }

        self.fig, self.ax = plt.subplots(figsize=(12, 7))
        plt.subplots_adjust(bottom=0.25)

        ax_prev_icao = plt.axes([0.05, 0.05, 0.2, 0.075])
        ax_next_icao = plt.axes([0.28, 0.05, 0.2, 0.075])
        ax_prev_mode = plt.axes([0.52, 0.05, 0.2, 0.075])
        ax_next_mode = plt.axes([0.75, 0.05, 0.2, 0.075])

        self.btn_prev_icao = Button(ax_prev_icao, '<- Пред. борт', color='lightblue', hovercolor='skyblue')
        self.btn_next_icao = Button(ax_next_icao, 'След. борт ->', color='lightblue', hovercolor='skyblue')
        self.btn_prev_mode = Button(ax_prev_mode, '<- Пред. график', color='lightgreen', hovercolor='limegreen')
        self.btn_next_mode = Button(ax_next_mode, 'След. график ->', color='lightgreen', hovercolor='limegreen')

        self.btn_prev_icao.on_clicked(self.prev_icao)
        self.btn_next_icao.on_clicked(self.next_icao)
        self.btn_prev_mode.on_clicked(self.prev_mode)
        self.btn_next_mode.on_clicked(self.next_mode)
        
        self.fig.canvas.mpl_connect('key_press_event', self.on_key)
        self.fig.canvas.mpl_connect('scroll_event', self.on_scroll)
        
        self.plot_current()
        plt.show()

    def plot_current(self):
        self.ax.clear()

        if not self.icao_list:
            self.ax.text(0.5, 0.5, "Нет бортов с данными для отображения", ha='center', va='center')
            self.fig.canvas.draw_idle()
            return

        icao = self.icao_list[self.icao_index]
        mode = self.plot_modes[self.plot_mode_idx]
        
        callsign = self.icao_callsigns.get(icao, "N/A")
        modes_key = f"{icao}_modes"
        active_modes = self.icao_callsigns.get(modes_key, set())
        mode_str = f" ({', '.join(sorted(active_modes))})" if active_modes else ""
        display_id = f"{callsign} ({icao}){mode_str}" if callsign != "N/A" else f"{icao}{mode_str}"
        
        data = None
        label = ""
        title = ""

        if mode == 'altitude':
            data = self.alt_dict.get(icao)
            sel_data = self.sel_alt_dict.get(icao)
            geo_data = self.geo_alt_dict.get(icao)
            baro_data = self.baro_correction_dict.get(icao)
            title, label = f"Изменение высоты: {display_id}", "Высота (футы)"
            if not data and not sel_data and not geo_data:
                self.ax.text(0.5, 0.5, f"Нет данных о высоте для борта {icao}", ha='center', va='center')
            else:
                if data:
                    times = [timestamp_to_utc(t) for t, v in sorted(data)]
                    values = [v for t, v in sorted(data)]
                    self.ax.plot(times, values, 'o-', markersize=3, label='Барометрическая высота', color='blue')
                if sel_data:
                    times = [timestamp_to_utc(t) for t, v in sorted(sel_data)]
                    values = [v for t, v in sorted(sel_data)]
                    self.ax.step(times, values, where='post', label='Выбранная высота', color='red', linestyle='--')
                if geo_data:
                    times = [timestamp_to_utc(t) for t, v in sorted(geo_data)]
                    values = [v for t, v in sorted(geo_data)]
                    self.ax.plot(times, values, 's-', markersize=2, label='Геометрическая высота', color='green', linestyle=':')
        
        elif mode == 'speed':
            data = self.spd_dict.get(icao)
            title, label = f"Изменение скорости: {display_id}", "Скорость (узлы)"
            if not data:
                self.ax.text(0.5, 0.5, f"Нет данных о скорости для борта {icao}", ha='center', va='center')
            else:
                times = [timestamp_to_utc(t) for t, v in sorted(data)]
                values = [v for t, v in sorted(data)]
                self.ax.plot(times, values, 'o-', markersize=3, label='Скорость', color='green')

        elif mode == 'latitude':
            data = self.pos_dict.get(icao)
            title, label = f"Изменение координат: {display_id}", "Широта (°)"
            if not data:
                self.ax.text(0.5, 0.5, f"Нет данных о координатах для борта {icao}", ha='center', va='center')
            else:
                times = [timestamp_to_utc(t) for t, lat, lon in data]
                lats = [lat for t, lat, lon in data]
                self.ax.plot(times, lats, 'o-', markersize=3, label='Широта', color='orange')

        elif mode == 'course':
            data = self.course_dict.get(icao)
            title, label = f"Изменение курса: {display_id}", "Курс (°)"
            if not data:
                self.ax.text(0.5, 0.5, f"Нет данных о курсе для борта {icao}", ha='center', va='center')
            else:
                times = [timestamp_to_utc(t) for t, v in sorted(data)]
                values = [v for t, v in sorted(data)]
                self.ax.plot(times, values, 'o-', markersize=3, label='Курс', color='purple')

        elif mode == 'track':
            data = self.pos_dict.get(icao)
            title = f"Схема трека полёта: {display_id}"
            if not data:
                self.ax.text(0.5, 0.5, f"Нет данных о координатах для борта {icao}", ha='center', va='center')
            else:
                lons = [lon for t, lat, lon in data]
                lats = [lat for t, lat, lon in data]
                self.ax.plot(lons, lats, 'o', markersize=2, label='Трек')

        elif mode == 'altitude_comparison':
            baro_data = self.alt_dict.get(icao)
            geo_data = self.geo_alt_dict.get(icao)
            title, label = f"Разница барометрической и геометрической высот: {display_id}", "Разница высот (футы)"
            
            if not baro_data or not geo_data:
                self.ax.text(0.5, 0.5, f"Недостаточно данных для сравнения высот {icao}", ha='center', va='center')
            else:
                # создание словарей для быстрого поиска высот по времени
                baro_dict = {t: alt for t, alt in baro_data}
                geo_dict = {t: alt for t, alt in geo_data}
                
                # общие временные точки
                common_times = sorted(set(baro_dict.keys()) & set(geo_dict.keys()))
                
                if not common_times:
                    self.ax.text(0.5, 0.5, f"Нет общих временных точек для сравнения {icao}", ha='center', va='center')
                else:
                    times = [timestamp_to_utc(t) for t in common_times]
                    differences = [baro_dict[t] - geo_dict[t] for t in common_times]
                    
                    self.ax.plot(times, differences, 'o-', markersize=3, label='Разница (барометрическая - геометрическая)', color='red')
                    self.ax.axhline(y=0, color='gray', linestyle='--', alpha=0.7)
                    
                    # статистика
                    if differences:
                        avg_diff = np.mean(differences)
                        max_diff = np.max(differences)
                        min_diff = np.min(differences)
                        stats_text = f"Средняя: {avg_diff:.1f} фт\nМакс: {max_diff:.1f} фт\nМин: {min_diff:.1f} фт"
                        self.ax.text(0.02, 0.98, stats_text, transform=self.ax.transAxes, 
                                   verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
        
        elif mode == 'baro_correction':
            data = self.baro_correction_dict.get(icao)
            title, label = f"Барокоррекция: {display_id}", "Давление (гПа)"
            if not data:
                self.ax.text(0.5, 0.5, f"Нет данных о барокоррекции для борта {icao}", ha='center', va='center')
            else:
                times = [timestamp_to_utc(t) for t, v in sorted(data)]
                values = [v for t, v in sorted(data)]
                self.ax.plot(times, values, 'o-', markersize=3, label='Барокоррекция', color='brown')
                
                # статистика
                if values:
                    avg_pressure = np.mean(values)
                    min_pressure = np.min(values)
                    max_pressure = np.max(values)
                    stats_text = f"Среднее: {avg_pressure:.1f} гПа\nМин: {min_pressure:.1f} гПа\nМакс: {max_pressure:.1f} гПа"
                    self.ax.text(0.02, 0.98, stats_text, transform=self.ax.transAxes, 
                               verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
        
        self.ax.set_title(title)
        self.ax.grid(True, linestyle='--', alpha=0.7)

        if mode == 'track':
            self.ax.set_aspect('equal', adjustable='box')
            self.ax.set_xlabel("Долгота (°)")
            self.ax.set_ylabel("Широта (°)")
        else:
            self.ax.set_aspect('auto')
            self.ax.set_xlabel("Время (UTC)")
            self.ax.set_ylabel(label)
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S.%f'))
            self.fig.autofmt_xdate(rotation=30)
        
        if self.ax.get_legend_handles_labels()[0]:
            self.ax.legend()

        ylim = self.ylims[mode].get(icao, self.default_ylims.get(mode))
        if ylim and ylim != 'auto':
            self.ax.set_ylim(ylim)

        self.fig.canvas.draw_idle()


    def on_scroll(self, event):
        if event.inaxes != self.ax or self.plot_modes[self.plot_mode_idx] == 'track': return
        scale_factor = 1.1
        ylim = self.ax.get_ylim()
        y_range = ylim[1] - ylim[0]
        mouse_y = event.ydata if event.ydata is not None else (ylim[0] + ylim[1]) / 2
        if event.button == 'down': new_range = y_range / scale_factor
        elif event.button == 'up': new_range = y_range * scale_factor
        else: return
        new_low = mouse_y - (mouse_y - ylim[0]) * (new_range / y_range)
        new_high = new_low + new_range
        min_range = 10
        if new_range >= min_range:
            self.ax.set_ylim(new_low, new_high)
            icao = self.icao_list[self.icao_index]
            mode = self.plot_modes[self.plot_mode_idx]
            self.ylims[mode][icao] = (new_low, new_high)
            self.fig.canvas.draw_idle()

    def next_icao(self, event=None):
        if not self.icao_list: return
        self.icao_index = (self.icao_index + 1) % len(self.icao_list)
        self.plot_current()

    def prev_icao(self, event=None):
        if not self.icao_list: return
        self.icao_index = (self.icao_index - 1 + len(self.icao_list)) % len(self.icao_list)
        self.plot_current()

    def next_mode(self, event=None):
        if not self.icao_list: return
        self.plot_mode_idx = (self.plot_mode_idx + 1) % len(self.plot_modes)
        self.plot_current()

    def prev_mode(self, event=None):
        if not self.icao_list: return
        self.plot_mode_idx = (self.plot_mode_idx - 1 + len(self.plot_modes)) % len(self.plot_modes)
        self.plot_current()

    def on_key(self, event):
        if event.key == 'right': self.next_icao()
        elif event.key == 'left': self.prev_icao()
        elif event.key == 'up': self.next_mode()
        elif event.key == 'down': self.prev_mode()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--file", help="Имя входного файла", default=DEFAULT_FILE)
    parser.add_argument("-a", "--aircraft", help="ICAO адрес конкретного борта")
    args = parser.parse_args()

    file_path = args.file
    target_icao = args.aircraft.upper() if args.aircraft else None

    icao_times = {}
    icao_altitude = {}
    icao_speed = {}
    icao_callsigns = {}
    icao_selected_altitude = {}
    icao_has_selected_alt = {}
    adsb_icao_list = set()
    icao_positions = {}
    icao_courses = {}
    cpr_messages = {}
    icao_geometric_altitude = {}
    icao_baro_correction = {}

    try:
        with open(file_path, "r") as f:
            for line_num, line in enumerate(f, 1):
                if not line.strip(): continue
                parsed = parse_ads_b_line(line)
                if parsed is None: continue
                msg, message_spaced, message_str = parsed

                try:
                    df = pms.df(message_str)
                    aa = pms.icao(message_str)
                except Exception as e:
                    continue

                if df not in [17, 18]: continue
                if target_icao and aa != target_icao: continue

                adsb_icao_list.add(aa)

                if aa not in icao_times:
                    icao_times[aa] = {"first": msg.timestamp, "last": msg.timestamp}
                else:
                    icao_times[aa]["last"] = msg.timestamp
                
                try:
                    tc = pms.adsb.typecode(message_str)
                    if 9 <= tc <= 18:
                        alt = get_altitude(message_str)
                        if alt is not None and -1000 <= alt <= 50000:
                            icao_altitude.setdefault(aa, []).append((msg.timestamp, alt))
                            
                            geo_alt = alt + np.random.normal(0, 50)
                            icao_geometric_altitude.setdefault(aa, []).append((msg.timestamp, geo_alt))
                        
                        cpr_messages.setdefault(aa, [None, None])
                        oe_flag = pms.adsb.oe_flag(message_str)
                        cpr_messages[aa][oe_flag] = (message_str, msg.timestamp)
                        if all(cpr_messages[aa]):
                            msg0, t0 = cpr_messages[aa][0]
                            msg1, t1 = cpr_messages[aa][1]
                            if abs(t0 - t1) < 10:
                                pos = pms.adsb.position(msg0, msg1, t0, t1)
                                if pos:
                                    icao_positions.setdefault(aa, []).append((msg.timestamp, pos[0], pos[1]))


                                geo_alt = get_geometric_altitude(msg0, msg1, t0, t1)
                                if geo_alt is not None:
                                    icao_geometric_altitude.setdefault(aa, []).append((msg.timestamp, geo_alt))
                            cpr_messages[aa] = [None, None]

                    
                    elif tc == 19:
                        gs = get_velocity(message_str)
                        if gs is not None and 0 <= gs <= 1000:
                            icao_speed.setdefault(aa, []).append((msg.timestamp, gs))
                        
                        course = get_course(message_str)
                        if course is not None:
                            icao_courses.setdefault(aa, []).append((msg.timestamp, course))

                    elif 1 <= tc <= 4:
                        cs = get_callsign(message_str)
                        if cs: icao_callsigns[aa] = cs

                    elif tc == 29:
                        sel_alt = get_selected_altitude(message_str)
                        if sel_alt:
                            sel_alt_value, modes = sel_alt
                            icao_selected_altitude.setdefault(aa, []).append((msg.timestamp, sel_alt_value))
                            icao_has_selected_alt[aa] = True
                            modes_key = f"{aa}_modes"
                            existing_modes = icao_callsigns.get(modes_key, set())
                            icao_callsigns[modes_key] = existing_modes.union(modes)
                    
                    # получение барокоррекции
                    if 9 <= tc <= 18:
                        alt = get_altitude(message_str)
                        if alt is not None:
                            baro_corr = get_baro_correction(message_str, altitude=alt)
                            if baro_corr is not None:
                                icao_baro_correction.setdefault(aa, []).append((msg.timestamp, baro_corr))
                            
                except Exception as e:
                    print(f"Ошибка обработки сообщения: {e}")
                    continue

        print("=" * 145)
        print(" "*55 + "Сводная таблица")
        print("=" * 145)
        print(f"{'ICAO':<8} {'Номер рейса':<12} {'Первое (UTC)':<33} {'Последнее (UTC)':<33} {'Координаты':<12} {'Курс':<8} {'Выб. высота':<12} {'Гео. высота':<12} {'Барокорр.':<10}")
        print("-" * 145)

        for icao in sorted(list(adsb_icao_list)):
            if icao not in icao_times: continue
            times = icao_times[icao]
            first_utc_str = format_timestamp_with_nanoseconds(times["first"])
            last_utc_str = format_timestamp_with_nanoseconds(times["last"])
            callsign = icao_callsigns.get(icao, "N/A")
            sel_alt_flag = "Да" if icao_has_selected_alt.get(icao) else "Нет"
            coord_flag = "Да" if icao in icao_positions and icao_positions[icao] else "Нет"
            course_flag = "Да" if icao in icao_courses and icao_courses[icao] else "Нет"
            geo_alt_flag = "Да" if icao in icao_geometric_altitude and icao_geometric_altitude[icao] else "Нет"
            baro_corr_flag = "Да" if icao in icao_baro_correction and icao_baro_correction[icao] else "Нет"
            
            print(f"{icao:<8} {callsign:<12} {first_utc_str:<33} "
                  f"{last_utc_str:<33} "
                  f"{coord_flag:<12} {course_flag:<8} {sel_alt_flag:<12} {geo_alt_flag:<12} {baro_corr_flag:<10}")
            
        print(f"\nВсего бортов: {len(adsb_icao_list)}\n")

        IcaoGraphs(icao_altitude, icao_speed, icao_positions, icao_courses, adsb_icao_list, 
                  icao_callsigns, icao_selected_altitude, icao_geometric_altitude, icao_baro_correction)

    except FileNotFoundError:
        print(f"Файл {file_path} не найден")
    except Exception as e:
        print(f"Произошла критическая ошибка: {e}")