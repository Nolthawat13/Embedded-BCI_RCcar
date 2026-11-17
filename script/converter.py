import os
import mne
import numpy as np

print("=================================================================")
print("     CONVERTER: EDF TO CSV)     ")
print("=================================================================")

# -----------------------------------------------------------------------------
# 1. รับชื่อไฟล์ต้นทาง (.edf)
# -----------------------------------------------------------------------------
raw_edf_input = input("ระบุชื่อไฟล์ EDF ต้นทาง [ค่าเริ่มต้น 'S001R01.edf']: ").strip()
if not raw_edf_input:
    edf_filename = "S001R01.edf"
else:
    edf_filename = raw_edf_input if raw_edf_input.endswith('.edf') else f"{raw_edf_input}.edf"

# ตรวจสอบความถูกต้องว่ามีไฟล์ต้นทางอยู่ใน Directory หรือไม่
if not os.path.exists(edf_filename):
    print(f"\n[ข้อผิดพลาด] ไม่พบไฟล์ '{edf_filename}' ในโฟลเดอร์ปัจจุบัน")
    print("กรุณาวางไฟล์ .edf ไว้ในโฟลเดอร์นี้แล้วลองใหม่อีกครั้ง")
    exit()

# -----------------------------------------------------------------------------
# 2. รับชื่อไฟล์ปลายทาง (.csv)
# -----------------------------------------------------------------------------
raw_csv_input = input("ระบุชื่อไฟล์ CSV ปลายทาง [ค่าเริ่มต้น 'test1.csv']: ").strip()
if not raw_csv_input:
    output_filename = "test1.csv"
else:
    output_filename = raw_csv_input if raw_csv_input.endswith('.csv') else f"{raw_csv_input}.csv"

# -----------------------------------------------------------------------------
# 3. กระบวนการอ่านและแปลงสัญญาณตามมาตรฐานทางการแพทย์
# -----------------------------------------------------------------------------
try:
    print(f"\n[กำลังดำเนินการ] กำลังอ่านสัญญาณ EDF จากไฟล์ '{edf_filename}'...")
    raw = mne.io.read_raw_edf(edf_filename, preload=True, verbose=False)

    # คัดเลือกเฉพาะสัญญาณประเภท EEG จำนวน 8 ช่องแรก
    eeg_picks = mne.pick_types(raw.info, eeg=True)[:8]
    
    if len(eeg_picks) < 8:
        print(f"[คำเตือน] พบช่องสัญญาณ EEG เพียง {len(eeg_picks)} ช่อง (ระบบจะขยายช่องสัญญาณให้ครบ 8 ช่อง)")

    # ดึงข้อมูลสัญญาณและแปลงหน่วยจาก Volts (V) เป็น Microvolts (uV) ตามมาตรฐาน EEG ทางการแพทย์
    eeg_data = raw.get_data(picks=eeg_picks) * 1e6  

    num_samples = eeg_data.shape[1]

    # สร้าง Matrix ขนาด 24 คอลัมน์ ตามโครงสร้างมาตรฐาน OpenBCI Cyton / BrainFlow
    brainflow_matrix = np.zeros((num_samples, 24))
    
    # คอลัมน์ 0: ตัวนับแพ็กเกจข้อมูล (Packet Counter 0-255)
    brainflow_matrix[:, 0] = np.arange(num_samples) % 256
    
    # คอลัมน์ 1 ถึง 8: สัญญาณ EEG จำนวน 8 ช่องจริง (Transpose ข้อมูล)
    actual_channels = eeg_data.shape[0]
    brainflow_matrix[:, 1:1 + actual_channels] = eeg_data.T 

    # -------------------------------------------------------------------------
    # 4. บันทึกเป็นไฟล์ CSV ด้วยตัวคั่น Comma (,) เพื่อความสมบูรณ์แบบในการ Parse
    # -------------------------------------------------------------------------
    np.savetxt(output_filename, brainflow_matrix, fmt="%.6f", delimiter=",")
    
    print(f"[สำเร็จ] แปลงไฟล์ '{edf_filename}' -> '{output_filename}' เรียบร้อยแล้ว (รูปแบบ 24 ช่องสัญญาณ)")
    print(f"[คำแนะนำ] คุณสามารถรันโปรแกรมหลักและโหลดไฟล์ '{output_filename}' ในโหมด 1 ได้ทันที")

except Exception as e:
    print(f"\n[ข้อผิดพลาด] การแปลงไฟล์ล้มเหลว: {str(e)}")