# 🧠 MAINSOFTWARE: Vol.1

ซอฟต์แวร์ประมวลผลสัญญาณคลื่นไฟฟ้าสมองแบบเรียลไทม์ (Real-Time Brain-Computer Interface) สำหรับการควบคุมรถบังคับไร้สายผ่านคลื่นสมองระดับสมาธิ (Attention/Focus State) พัฒนาด้วย Python, PyQt5 และ BrainFlow


---

## ✨ คุณสมบัติหลักของระบบ (Key Features)

* **Dual Input Modes:** รองรับทั้งโหมดจำลองข้อมูลย้อนหลังจากไฟล์ CSV (**Playback Mode**) และโหมดรับสัญญาณสดจากบอร์ดฮาร์ดแวร์ ADS1299/ADS1294 ผ่าน Serial (**Hardware Mode**)
* **Medical-Grade Signal Processing Pipeline:**
  * **Spatial Filtering:** กรองสัญญาณรบกวนร่วมด้วยวิธี Common Average Reference (CAR)
  * **Digital Filtering:** ตัดสัญญาณรบกวนไฟบ้าน (50Hz Notch Filter), Linear Detrending และ Bandpass Filter (1.0 – 30.0 Hz)
  * **Artifact & Disconnect Protection:** ตรวจสอบสัญญาณขาดหาย (Flatline) และสัญญาณรบกวนรุนแรง (Peak-to-Peak > 4000 µV) เพื่อสั่งหยุดรถอัตโนมัติ (Fail-Safe)
* **Adaptive 2-State Calibration:** ระบบปรับจูนค่าเกณฑ์มาตรฐาน (Dynamic Thresholds) เฉพาะบุคคล โดยเปรียบเทียบระหว่างสภาวะผ่อนคลาย (Resting) และสภาวะเพ่งสมาธิ (Active Focus)
* **Hysteresis & Debounce Control:** ป้องกันการสั่งงานกระตุกด้วย Schmitt Trigger ร่วมกับตัวหน่วงเวลาออกตัว ($\ge 0.6\text{s}$) และหน่วงเวลาหยุดรถ ($\ge 1.2\text{s}$)
* **CRC-8 Binary Telemetry:** ส่งคำสั่งควบคุมไปยังไมโครคอนโทรลเลอร์ ESP32 ผ่าน Bluetooth/Serial ในรูปแบบ Binary Packet พร้อมระบบตรวจสอบความถูกต้องของข้อมูล (CRC-8)

---

## 🛠️ การติดตั้งและเตรียมความพร้อม (Installation)

### 1. ความต้องการของระบบ (Prerequisites)
* **Python:** เวอร์ชัน 3.8 – 3.12 (แนะนำ Python 3.12)
* **OS:** Windows 10 / 11

### 2. ติดตั้ง Libraries ที่จำเป็น
เปิด Terminal หรือ PowerShell ในโฟลเดอร์โปรเจกต์ แล้วรันคำสั่งต่อไปนี้:

```bash
python -m pip install numpy pandas pyserial pyqtgraph PyQt5 brainflow
```
*(หรือหากใช้ Python Launcher ของ Windows ให้รัน `py -m pip install numpy pandas pyserial pyqtgraph PyQt5 brainflow`)*

---

## 🚀 วิธีการใช้งาน (Usage Guide)

### 1. เริ่มต้นรันโปรแกรม
พิมพ์คำสั่งใน Terminal เพื่อเปิดระบบ:
```bash
python python.py
```

### 2. การตั้งค่าผ่านหน้าต่าง Console (Startup Configuration)
เมื่อรันโปรแกรม ระบบจะให้เลือกโหมดการทำงาน 2 ขั้นตอนผ่านหน้าต่าง Terminal:

* **ขั้นตอนที่ 1: เลือกแหล่งข้อมูลสัญญาณ EEG**
  * พิมพ์ `1` (**Playback Mode**): จำลองการทำงานจากไฟล์ `.csv` (ระบบจะค้นหาไฟล์ `S001R01.csv` หรือไฟล์ `.csv` แรกที่พบในโฟลเดอร์โดยอัตโนมัติ)
  * พิมพ์ `2` (**Hardware Mode**): เชื่อมต่อบอร์ดวัดคลื่นสมอง ADS1299/ADS1294 ผ่านพอร์ต Serial (ระบุ COM Port เช่น `COM3`)

* **ขั้นตอนที่ 2: เลือกการเชื่อมต่อโทรมาตรยานพาหนะ ESP32**
  * พิมพ์ `1` (**Standalone Mode**): ทดสอบประมวลผลและแสดงผลบนหน้าจออย่างเดียวโดยไม่ส่งออก Serial
  * พิมพ์ `2` (**ESP32 Bluetooth Serial Link**): เชื่อมต่อและส่งคำสั่งควบคุมไปยัง ESP32 (ระบุ COM Port เช่น `COM4`)

### 3. ขั้นตอนการปรับจูนก่อนใช้งาน (Calibration)
เมื่อหน้าต่าง GUI เปิดขึ้นมา ระบบจะล็อกสถานะเป็น `STOP` เพื่อความปลอดภัยจนกว่าจะทำการปรับจูนเสร็จสิ้น:
1. กดปุ่ม **"เริ่มต้นปรับจูน (CALIBRATION)"** ที่มุมซ้ายบน *(หากใช้โหมด Playback สามารถเลือกไฟล์ `.csv` ช่วงเพ่งสมาธิแยกต่างหากได้)*
2. **ช่วงที่ 1 (10 วินาที):** นั่งผ่อนคลาย ทำใจให้สบายเพื่อเก็บค่าฐานสภาวะพัก (Resting Baseline)
3. **ช่วงเตรียมตัว (3 วินาที):** เตรียมพร้อมก่อนเริ่มเพ่งสมาธิ
4. **ช่วงที่ 2 (10 วินาที):** เพ่งสมาธิจดจ่อกับจุดใดจุดหนึ่งเพื่อเก็บค่าสภาวะตื่นตัว (Active Focus)
5. เมื่อครบกำหนด ระบบจะคำนวณค่า `Threshold Low` และ `Threshold High` และเริ่มสั่งงานอัตโนมัติ

### 4. การควบคุมฉุกเฉิน (Emergency Override)
* กดปุ่ม **`SPACEBAR`** บนคีย์บอร์ดได้ตลอดเวลาเพื่อ **สั่งหยุดฉุกเฉิน (EMERGENCY STOP)** ทันที
* กด **`SPACEBAR`** ซ้ำอีกครั้งเพื่อปลดล็อกและกลับสู่การทำงานปกติ

---

## 📊 คำอธิบายหน้าจอแสดงผล (GUI Dashboard Overview)

| ส่วนประกอบ (Panel) | รายละเอียดการทำงาน |
| :--- | :--- |
| **Header & Status Bar** | แสดงสถานะปัจจุบัน, เปอร์เซ็นต์ความเชื่อมั่น (Confidence), ค่า Focus Ratio และเกณฑ์ Low/High |
| **Diagnostics Panel** | แสดงผลการวิเคราะห์คลื่นสมองทางคลินิก (Active Focus / Resting / Drowsy) และทิศทางที่ควรจะเป็น |
| **Telemetry Box** | แสดงสถานะการเชื่อมต่อ ESP32, รหัสฐานสิบหก (Hex Stream) ที่ส่งออก และสถานะนับถอยหลัง Debounce |
| **RAW EEG (Cz)** | กราฟสัญญาณดิบจากตำแหน่งอิเล็กโทรด Cz (ก่อนผ่านตัวกรอง) |
| **FILTERED (CAR + 1-30Hz)** | กราฟสัญญาณที่ผ่านการกรองสัญญาณรบกวนและตัดคลื่นความถี่นอกย่านแล้ว |
| **PSD SPECTRUM (Welch)** | กราฟความหนาแน่นสเปกตรัมพลังงาน (Power Spectral Density) ย่านความถี่ 0 – 35 Hz |
| **BAND POWER RATIO (%)** | กราฟแท่งเปรียบเทียบสัดส่วนพลังงานคลื่นสมอง 3 ย่านหลัก: **Theta (4–8Hz)**, **Alpha (8–13Hz)** และ **Beta (13–30Hz)** |

---

## 📡 โปรโตคอลการสื่อสาร (ESP32 Binary Telemetry Protocol)

ระบบส่งข้อมูลออกไปยัง ESP32 ทุกๆ `100 ms` (ความถี่ 10 Hz) ที่ Baudrate **115200 bps** ในรูปแบบ Binary Packet ขนาด **6 Bytes**:

| Byte Index | ชื่อฟิลด์ | ค่า / รายละเอียด |
| :---: | :--- | :--- |
| `Byte 0` | **Header 1** | `0xAA` (Start Byte 1) |
| `Byte 1` | **Header 2** | `0x55` (Start Byte 2) |
| `Byte 2` | **Sequence** | `0x00` – `0xFF` (ตัวนับลำดับแพ็กเกจวนซ้ำ) |
| `Byte 3` | **Command** | `0x00` = **STOP** (หยุดนิ่ง), `0x01` = **MOVE_FORWARD** (เดินหน้า) |
| `Byte 4` | **Checksum** | ค่า **CRC-8** (Polynomial `0x07`, Init `0x00`) คำนวณจาก Byte 0 ถึง Byte 3 |
| `Byte 5` | **Footer** | `0x0A` (Newline / End Byte) |

---

## 📁 โครงสร้างไฟล์ในโปรเจกต์ (Project Structure)

```text
Project/
├── python.py          # ไฟล์ซอร์สโค้ดหลัก (Main Application & DSP Thread)
├── S001R01.csv        # ไฟล์ข้อมูลตัวอย่าง EEG สำหรับโหมด Playback (8 Channels, 250Hz)
└── README.md          # เอกสารคู่มือการใช้งานระบบ
```

---

## ⚠️ ข้อควรระวังในการใช้งาน (Troubleshooting)

* **หากรันโหมด Playback แล้วไม่มีกราฟขึ้น:** ตรวจสอบว่ามีไฟล์ `.csv` ที่มีข้อมูลตัวเลขอย่างน้อย 8 คอลัมน์วางอยู่ในโฟลเดอร์เดียวกับไฟล์ `python.py` หรือไม่
* **แจ้งเตือน `สายหลุดหรือเกิด Artifact ขนาดใหญ่`:** เกิดจากสัญญาณ EEG มีค่าแอมพลิจูดเกิน `4000 µV` หรือสัญญาณนิ่งสนิท (Flatline) ให้ตรวจสอบการแนบของอิเล็กโทรดและสายกราวด์ก่อนเริ่มใช้งานใหม่

# 🧠 CONVERTER: EDF TO CSV

เครื่องมือ Command-Line Interface (CLI) สำหรับอ่านและแปลงไฟล์สัญญาณคลื่นไฟฟ้าสมองมาตรฐานทางการแพทย์ **EDF (European Data Format)** ให้อยู่ในรูปแบบ **CSV 24 คอลัมน์** ตามโครงสร้างมาตรฐานของ **OpenBCI Cyton / BrainFlow** เพื่อนำไปใช้จำลองการสตรีมข้อมูล (Playback) หรือวิเคราะห์ผลต่อในระบบประมวลผลสัญญาณ BCI

---

## ✨ คุณสมบัติหลัก (Features)

* **Dynamic CLI Input:** รองรับการป้อนชื่อไฟล์ต้นทาง (`.edf`) และไฟล์ปลายทาง (`.csv`) แบบโต้ตอบ พร้อมระบบเติม นามสกุลไฟล์ให้อัตโนมัติ และมีค่าเริ่มต้น (Default Values) รองรับหากกด Enter ผ่าน
* **Medical-Grade Unit Conversion:** แปลงหน่วยศักย์ไฟฟ้าของสัญญาณ EEG จาก **Volts ($V$)** เป็น **Microvolts ($\mu V$)** โดยอัตโนมัติ ($\times 10^6$) ตามมาตรฐานสัญญาณทางคลินิก
* **Channel Extraction & Auto-Padding:** คัดเลือกสัญญาณประเภท EEG จำนวน 8 ช่องแรกจากไฟล์ต้นทาง หากไฟล์ต้นทางมีไม่ถึง 8 ช่อง ระบบจะทำการเติมค่า `0` (Zero-padding) ในช่องที่เหลือให้อัตโนมัติ
* **BrainFlow / OpenBCI Cyton Compatibility:** จัดเรียงโครงสร้างเมทริกซ์ขนาด 24 คอลัมน์ พร้อมสร้าง Packet Counter (`0–255`) ในคอลัมน์แรกเพื่อให้เข้ากันได้กับไลบรารี BrainFlow

---

## 🛠️ ข้อกำหนดของระบบและการติดตั้ง (Prerequisites & Installation)

### 1. ความต้องการของระบบ
* **Python:** เวอร์ชัน 3.8 ขึ้นไป (แนะนำให้ติ๊กเลือก *"Add Python to PATH"* ระหว่างการติดตั้งบน Windows)
* **Libraries:** `mne`, `numpy`

### 2. ขั้นตอนการติดตั้ง
1. ดาวน์โหลดหรือโคลนไฟล์สคริปต์ (`script.py`) ลงในโฟลเดอร์โปรเจกต์ของคุณ
2. เปิด Terminal หรือ Command Prompt ในโฟลเดอร์โปรเจกต์ แล้วติดตั้งไลบรารีที่จำเป็นด้วยคำสั่ง:

```bash
pip install mne numpy