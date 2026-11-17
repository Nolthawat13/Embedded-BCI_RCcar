import sys
import os
import time
import struct
from collections import deque
import numpy as np
import pandas as pd
import serial
import serial.tools.list_ports
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore, QtGui
from brainflow.data_filter import DataFilter, FilterTypes, NoiseTypes, WindowOperations, DetrendOperations

# -----------------------------------------------------------------------------
# กำหนดค่าธีมกราฟิก PyQTGraph (ปิด Antialias เพื่อประหยัด CPU บนเครื่องสเปกประหยัด)
# -----------------------------------------------------------------------------
pg.setConfigOption('background', '#06090F')
pg.setConfigOption('foreground', '#7090B0')
pg.setConfigOptions(antialias=False)

def calculate_crc8_bytes(data: bytes) -> int:
    crc = 0x00
    poly = 0x07
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ poly) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc

class SystemState:
    DISCONNECTED = -1
    STOP = 0
    MOVE_FORWARD = 1
    CALIBRATING = 2

def select_system_configuration():
    print("=================================================================")
    print("   MAINSOFTWARE: Vol.1 ")
    print("=================================================================")
    
    print("ขั้นตอนที่ 1: เลือกแหล่งข้อมูลสัญญาณ EEG")
    print("  [1] โหมดไฟล์จำลองย้อนหลัง (Playback Real CSV Data)")
    print("  [2] โหมดฮาร์ดแวร์จริง     (ADS1299/ADS1294 MCU Hardware)")
    print("-----------------------------------------------------------------")
    
    while True:
        eeg_choice = input("เลือกแหล่งข้อมูล (1 หรือ 2) [ค่าเริ่มต้น 1]: ").strip() or "1"
        if eeg_choice in ['1', '2']:
            eeg_mode = int(eeg_choice)
            break
        print("[ข้อผิดพลาด] ตัวเลือกไม่ถูกต้อง กรุณาพิมพ์ 1 หรือ 2")

    project_dir = os.getcwd()
    playback_file_init = os.path.join(project_dir, "S001R01.csv")
    
    if not os.path.exists(playback_file_init):
        csv_files = [f for f in os.listdir(project_dir) if f.endswith('.csv')]
        if csv_files:
            playback_file_init = os.path.join(project_dir, csv_files[0])

    ads_port = "COM3"
    num_channels = 8
    sampling_rate = 250

    if eeg_mode == 1:
        print("\n--- ตั้งค่าโหมด PLAYBACK ---")
        file_i = input(f"ระบุชื่อไฟล์ CSV [{os.path.basename(playback_file_init)}]: ").strip()
        if file_i:
            playback_file_init = os.path.join(project_dir, file_i)
    else:
        print("\n--- ตั้งค่าไดรเวอร์ฮาร์ดแวร์จริง ---")
        ports = [port.device for port in serial.tools.list_ports.comports()]
        if ports:
            print(f"พอร์ต Serial ที่ตรวจพบ: {', '.join(ports)}")
        user_ads_port = input(f"ระบุ COM Port ของ EEG [{ads_port}]: ").strip()
        if user_ads_port:
            ads_port = user_ads_port

    print("\n-----------------------------------------------------------------")
    print("ขั้นตอนที่ 2: เลือกการเชื่อมต่อโทรมาตรยานพาหนะ ESP32")
    print("  [1] โหมดประมวลผลเดี่ยว (Standalone Mode)")
    print("  [2] โหมดเชื่อมต่อฮาร์ดแวร์ (ESP32 Bluetooth Serial Link)")
    print("-----------------------------------------------------------------")

    esp_port = None
    while True:
        esp_choice = input("เลือกโหมด (1 หรือ 2) [ค่าเริ่มต้น 1]: ").strip() or "1"
        if esp_choice == '1':
            esp_port = None
            break
        elif esp_choice == '2':
            ports = [port.device for port in serial.tools.list_ports.comports()]
            if ports:
                print(f"พอร์ต Serial ที่ตรวจพบ: {', '.join(ports)}")
            esp_port = input("ระบุ COM Port ของ ESP32 Bluetooth (เช่น COM4 หรือ COM5): ").strip()
            break

    return eeg_mode, playback_file_init, ads_port, esp_port, num_channels, sampling_rate

# -----------------------------------------------------------------------------
# BCI Processing Thread
# -----------------------------------------------------------------------------
class MedicalBCIThread(QtCore.QThread):
    data_updated = QtCore.pyqtSignal(dict)

    def __init__(self, eeg_mode, file_init, ads_port, esp_port, num_channels, sampling_rate, cz_idx=0):
        super().__init__()
        self.running = True
        self.eeg_mode = eeg_mode
        self.current_file = file_init
        self.focus_file = file_init
        self.ads_port = ads_port
        self.esp_port = esp_port
        self.num_channels = num_channels
        self.sampling_rate = sampling_rate
        self.cz_idx = cz_idx

        self.state = SystemState.STOP
        self.manual_override_stop = False
        self.seq_num = 0
        self.last_tx_time = 0.0
        self.tx_interval_sec = 0.100  # 10 Hz Binary Telemetry
        self.is_esp_connected = False
        self.last_sent_hex = "STANDBY"

        self.window_size = int(self.sampling_rate * 2.0) # 500 samples (2 seconds)
        self.eeg_buffer = np.zeros((self.num_channels, self.window_size))

        self.HARD_DISCONNECT_PTP = 4000.0
        self.FLATLINE_STD_LIMIT = 1e-6
        
        # Exponential Moving Average (EMA) Parameters
        self.ema_alpha = 0.15
        self.ema_focus_ratio = 0.0

        # Calibration & Schmitt Trigger Controls (คงมาตรฐาน Medical-Grade 0.60 / 0.30)
        self.is_calibrated = False
        self.threshold_high = 1.0
        self.threshold_low = 0.5

        # Debounce Logic Controls
        self.high_focus_start_time = None
        self.low_focus_start_time = None
        self.START_DEBOUNCE_TIME = 0.6  # หน่วงออกตัว >= 0.6s
        self.STOP_DEBOUNCE_TIME = 1.2   # หน่วงหยุดรถ >= 1.2s

        self.calib_state = 0
        self.calib_start_time = 0.0
        self.calib_duration = 10.0
        self.iti_duration = 3.0
        self.rest_ratios = []
        self.focus_ratios = []

        self.playback_data = None
        self.playback_idx = 0
        self.ser_esp = None

        if self.esp_port is not None:
            self.init_esp32_serial()

    def init_esp32_serial(self):
        try:
            self.ser_esp = serial.Serial(self.esp_port, 115200, timeout=0.01, write_timeout=0.01)
            self.is_esp_connected = True
        except Exception:
            self.ser_esp = None
            self.is_esp_connected = False

    def load_csv_data(self, file_path):
        if not os.path.exists(file_path):
            self.playback_data = None
            return
        try:
            df = pd.read_csv(file_path, comment='#', on_bad_lines='skip')
            numeric_df = df.apply(pd.to_numeric, errors='coerce').dropna(how='all', axis=1).dropna(how='all', axis=0)
            data = numeric_df.values.T
            if data.shape[0] >= self.num_channels + 1:
                self.playback_data = data[1:self.num_channels + 1, :]
            else:
                self.playback_data = data[:self.num_channels, :]
            self.playback_idx = 0
            self.current_file = file_path
        except Exception:
            self.playback_data = None

    def set_focus_file(self, file_path):
        if file_path and file_path.endswith('.csv'):
            self.focus_file = file_path

    def start_2state_calibration(self):
        self.calib_state = 1
        self.calib_start_time = time.time()
        self.rest_ratios = []
        self.focus_ratios = []
        self.is_calibrated = False
        self.manual_override_stop = False
        self.force_safety_stop("CALIBRATION_INIT")

    def reset_manual_override(self):
        self.manual_override_stop = False

    def run(self):
        if self.eeg_mode == 1:
            self.load_csv_data(self.current_file)
            while self.running:
                if self.playback_data is not None and self.playback_data.shape[1] > 0:
                    chunk_size = 10
                    end_idx = self.playback_idx + chunk_size
                    if end_idx >= self.playback_data.shape[1]:
                        chunk = self.playback_data[:, self.playback_idx:]
                        self.playback_idx = 0
                    else:
                        chunk = self.playback_data[:, self.playback_idx:end_idx]
                        self.playback_idx = end_idx

                    if chunk.shape[1] > 0:
                        self.eeg_buffer = np.roll(self.eeg_buffer, -chunk.shape[1], axis=1)
                        self.eeg_buffer[:, -chunk.shape[1]:] = chunk
                        self.process_eeg_pipeline(self.eeg_buffer)
                time.sleep(0.04)

        elif self.eeg_mode == 2:
            try:
                eeg_ser = serial.Serial(self.ads_port, 115200, timeout=0.05)
            except Exception:
                self.running = False

            while self.running:
                try:
                    line = eeg_ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        parts = line.split(',')
                        valid_vals = []
                        for p in parts:
                            try:
                                valid_vals.append(float(p.strip()))
                            except ValueError:
                                continue
                        if len(valid_vals) >= self.num_channels:
                            eeg_vals = valid_vals[:self.num_channels]
                            self.eeg_buffer = np.roll(self.eeg_buffer, -1, axis=1)
                            self.eeg_buffer[:, -1] = eeg_vals
                            self.process_eeg_pipeline(self.eeg_buffer)
                except Exception:
                    pass
                time.sleep(0.002)

        self.cleanup()

    def process_eeg_pipeline(self, eeg_data):
        # 1. Spatial Filter (CAR)
        eeg_car = eeg_data - np.mean(eeg_data, axis=0)
        raw_cz = np.copy(eeg_data[self.cz_idx])
        filtered_cz = np.copy(eeg_car[self.cz_idx])

        # 2. Preprocessing & Filtering
        DataFilter.detrend(filtered_cz, DetrendOperations.LINEAR.value)
        DataFilter.remove_environmental_noise(filtered_cz, self.sampling_rate, NoiseTypes.FIFTY.value)
        DataFilter.perform_bandpass(filtered_cz, self.sampling_rate, 1.0, 30.0, 4, FilterTypes.BUTTERWORTH_ZERO_PHASE.value, 0)

        # 3. Artifact Rejection Check
        ptp_amp = np.ptp(filtered_cz)
        std_amp = np.std(filtered_cz)
        if ptp_amp > self.HARD_DISCONNECT_PTP or std_amp < self.FLATLINE_STD_LIMIT:
            self.force_safety_stop("ARTIFACT_OR_DISCONNECT")
            self.emit_ui("แจ้งเตือน: สายหลุดหรือเกิด Artifact ขนาดใหญ่", "#FF0055", raw_cz, filtered_cz,
                        np.array([]), np.array([]), 0.0, 0.0, 0.0, 0.0, 0.0, "ARTIFACT / DISCONNECT", "FORCE STOP", "STOP")
            return

        # 4. Corrected Spectral PSD Analysis
        data_len = len(filtered_cz)
        n_fft = 256
        if data_len < n_fft:
            return

        fft_input = np.ascontiguousarray(filtered_cz[-n_fft:], dtype=np.float64)
        try:
            psd = DataFilter.get_psd_welch(fft_input, n_fft, n_fft // 2, self.sampling_rate, WindowOperations.HAMMING.value)
            freqs, powers = psd[1], psd[0]
            
            theta_power = DataFilter.get_band_power(psd, 4.0, 8.0)
            alpha_power = DataFilter.get_band_power(psd, 8.0, 13.0)
            beta_power  = DataFilter.get_band_power(psd, 13.0, 30.0)

            raw_ratio = beta_power / (alpha_power + theta_power + 1e-6)
            
            # Exponential Moving Average (EMA)
            if self.ema_focus_ratio == 0.0:
                self.ema_focus_ratio = raw_ratio
            else:
                self.ema_focus_ratio = (self.ema_alpha * raw_ratio) + ((1.0 - self.ema_alpha) * self.ema_focus_ratio)
            
            focus_ratio = float(self.ema_focus_ratio)
        except Exception:
            return

        # 5. Synchronized Clinical Diagnostic Logic
        if self.is_calibrated:
            if focus_ratio >= self.threshold_high:
                clinical_state = "ACTIVE FOCUS (High Beta Ratio)"
                ideal_car_action = "ควรเคลื่อนที่ (SHOULD MOVE)"
            elif focus_ratio <= self.threshold_low:
                if theta_power > alpha_power:
                    clinical_state = "DROWSY / IDLE (Theta-Dominant)"
                else:
                    clinical_state = "RESTING (Alpha-Dominant)"
                ideal_car_action = "ควรหยุดนิ่ง (SHOULD STOP)"
            else:
                clinical_state = "TRANSITION (Hysteresis Band)"
                ideal_car_action = "รักษาการทำงานเดิม (HOLD STATE)"
        else:
            if beta_power > alpha_power and beta_power > theta_power:
                clinical_state = "ACTIVE FOCUS (Uncalibrated)"
            elif alpha_power > beta_power and alpha_power > theta_power:
                clinical_state = "RESTING (Uncalibrated)"
            else:
                clinical_state = "DROWSY / IDLE (Uncalibrated)"
            ideal_car_action = "ควรหยุดนิ่ง (UN-CALIBRATED LOCK)"

        now = time.time()

        # 6. Calibration Sequence Handling
        if self.calib_state == 1:
            self.rest_ratios.append(focus_ratio)
            self.force_safety_stop("CALIB_REST")
            rem = int(self.calib_duration - (now - self.calib_start_time))
            if rem <= 0:
                self.calib_state = 2
                self.calib_start_time = now
            else:
                self.emit_ui(f"การปรับจูน [1/2: พักผ่อน] นั่งผ่อนคลาย ({rem}s)", "#00CCFF", raw_cz, filtered_cz,
                            freqs, powers, theta_power, alpha_power, beta_power, focus_ratio, 0.0, clinical_state, ideal_car_action, "STOP")
            return

        elif self.calib_state == 2:
            self.force_safety_stop("CALIB_ITI")
            rem = int(self.iti_duration - (now - self.calib_start_time)) + 1
            if rem <= 0:
                self.calib_state = 3
                self.calib_start_time = now
                if self.eeg_mode == 1 and self.focus_file != self.current_file:
                    self.load_csv_data(self.focus_file)
            else:
                self.emit_ui(f"เตรียมเพ่งสมาธิในอีก... {rem}s", "#FFCC00", raw_cz, filtered_cz,
                            freqs, powers, theta_power, alpha_power, beta_power, focus_ratio, 0.0, clinical_state, ideal_car_action, "STOP")
            return

        elif self.calib_state == 3:
            self.focus_ratios.append(focus_ratio)
            self.force_safety_stop("CALIB_FOCUS")
            rem = int(self.calib_duration - (now - self.calib_start_time))
            if rem <= 0:
                self.calib_state = 0
                m_rest = np.mean(self.rest_ratios)
                m_focus = np.mean(self.focus_ratios)
                
                # Dynamic Schmitt Trigger Calibration (Medical Grade Standard: 0.60 / 0.30)
                self.threshold_high = float(m_rest + (m_focus - m_rest) * 0.60)
                self.threshold_low  = float(m_rest + (m_focus - m_rest) * 0.30)
                if self.threshold_low <= m_rest:
                    self.threshold_low = m_rest * 1.1
                if self.threshold_high <= self.threshold_low:
                    self.threshold_high = self.threshold_low * 1.3

                self.is_calibrated = True
            else:
                self.emit_ui(f"การปรับจูน [2/2: เพ่งสมาธิ] ({rem}s)", "#FF9900", raw_cz, filtered_cz,
                            freqs, powers, theta_power, alpha_power, beta_power, focus_ratio, 0.0, clinical_state, ideal_car_action, "STOP")
            return

        if not self.is_calibrated:
            self.force_safety_stop("UN_CALIBRATED")
            self.emit_ui("ระบบพร้อมทำงาน - กดปุ่มปรับจูนเพื่อเริ่มต้น", "#7090B0", raw_cz, filtered_cz,
                        freqs, powers, theta_power, alpha_power, beta_power, focus_ratio, 0.0, clinical_state, ideal_car_action, "STOP")
            return

        if self.manual_override_stop:
            self.force_safety_stop("EMERGENCY_OVERRIDE")
            self.emit_ui("🔴 หยุดฉุกเฉิน (EMERGENCY OVERRIDE) - กด SPACEBAR เพื่อปลดล็อก", "#FF0055", raw_cz, filtered_cz,
                        freqs, powers, theta_power, alpha_power, beta_power, focus_ratio, 0.0, clinical_state, ideal_car_action, "EMERGENCY STOP")
            return

        # 7. Robust Schmitt Trigger State Machine พร้อมระบบนับถอยหลัง Debounce สำหรับ UI
        display_car_cmd = "STOP"
        
        if self.state == SystemState.STOP:
            if focus_ratio >= self.threshold_high:
                self.low_focus_start_time = None
                if self.high_focus_start_time is None:
                    self.high_focus_start_time = now
                
                elapsed = now - self.high_focus_start_time
                if elapsed >= self.START_DEBOUNCE_TIME:
                    self.state = SystemState.MOVE_FORWARD
                    display_car_cmd = "FORWARD"
                else:
                    rem_time = self.START_DEBOUNCE_TIME - elapsed
                    display_car_cmd = f"STOP (กำลังเตรียมเดินหน้า {rem_time:.1f}s)"
            else:
                self.high_focus_start_time = None
                display_car_cmd = "STOP"

        elif self.state == SystemState.MOVE_FORWARD:
            if focus_ratio <= self.threshold_low:
                self.high_focus_start_time = None
                if self.low_focus_start_time is None:
                    self.low_focus_start_time = now
                
                elapsed = now - self.low_focus_start_time
                if elapsed >= self.STOP_DEBOUNCE_TIME:
                    self.state = SystemState.STOP
                    display_car_cmd = "STOP"
                else:
                    rem_time = self.STOP_DEBOUNCE_TIME - elapsed
                    display_car_cmd = f"FORWARD (กำลังเตรียมหยุด {rem_time:.1f}s)"
            else:
                self.low_focus_start_time = None
                display_car_cmd = "FORWARD"

        # 8. Binary Telemetry Output
        if now - self.last_tx_time >= self.tx_interval_sec:
            self.send_binary_packet(self.state)
            self.last_tx_time = now

        confidence = float(np.clip((focus_ratio / (self.threshold_high + 1e-6)) * 100.0, 0.0, 100.0))
        status = "เดินหน้า (FORWARD)" if self.state == SystemState.MOVE_FORWARD else "หยุดนิ่ง (STOP)"
        color = "#00FF66" if self.state == SystemState.MOVE_FORWARD else "#0A0E17"
        
        self.emit_ui(f"สถานะ: {status} | ความเชื่อมั่น: {confidence:.0f}% | สมาธิ: {focus_ratio:.2f} [Low:{self.threshold_low:.2f} / High:{self.threshold_high:.2f}]",
                    color, raw_cz, filtered_cz, freqs, powers, theta_power, alpha_power, beta_power, focus_ratio, confidence,
                    clinical_state, ideal_car_action, display_car_cmd)

    def force_safety_stop(self, reason="SAFETY"):
        self.state = SystemState.STOP
        self.high_focus_start_time = None
        self.low_focus_start_time = None
        if time.time() - self.last_tx_time >= self.tx_interval_sec:
            self.send_binary_packet(SystemState.STOP)
            self.last_tx_time = time.time()

    def send_binary_packet(self, state_val):
        self.seq_num = (self.seq_num + 1) % 256
        header = bytes([0xAA, 0x55, self.seq_num, int(state_val)])
        crc_val = calculate_crc8_bytes(header)
        packet = header + bytes([crc_val, 0x0A])

        self.last_sent_hex = packet.hex().upper()

        if self.ser_esp and self.ser_esp.is_open:
            try:
                self.ser_esp.write(packet)
                self.is_esp_connected = True
            except Exception:
                self.is_esp_connected = False
        else:
            self.is_esp_connected = False

    def emit_ui(self, msg, color, raw_ch, filtered_ch, freqs, powers, theta, alpha, beta, focus, conf, clinical_state, ideal_action, display_car_cmd):
        self.data_updated.emit({
            "message": msg, "color": color, "raw_ch": raw_ch, "filtered_ch": filtered_ch,
            "freqs": freqs, "powers": powers, "theta": theta, "alpha": alpha, "beta": beta,
            "focus": focus, "confidence": conf, "esp_packet": self.last_sent_hex,
            "esp_connected": self.is_esp_connected, "vehicle_state": self.state,
            "clinical_state": clinical_state, "ideal_action": ideal_action,
            "display_car_cmd": display_car_cmd
        })

    def stop(self):
        self.running = False
        self.wait()

    def cleanup(self):
        self.force_safety_stop("SHUTDOWN")

# -----------------------------------------------------------------------------
# PyQt5 GUI Main Application
# -----------------------------------------------------------------------------
class ProductionBCIApp(QtWidgets.QMainWindow):
    def __init__(self, eeg_mode, file_init, ads_port, esp_port, num_channels, sampling_rate):
        super().__init__()
        self.eeg_mode = eeg_mode
        mode_str = f"Playback Mode" if eeg_mode == 1 else f"Hardware Mode ({ads_port})"
        self.setWindowTitle(f"NEUROLINK MEDICAL BCI v4.8 — [{mode_str}]")
        self.resize(1280, 850)
        self.setStyleSheet("QMainWindow { background-color: #06090F; }")

        self.latest_data = None

        main_widget = QtWidgets.QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QtWidgets.QVBoxLayout(main_widget)

        # Header Bar
        header_layout = QtWidgets.QHBoxLayout()
        title_lbl = QtWidgets.QLabel("NEUROLINK BCI")
        title_lbl.setFont(QtGui.QFont("Consolas", 14, QtGui.QFont.Bold))
        title_lbl.setStyleSheet("color: #00E5FF;")
        header_layout.addWidget(title_lbl)

        self.btn_calib = QtWidgets.QPushButton("เริ่มต้นปรับจูน (CALIBRATION)")
        self.btn_calib.setFont(QtGui.QFont("Consolas", 10, QtGui.QFont.Bold))
        self.btn_calib.setStyleSheet("""
            QPushButton { background: #0D1B2A; color: #00E5FF; border: 1px solid #00E5FF; padding: 6px 12px; border-radius: 4px; }
            QPushButton:hover { background: #00E5FF; color: #06090F; }
        """)
        self.btn_calib.clicked.connect(self.trigger_calibration)
        header_layout.addWidget(self.btn_calib)

        self.lbl_status = QtWidgets.QLabel("ระบบพร้อมทำงาน...")
        self.lbl_status.setFont(QtGui.QFont("Consolas", 11, QtGui.QFont.Bold))
        self.lbl_status.setStyleSheet("background: #0A0E17; color: #00E5FF; border: 1px solid #1E293B; padding: 6px;")
        self.lbl_status.setAlignment(QtCore.Qt.AlignCenter)
        header_layout.addWidget(self.lbl_status, stretch=1)
        main_layout.addLayout(header_layout)

        # Diagnostics Panel
        diag_box = QtWidgets.QFrame()
        diag_box.setStyleSheet("QFrame { background: #08101D; border: 1px solid #00E5FF; border-radius: 4px; }")
        diag_layout = QtWidgets.QHBoxLayout(diag_box)
        self.lbl_patient_state = QtWidgets.QLabel("คลื่นสมองผู้ป่วย: Standby")
        self.lbl_patient_state.setStyleSheet("color: #00E5FF; font-weight: bold;")
        self.lbl_ideal_action = QtWidgets.QLabel("ทฤษฎีการเคลื่อนที่: Standby")
        self.lbl_ideal_action.setStyleSheet("color: #FFCC00; font-weight: bold;")
        diag_layout.addWidget(self.lbl_patient_state, stretch=1)
        diag_layout.addWidget(self.lbl_ideal_action, stretch=1)
        main_layout.addWidget(diag_box)

        # Telemetry Box
        telemetry_box = QtWidgets.QFrame()
        telemetry_box.setStyleSheet("QFrame { background: #0A0E17; border: 1px solid #1E293B; border-radius: 4px; }")
        telemetry_layout = QtWidgets.QHBoxLayout(telemetry_box)
        self.lbl_esp_status = QtWidgets.QLabel("ESP32: DISCONNECTED")
        self.lbl_esp_status.setStyleSheet("color: #7090B0; font-weight: bold;")
        self.lbl_tx_packet = QtWidgets.QLabel("Binary Telemetry: None")
        self.lbl_tx_packet.setStyleSheet("color: #00FF66; background: #06090F; padding: 4px;")
        self.lbl_car_realtime = QtWidgets.QLabel("คำสั่งส่งออก: STOP")
        self.lbl_car_realtime.setStyleSheet("color: #FF0055; font-weight: bold;")
        telemetry_layout.addWidget(self.lbl_esp_status)
        telemetry_layout.addWidget(self.lbl_tx_packet, stretch=1)
        telemetry_layout.addWidget(self.lbl_car_realtime)
        main_layout.addWidget(telemetry_box)

        # Plot Grid Layout
        grid_layout = QtWidgets.QGridLayout()
        
        self.win_left = pg.GraphicsLayoutWidget()
        # [ซ้ายบน]: RAW EEG (Cz)
        self.p_raw = self.win_left.addPlot(row=0, col=0, title="RAW EEG (Cz)")
        self.curve_raw = self.p_raw.plot(pen=pg.mkPen(color='#FF0055', width=1.0))
        # [ซ้ายล่าง]: PSD SPECTRUM (Welch)
        self.p_fft = self.win_left.addPlot(row=1, col=0, title="PSD SPECTRUM (Welch)")
        self.p_fft.setXRange(0, 35)
        self.curve_fft = self.p_fft.plot(pen=pg.mkPen(color='#00E5FF', width=1.2))

        self.win_right = pg.GraphicsLayoutWidget()
        # [ขวาบน]: FILTERED (CAR + 1-30Hz)
        self.p_filtered = self.win_right.addPlot(row=0, col=0, title="FILTERED (CAR + 1-30Hz)")
        self.curve_filtered = self.p_filtered.plot(pen=pg.mkPen(color='#00FF66', width=1.0))
        # [ขวาล่าง]: BAND POWER RATIO (%)
        self.p_bands = self.win_right.addPlot(row=1, col=0, title="BAND POWER RATIO (%)")
        self.p_bands.setYRange(0, 100)
        ticks = [(1, 'Theta'), (2, 'Alpha'), (3, 'Beta')]
        self.p_bands.getAxis('bottom').setTicks([ticks])
        self.bar_chart = pg.BarGraphItem(x=[1, 2, 3], height=[0, 0, 0], width=0.45, brush=pg.mkBrush('#00E5FF'))
        self.p_bands.addItem(self.bar_chart)

        grid_layout.addWidget(self.win_left, 0, 0)
        grid_layout.addWidget(self.win_right, 0, 1)
        main_layout.addLayout(grid_layout)

        self.sampling_rate = sampling_rate
        self.time_axis = np.linspace(-2.0, 0.0, int(sampling_rate * 2))

        # BCI Processing Thread
        self.bci_thread = MedicalBCIThread(eeg_mode, file_init, ads_port, esp_port, num_channels, sampling_rate)
        self.bci_thread.data_updated.connect(self.cache_thread_data)
        self.bci_thread.start()

        # UI Timer
        self.ui_timer = QtCore.QTimer()
        self.ui_timer.timeout.connect(self.render_ui)
        self.ui_timer.start(150)

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if event.key() == QtCore.Qt.Key_Space:
            if self.bci_thread.manual_override_stop:
                self.bci_thread.reset_manual_override()
            else:
                self.bci_thread.manual_override_stop = True

    def trigger_calibration(self):
        if self.eeg_mode == 1:
            file_dialog = QtWidgets.QFileDialog(self)
            file_dialog.setDirectory(os.getcwd())
            file_dialog.setNameFilter("CSV Files (*.csv)")
            if file_dialog.exec_():
                files = file_dialog.selectedFiles()
                if files:
                    self.bci_thread.set_focus_file(files[0])
        self.bci_thread.start_2state_calibration()

    def cache_thread_data(self, data):
        self.latest_data = data

    def render_ui(self):
        if self.latest_data is None:
            return

        data = self.latest_data
        self.lbl_status.setText(data["message"])
        self.lbl_patient_state.setText(f"คลื่นสมองผู้ป่วย: {data['clinical_state']}")
        self.lbl_ideal_action.setText(f"ทฤษฎีการเคลื่อนที่: {data['ideal_action']}")

        if data["esp_connected"]:
            self.lbl_esp_status.setText("ESP32: CONNECTED")
            self.lbl_esp_status.setStyleSheet("color: #00FF66; font-weight: bold;")
        else:
            self.lbl_esp_status.setText("ESP32: STANDALONE")
            self.lbl_esp_status.setStyleSheet("color: #7090B0;")

        self.lbl_tx_packet.setText(f"Binary Hex Stream: {data['esp_packet']}")

        # แสดงสถานะคำสั่งส่งออกพร้อมตัวนับถอยหลัง Debounce
        cmd_text = data["display_car_cmd"]
        if "FORWARD" in cmd_text:
            if "เตรียมหยุด" in cmd_text:
                self.lbl_car_realtime.setText(f"คำสั่งส่งออก: {cmd_text}")
                self.lbl_car_realtime.setStyleSheet("color: #FFCC00; font-weight: bold;") # สีเหลืองเตือนกำลังหยุด
            else:
                self.lbl_car_realtime.setText("คำสั่งส่งออก: FORWARD")
                self.lbl_car_realtime.setStyleSheet("color: #00FF66; font-weight: bold;")
        else:
            if "เตรียมเดินหน้า" in cmd_text:
                self.lbl_car_realtime.setText(f"คำสั่งส่งออก: {cmd_text}")
                self.lbl_car_realtime.setStyleSheet("color: #00E5FF; font-weight: bold;") # สีฟ้าเตือนกำลังออกตัว
            else:
                self.lbl_car_realtime.setText("คำสั่งส่งออก: STOP")
                self.lbl_car_realtime.setStyleSheet("color: #FF0055; font-weight: bold;")

        if len(data["raw_ch"]) == len(self.time_axis):
            self.curve_raw.setData(self.time_axis, data["raw_ch"])
            self.curve_filtered.setData(self.time_axis, data["filtered_ch"])

        if len(data["freqs"]) > 0:
            self.curve_fft.setData(data["freqs"], data["powers"])

        total_p = data["theta"] + data["alpha"] + data["beta"] + 1e-6
        self.bar_chart.setOpts(height=[(data["theta"]/total_p)*100, (data["alpha"]/total_p)*100, (data["beta"]/total_p)*100])

    def closeEvent(self, event):
        self.ui_timer.stop()
        self.bci_thread.stop()
        event.accept()

if __name__ == '__main__':
    eeg_mode, file_init, ads_port, esp_port, num_channels, sampling_rate = select_system_configuration()
    app = QtWidgets.QApplication(sys.argv)
    win = ProductionBCIApp(eeg_mode, file_init, ads_port, esp_port, num_channels, sampling_rate)
    win.show()
    sys.exit(app.exec_())