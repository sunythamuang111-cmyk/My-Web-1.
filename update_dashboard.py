import os
import sys
import csv
import json
import re
import webbrowser
from datetime import datetime

# จัดการ Encoding บน Windows Console เพื่อป้องกัน UnicodeEncodeError สำหรับ Emoji
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

def parse_date(date_str):
    """
    แปลงสตริงวันที่ให้อยู่ในรูปแบบ datetime.date
    รองรับทั้งปี ค.ศ. และ พ.ศ. รวมถึงรูปแบบ d/m/Y, Y-m-d, d-m-Y
    """
    if not date_str or not str(date_str).strip():
        return None
    cleaned = str(date_str).strip()
    
    formats = ('%d/%m/%Y', '%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%m/%d/%Y', '%d/%m/%y')
    for fmt in formats:
        try:
            dt = datetime.strptime(cleaned, fmt).date()
            # หากปีที่อ่านได้เป็นปี พ.ศ. (มากกว่า 2400) ให้แปลงเป็น ค.ศ. เพื่อการคำนวณที่ถูกต้อง
            if dt.year > 2400:
                dt = dt.replace(year=dt.year - 543)
            return dt
        except ValueError:
            pass
    return None

def extract_brought_forward(note_text):
    """
    สกัดยอดยกมาจากข้อความในช่องหมายเหตุ (note)
    รองรับข้อความเช่น:
    - 'วันลาพักผ่อนยกมาจากปีงบประมาณ 2568: 11 วัน'
    - 'ยกมา 11 วัน'
    - 'ยอดยกมา 10.5 วัน'
    - 'สะสมจากปี 2568 จำนวน 12 วัน'
    """
    if not note_text:
        return None
    text = str(note_text).strip()
    
    # ตรวจสอบว่ามีคำสำคัญเกี่ยวกับการยกยอดหรือสะสม
    if not any(k in text for k in ['ยกมา', 'สะสม', 'ยอดยก']):
        return None

    # ลบส่วนระบุปี เช่น "ปีงบประมาณ 2568", "ปี 2568", "ปี 2025" ออกก่อน เพื่อไม่ให้สับสนกับตัวเลขจำนวนวันลา
    cleaned = re.sub(r'(?:ปีงบประมาณ|ปี\s*งบประมาณ|ปี)\s*(?:25\d{2}|20\d{2})', '', text)

    # 1. มองหาตัวเลขที่อยู่หน้าคำว่า 'วัน' ก่อนเป็นอันดับแรก (เช่น "11 วัน", "11.5 วัน")
    match_days = re.search(r'(\d+(?:\.\d+)?)\s*วัน', cleaned)
    if match_days:
        try:
            return float(match_days.group(1))
        except ValueError:
            pass

    # 2. มองหาตัวเลขหลังเครื่องหมายโคลอน : หรือคำว่า จำนวน / คือ
    match_colon = re.search(r'(?:[:=]|จำนวน|คือ)\s*(\d+(?:\.\d+)?)', cleaned)
    if match_colon:
        try:
            return float(match_colon.group(1))
        except ValueError:
            pass

    # 3. มองหาตัวเลขแรกที่พบในข้อความที่ถูกกรองปีออกแล้ว
    match_any = re.search(r'(\d+(?:\.\d+)?)', cleaned)
    if match_any:
        try:
            return float(match_any.group(1))
        except ValueError:
            pass

    return None

def determine_fiscal_year(date_obj):
    """
    คำนวณปีงบประมาณ (พ.ศ.) จากวันที่
    ปีงบประมาณไทย: เริ่ม 1 ต.ค. (ปีก่อนหน้า) ถึง 30 ก.ย. (ปีปัจจุบัน)
    """
    if not date_obj:
        return None
    ce_year = date_obj.year
    if date_obj.month >= 10:
        fy_ce = ce_year + 1
    else:
        fy_ce = ce_year
    return fy_ce + 543

def process_leave_data(csv_path):
    """
    อ่านข้อมูลจาก CSV และประมวลผลคำนวณสิทธิ์วันลา วันลาที่ใช้ และวันลาคงเหลือ
    ตามกฎเกณฑ์ปีงบประมาณ (ลาป่วย 20 วัน แบ่ง 2 รอบ, ลาพักผ่อน 10 วัน + ยอดยกมา)
    """
    if not os.path.exists(csv_path):
        print(f"[!] ไม่พบไฟล์: {csv_path}")
        return None

    records = []
    with open(csv_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cleaned_row = {k.strip(): (v.strip() if v else '') for k, v in row.items() if k}
            records.append(cleaned_row)

    if not records:
        print("[!] ไฟล์ CSV ว่างเปล่า")
        return None

    employees = {}
    all_fiscal_years = set()

    for r in records:
        emp_id = r.get('emp_id', '').strip() or 'EMP001'
        emp_name = r.get('emp_name', '').strip() or emp_id
        leave_type = r.get('leave_type', '').strip()
        start_date_str = r.get('start_date', '').strip()
        end_date_str = r.get('end_date', '').strip()
        note = r.get('note', '').strip()

        start_date = parse_date(start_date_str)
        end_date = parse_date(end_date_str)
        ref_date = start_date or end_date

        fy_str = r.get('fiscal_year', '').strip()
        if fy_str:
            try:
                fy = int(fy_str)
            except ValueError:
                fy = determine_fiscal_year(ref_date) or 2569
        else:
            fy = determine_fiscal_year(ref_date) or 2569

        all_fiscal_years.add(fy)

        try:
            days_str = str(r.get('days_taken', 0)).replace(',', '.').strip()
            days_taken = float(days_str) if days_str else 0.0
        except ValueError:
            days_taken = 0.0

        if emp_id not in employees:
            employees[emp_id] = {
                'emp_id': emp_id,
                'emp_name': emp_name,
                'by_fiscal_year': {}
            }

        if fy not in employees[emp_id]['by_fiscal_year']:
            employees[emp_id]['by_fiscal_year'][fy] = {
                'fiscal_year': fy,
                'brought_forward': 0.0,
                'vacation_new_quota': 10.0,
                'vacation_used': 0.0,
                'sick_quota_round1': 10.0,
                'sick_used_round1': 0.0,
                'sick_quota_round2': 10.0,
                'sick_used_round2': 0.0,
                'history': []
            }

        fy_data = employees[emp_id]['by_fiscal_year'][fy]

        # ตรวจสอบยอดยกมาจากหมายเหตุ
        bf_extracted = extract_brought_forward(note)
        if bf_extracted is not None:
            fy_data['brought_forward'] = bf_extracted

        # บันทึกรายการประวัติการลา
        fy_data['history'].append({
            'leave_type': leave_type,
            'start_date': start_date_str,
            'end_date': end_date_str,
            'days_taken': days_taken,
            'note': note
        })

        # คำนวณวันลาที่ใช้ตามประเภท
        if 'พักผ่อน' in leave_type:
            # รายการที่เป็นการยกยอดมาแต่ days_taken = 0 จะไม่เพิ่มวันใช้ไป
            fy_data['vacation_used'] += days_taken
        elif 'ป่วย' in leave_type:
            ce_year = fy - 543
            oct1_prev = datetime(ce_year - 1, 10, 1).date()
            mar31_curr = datetime(ce_year, 3, 31).date()

            if ref_date:
                if oct1_prev <= ref_date <= mar31_curr:
                    fy_data['sick_used_round1'] += days_taken
                else:
                    fy_data['sick_used_round2'] += days_taken
            else:
                # ถ้าไม่มีวันที่ ให้อ้างอิงจากข้อความใน note
                if 'รอบ 1' in note or 'รอบที่ 1' in note or 'ครึ่งปีแรก' in note:
                    fy_data['sick_used_round1'] += days_taken
                else:
                    fy_data['sick_used_round2'] += days_taken

    # สรุปยอดคงเหลือและส่งต่อยอดสะสมไปปีถัดไป (Rollover Support)
    sorted_years = sorted(list(all_fiscal_years))
    for emp_id, emp_info in employees.items():
        prev_vacation_rem = None
        for fy in sorted_years:
            if fy not in emp_info['by_fiscal_year']:
                continue
            fy_data = emp_info['by_fiscal_year'][fy]

            # หากไม่ได้ระบุยอดยกมาในหมายเหตุ และมีปีก่อนหน้า ให้ใช้ยอดคงเหลือจากปีก่อน
            if fy_data['brought_forward'] == 0.0 and prev_vacation_rem is not None:
                fy_data['brought_forward'] = prev_vacation_rem

            total_entitled = fy_data['brought_forward'] + fy_data['vacation_new_quota']
            fy_data['vacation_total_entitled'] = total_entitled
            fy_data['vacation_remaining'] = max(0.0, total_entitled - fy_data['vacation_used'])
            prev_vacation_rem = fy_data['vacation_remaining']

            fy_data['sick_remaining_round1'] = max(0.0, fy_data['sick_quota_round1'] - fy_data['sick_used_round1'])
            fy_data['sick_remaining_round2'] = max(0.0, fy_data['sick_quota_round2'] - fy_data['sick_used_round2'])
            fy_data['sick_remaining_total'] = fy_data['sick_remaining_round1'] + fy_data['sick_remaining_round2']
            fy_data['sick_used_total'] = fy_data['sick_used_round1'] + fy_data['sick_used_round2']
            fy_data['total_all_leave_used'] = fy_data['vacation_used'] + fy_data['sick_used_total']

    return {
        'fiscal_years': sorted_years,
        'employees': employees,
        'generated_at': datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    }

def generate_html_dashboard(data, output_html_path):
    """
    สร้างไฟล์ HTML Dashboard สวยงาม ทันสมัย แบบ Interactive หน้าเดียว
    """
    data_json = json.dumps(data, ensure_ascii=False)

    html_content = f"""<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ระบบติดตามวันลาและสิทธิ์คงเหลือประจำปีงบประมาณ</title>
    <!-- Fonts Google -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Prompt:wght@400;500;600;700&family=Sarabun:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --primary: #1e3a8a;
            --primary-light: #3b82f6;
            --accent: #0284c7;
            --success: #10b981;
            --success-bg: #ecfdf5;
            --warning: #f59e0b;
            --warning-bg: #fffbeb;
            --danger: #ef4444;
            --danger-bg: #fef2f2;
            --bg: #f1f5f9;
            --card-bg: #ffffff;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --border: #e2e8f0;
            --shadow-sm: 0 1px 3px rgba(0,0,0,0.06);
            --shadow-md: 0 4px 12px -2px rgba(0,0,0,0.08);
            --shadow-lg: 0 10px 25px -5px rgba(30, 58, 138, 0.15);
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Sarabun', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }}

        body {{
            background-color: var(--bg);
            color: var(--text-main);
            min-height: 100vh;
            padding: 24px 20px;
            -webkit-font-smoothing: antialiased;
        }}

        .container {{
            max-width: 1240px;
            margin: 0 auto;
        }}

        /* Header */
        header {{
            background: linear-gradient(135deg, #1e3a8a 0%, #0369a1 100%);
            color: white;
            padding: 28px 32px;
            border-radius: 18px;
            box-shadow: var(--shadow-lg);
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
        }}

        .header-title h1 {{
            font-family: 'Prompt', sans-serif;
            font-size: 1.65rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 10px;
            letter-spacing: -0.3px;
        }}

        .header-title p {{
            font-size: 0.95rem;
            opacity: 0.9;
            margin-top: 6px;
            font-weight: 300;
        }}

        .header-badge-group {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }}

        .badge-live {{
            background-color: rgba(255, 255, 255, 0.18);
            padding: 6px 14px;
            border-radius: 9999px;
            font-size: 0.85rem;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            border: 1px solid rgba(255, 255, 255, 0.25);
            backdrop-filter: blur(4px);
        }}

        .badge-live::before {{
            content: '';
            width: 8px;
            height: 8px;
            background-color: #4ade80;
            border-radius: 50%;
            display: inline-block;
            box-shadow: 0 0 8px #4ade80;
        }}

        .btn-print {{
            background: rgba(255, 255, 255, 0.95);
            color: var(--primary);
            border: none;
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 0.88rem;
            font-weight: 600;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.2s;
        }}

        .btn-print:hover {{
            background: #ffffff;
            transform: translateY(-1px);
            box-shadow: 0 4px 10px rgba(0,0,0,0.15);
        }}

        /* Controls Section */
        .controls {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 18px;
            background: var(--card-bg);
            padding: 22px 26px;
            border-radius: 16px;
            box-shadow: var(--shadow-sm);
            border: 1px solid var(--border);
            margin-bottom: 24px;
        }}

        .control-group {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}

        .control-group label {{
            font-size: 0.92rem;
            font-weight: 600;
            color: var(--text-muted);
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        select {{
            padding: 11px 16px;
            border-radius: 10px;
            border: 1.5px solid var(--border);
            background-color: #fff;
            color: var(--text-main);
            font-size: 1rem;
            outline: none;
            cursor: pointer;
            transition: all 0.2s ease;
            font-weight: 500;
        }}

        select:focus {{
            border-color: var(--primary-light);
            box-shadow: 0 0 0 3.5px rgba(59, 130, 246, 0.15);
        }}

        /* KPI Cards */
        .grid-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 18px;
            margin-bottom: 24px;
        }}

        .card {{
            background: var(--card-bg);
            padding: 22px;
            border-radius: 16px;
            border: 1px solid var(--border);
            box-shadow: var(--shadow-sm);
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            position: relative;
            overflow: hidden;
            transition: transform 0.2s, box-shadow 0.2s;
        }}

        .card:hover {{
            transform: translateY(-2px);
            box-shadow: var(--shadow-md);
        }}

        .card::after {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 5px;
            height: 100%;
        }}

        .card.card-bf::after {{ background-color: #6366f1; }}
        .card.card-vacation::after {{ background-color: #0284c7; }}
        .card.card-sick1::after {{ background-color: #10b981; }}
        .card.card-sick2::after {{ background-color: #f59e0b; }}

        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 12px;
        }}

        .card-title {{
            font-size: 0.92rem;
            font-weight: 600;
            color: var(--text-muted);
        }}

        .card-icon-wrap {{
            width: 38px;
            height: 38px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.25rem;
        }}

        .icon-bf {{ background-color: #e0e7ff; }}
        .icon-vacation {{ background-color: #e0f2fe; }}
        .icon-sick1 {{ background-color: #d1fae5; }}
        .icon-sick2 {{ background-color: #fef3c7; }}

        .card-value-box {{
            display: flex;
            align-items: baseline;
            gap: 6px;
            margin: 6px 0;
        }}

        .card-value {{
            font-family: 'Prompt', sans-serif;
            font-size: 2.3rem;
            font-weight: 700;
            line-height: 1;
        }}

        .card-unit {{
            font-size: 0.95rem;
            font-weight: 500;
            color: var(--text-muted);
        }}

        .card-subtext {{
            font-size: 0.86rem;
            color: var(--text-muted);
            margin-top: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .progress-bar-bg {{
            width: 100%;
            height: 8px;
            background-color: #e2e8f0;
            border-radius: 9999px;
            overflow: hidden;
            margin-top: 12px;
        }}

        .progress-bar-fill {{
            height: 100%;
            border-radius: 9999px;
            transition: width 0.5s ease-in-out;
        }}

        .fill-vacation {{ background: linear-gradient(90deg, #38bdf8, #0284c7); }}
        .fill-sick1 {{ background: linear-gradient(90deg, #34d399, #10b981); }}
        .fill-sick2 {{ background: linear-gradient(90deg, #fbbf24, #f59e0b); }}

        /* Breakdown Details Grid */
        .details-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 24px;
        }}

        @media (max-width: 860px) {{
            .details-grid {{ grid-template-columns: 1fr; }}
        }}

        .detail-card {{
            background: var(--card-bg);
            border-radius: 16px;
            padding: 24px;
            border: 1px solid var(--border);
            box-shadow: var(--shadow-sm);
        }}

        .detail-card h3 {{
            font-family: 'Prompt', sans-serif;
            font-size: 1.15rem;
            font-weight: 600;
            margin-bottom: 18px;
            display: flex;
            align-items: center;
            gap: 10px;
            color: var(--primary);
        }}

        .rule-list {{
            list-style: none;
            display: flex;
            flex-direction: column;
            gap: 14px;
        }}

        .rule-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.95rem;
            padding-bottom: 10px;
            border-bottom: 1px dashed var(--border);
        }}

        .rule-item:last-child {{
            border-bottom: none;
            padding-bottom: 0;
            padding-top: 4px;
        }}

        .rule-label {{
            color: var(--text-muted);
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        .rule-val {{
            font-weight: 600;
            color: var(--text-main);
        }}

        /* Table Section */
        .table-section {{
            background: var(--card-bg);
            border-radius: 16px;
            padding: 24px;
            border: 1px solid var(--border);
            box-shadow: var(--shadow-sm);
        }}

        .table-header-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 14px;
            margin-bottom: 18px;
        }}

        .table-title {{
            font-family: 'Prompt', sans-serif;
            font-size: 1.18rem;
            font-weight: 600;
            color: var(--text-main);
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .search-box {{
            position: relative;
            min-width: 240px;
        }}

        .search-box input {{
            width: 100%;
            padding: 8px 14px 8px 34px;
            border-radius: 8px;
            border: 1.5px solid var(--border);
            font-size: 0.9rem;
            outline: none;
            transition: all 0.2s;
        }}

        .search-box input:focus {{
            border-color: var(--primary-light);
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
        }}

        .search-box::before {{
            content: '🔍';
            position: absolute;
            left: 10px;
            top: 50%;
            transform: translateY(-50%);
            font-size: 0.85rem;
            opacity: 0.6;
        }}

        .table-wrapper {{
            overflow-x: auto;
            border-radius: 12px;
            border: 1px solid var(--border);
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.94rem;
            text-align: left;
        }}

        thead th {{
            background-color: #f8fafc;
            padding: 14px 18px;
            font-weight: 600;
            color: var(--text-muted);
            border-bottom: 1.5px solid var(--border);
            white-space: nowrap;
        }}

        tbody td {{
            padding: 14px 18px;
            border-bottom: 1px solid var(--border);
            color: var(--text-main);
        }}

        tbody tr:last-child td {{
            border-bottom: none;
        }}

        tbody tr:hover {{
            background-color: #f8fafc;
        }}

        .tag {{
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 5px 12px;
            border-radius: 6px;
            font-size: 0.85rem;
            font-weight: 600;
        }}

        .tag-vacation {{
            background-color: #e0f2fe;
            color: #0369a1;
        }}

        .tag-sick {{
            background-color: #fef3c7;
            color: #b45309;
        }}

        footer {{
            text-align: center;
            color: var(--text-muted);
            font-size: 0.86rem;
            margin-top: 32px;
            padding: 14px;
        }}

        /* Print Style */
        @media print {{
            body {{
                background-color: #fff;
                padding: 0;
            }}
            .badge-live, .btn-print, .controls, .search-box {{
                display: none !important;
            }}
            .card, .detail-card, .table-section {{
                box-shadow: none !important;
                border: 1px solid #ccc !important;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <header>
            <div class="header-title">
                <h1>📊 ระบบติดตามวันลาและสิทธิ์คงเหลือ</h1>
                <p>คำนวณตามระเบียบปีงบประมาณ • ลาป่วย 20 วัน (แบ่ง 2 รอบ) • ลาพักผ่อน 10 วัน + ยอดยกมาสะสม</p>
            </div>
            <div class="header-badge-group">
                <div class="badge-live">อัปเดตอัตโนมัติ: <span id="gen-time">{data.get('generated_at', '-')}</span></div>
                <button class="btn-print" onclick="window.print()">🖨️ พิมพ์รายงาน</button>
            </div>
        </header>

        <!-- Controls Filter -->
        <section class="controls">
            <div class="control-group">
                <label for="fy-select">📅 เลือกปีงบประมาณ</label>
                <select id="fy-select" onchange="updateView()"></select>
            </div>
            <div class="control-group">
                <label for="emp-select">👤 เลือกรายชื่อพนักงาน</label>
                <select id="emp-select" onchange="updateView()"></select>
            </div>
        </section>

        <!-- KPI Metric Cards -->
        <section class="grid-cards">
            <!-- 1. ยอดยกมาวันพักผ่อน -->
            <div class="card card-bf">
                <div class="card-header">
                    <span class="card-title">ยอดยกมาวันพักผ่อน</span>
                    <div class="card-icon-wrap icon-bf">📥</div>
                </div>
                <div class="card-value-box">
                    <span class="card-value" id="val-bf" style="color: #4f46e5;">0</span>
                    <span class="card-unit">วัน</span>
                </div>
                <div class="card-subtext">
                    <span>จากปีงบประมาณก่อนหน้า</span>
                    <span>สิทธิ์สะสม</span>
                </div>
            </div>

            <!-- 2. วันลาพักผ่อนคงเหลือสุทธิ -->
            <div class="card card-vacation">
                <div class="card-header">
                    <span class="card-title">วันลาพักผ่อนคงเหลือสุทธิ</span>
                    <div class="card-icon-wrap icon-vacation">🏖️</div>
                </div>
                <div class="card-value-box">
                    <span class="card-value" id="val-vacation-rem" style="color: #0284c7;">0</span>
                    <span class="card-unit">วัน</span>
                </div>
                <div class="card-subtext">
                    <span>ใช้ไป <strong id="val-vacation-used" style="color: var(--danger);">0</strong> วัน</span>
                    <span>สิทธิ์รวม <strong id="val-vacation-entitled">0</strong> วัน</span>
                </div>
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill fill-vacation" id="bar-vacation" style="width: 0%;"></div>
                </div>
            </div>

            <!-- 3. วันลาป่วยคงเหลือ รอบ 1 -->
            <div class="card card-sick1">
                <div class="card-header">
                    <span class="card-title">ลาป่วยคงเหลือ รอบ 1</span>
                    <div class="card-icon-wrap icon-sick1">🩺</div>
                </div>
                <div class="card-value-box">
                    <span class="card-value" id="val-sick1-rem" style="color: #10b981;">0</span>
                    <span class="card-unit">วัน</span>
                </div>
                <div class="card-subtext">
                    <span>ใช้ไป <strong id="val-sick1-used" style="color: var(--danger);">0</strong> วัน</span>
                    <span>1 ต.ค. - 31 มี.ค. (เต็ม 10 วัน)</span>
                </div>
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill fill-sick1" id="bar-sick1" style="width: 0%;"></div>
                </div>
            </div>

            <!-- 4. วันลาป่วยคงเหลือ รอบ 2 -->
            <div class="card card-sick2">
                <div class="card-header">
                    <span class="card-title">ลาป่วยคงเหลือ รอบ 2</span>
                    <div class="card-icon-wrap icon-sick2">💊</div>
                </div>
                <div class="card-value-box">
                    <span class="card-value" id="val-sick2-rem" style="color: #f59e0b;">0</span>
                    <span class="card-unit">วัน</span>
                </div>
                <div class="card-subtext">
                    <span>ใช้ไป <strong id="val-sick2-used" style="color: var(--danger);">0</strong> วัน</span>
                    <span>1 เม.ย. - 30 ก.ย. (เต็ม 10 วัน)</span>
                </div>
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill fill-sick2" id="bar-sick2" style="width: 0%;"></div>
                </div>
            </div>
        </section>

        <!-- Detailed Breakdown -->
        <section class="details-grid">
            <!-- สรุปสิทธิ์วันลาพักผ่อน -->
            <div class="detail-card">
                <h3>🏖️ สรุปสิทธิ์วันลาพักผ่อนประจำปี</h3>
                <div class="rule-list">
                    <div class="rule-item">
                        <span class="rule-label">📥 ยอดยกมาจากปีงบประมาณก่อนหน้า</span>
                        <span class="rule-val" id="detail-vacation-bf">0 วัน</span>
                    </div>
                    <div class="rule-item">
                        <span class="rule-label">✨ สิทธิ์ใหม่ประจำปีงบประมาณ</span>
                        <span class="rule-val" style="color: #10b981;">+10.0 วัน</span>
                    </div>
                    <div class="rule-item">
                        <span class="rule-label">📊 สิทธิ์วันลาพักผ่อนรวมสุทธิ</span>
                        <span class="rule-val" id="detail-vacation-entitled" style="color: var(--primary);">0 วัน</span>
                    </div>
                    <div class="rule-item">
                        <span class="rule-label">📉 จำนวนวันที่ใช้ไปในปีนี้</span>
                        <span class="rule-val" id="detail-vacation-used" style="color: var(--danger);">-0 วัน</span>
                    </div>
                    <div class="rule-item" style="font-weight: 700; font-size: 1.05rem;">
                        <span class="rule-label" style="color: var(--text-main);">🎯 วันลาพักผ่อนคงเหลือสุทธิ</span>
                        <span class="rule-val" id="detail-vacation-rem" style="color: #0284c7; font-size: 1.15rem;">0 วัน</span>
                    </div>
                </div>
            </div>

            <!-- สรุปสิทธิ์วันลาป่วย -->
            <div class="detail-card">
                <h3>🩺 สรุปสิทธิ์วันลาป่วย (โควตา 20 วัน แบ่ง 2 รอบ)</h3>
                <div class="rule-list">
                    <div class="rule-item">
                        <span class="rule-label">รอบ 1: ครึ่งปีแรก (1 ต.ค. - 31 มี.ค.)</span>
                        <span class="rule-val">โควตา 10 วัน • ใช้ <span id="detail-sick1-used" style="color: var(--danger);">0</span> วัน • เหลือ <span id="detail-sick1-rem" style="color: var(--success);">10</span> วัน</span>
                    </div>
                    <div class="rule-item">
                        <span class="rule-label">รอบ 2: ครึ่งปีหลัง (1 เม.ย. - 30 ก.ย.)</span>
                        <span class="rule-val">โควตา 10 วัน • ใช้ <span id="detail-sick2-used" style="color: var(--danger);">0</span> วัน • เหลือ <span id="detail-sick2-rem" style="color: var(--warning);">10</span> วัน</span>
                    </div>
                    <div class="rule-item">
                        <span class="rule-label">ยอดรวมการลาป่วยทั้งปีงบประมาณ</span>
                        <span class="rule-val" id="detail-sick-total-used">0 วัน</span>
                    </div>
                    <div class="rule-item" style="font-weight: 700; font-size: 1.05rem;">
                        <span class="rule-label" style="color: var(--text-main);">🎯 วันลาป่วยคงเหลือรวมทั้งสิ้น</span>
                        <span class="rule-val" id="detail-sick-total-rem" style="color: var(--success); font-size: 1.15rem;">20 วัน</span>
                    </div>
                </div>
            </div>
        </section>

        <!-- Leave History Table -->
        <section class="table-section">
            <div class="table-header-row">
                <div class="table-title">
                    <span>📝 ประวัติและบันทึกการลา</span>
                    <span style="font-size: 0.88rem; font-weight: normal; color: var(--text-muted); background: #f1f5f9; padding: 3px 10px; border-radius: 9999px;" id="table-count">0 รายการ</span>
                </div>
                <div class="search-box">
                    <input type="text" id="table-search" placeholder="ค้นหาประวัติการลา..." oninput="renderTable()">
                </div>
            </div>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr>
                            <th style="width: 15%;">ประเภทการลา</th>
                            <th style="width: 15%;">วันที่เริ่มต้น</th>
                            <th style="width: 15%;">วันที่สิ้นสุด</th>
                            <th style="width: 12%; text-align: center;">จำนวนวัน</th>
                            <th style="width: 43%;">หมายเหตุ / รายละเอียดรอบ</th>
                        </tr>
                    </thead>
                    <tbody id="history-tbody">
                    </tbody>
                </table>
            </div>
        </section>

        <footer>
            ระบบติดตามวันลาและแดชบอร์ดอัตโนมัติ • ข้อมูลประมวลผลจาก leave_data.csv แบบ One-Click Automation
        </footer>
    </div>

    <!-- JavaScript Interactive Logic -->
    <script>
        const rawData = {data_json};
        let currentHistory = [];

        function init() {{
            const fySelect = document.getElementById('fy-select');
            const empSelect = document.getElementById('emp-select');

            fySelect.innerHTML = '';
            rawData.fiscal_years.forEach(fy => {{
                const opt = document.createElement('option');
                opt.value = fy;
                opt.textContent = 'ปีงบประมาณ ' + fy;
                fySelect.appendChild(opt);
            }});

            empSelect.innerHTML = '';
            Object.values(rawData.employees).forEach(emp => {{
                const opt = document.createElement('option');
                opt.value = emp.emp_id;
                opt.textContent = `${{emp.emp_name}} (${{emp.emp_id}})`;
                empSelect.appendChild(opt);
            }});

            updateView();
        }}

        function updateView() {{
            const fy = parseInt(document.getElementById('fy-select').value);
            const empId = document.getElementById('emp-select').value;

            const emp = rawData.employees[empId];
            if (!emp) return;

            const fyData = emp.by_fiscal_year[fy] || {{
                brought_forward: 0,
                vacation_total_entitled: 10,
                vacation_used: 0,
                vacation_remaining: 10,
                sick_used_round1: 0,
                sick_remaining_round1: 10,
                sick_used_round2: 0,
                sick_remaining_round2: 10,
                sick_used_total: 0,
                sick_remaining_total: 20,
                history: []
            }};

            // อัปเดต Metric Cards
            document.getElementById('val-bf').textContent = fyData.brought_forward;
            document.getElementById('val-vacation-rem').textContent = fyData.vacation_remaining;
            document.getElementById('val-vacation-used').textContent = fyData.vacation_used;
            document.getElementById('val-vacation-entitled').textContent = fyData.vacation_total_entitled;
            
            // Progress Bar วันลาพักผ่อน (เทียบสิทธิ์ที่ใช้ไปกับสิทธิ์รวม)
            const vacPct = fyData.vacation_total_entitled > 0 ? (fyData.vacation_used / fyData.vacation_total_entitled * 100) : 0;
            document.getElementById('bar-vacation').style.width = Math.min(100, Math.max(0, vacPct)) + '%';

            // Progress Bar วันลาป่วย รอบ 1 & 2
            document.getElementById('val-sick1-rem').textContent = fyData.sick_remaining_round1;
            document.getElementById('val-sick1-used').textContent = fyData.sick_used_round1;
            document.getElementById('bar-sick1').style.width = Math.min(100, Math.max(0, (fyData.sick_used_round1 / 10 * 100))) + '%';

            document.getElementById('val-sick2-rem').textContent = fyData.sick_remaining_round2;
            document.getElementById('val-sick2-used').textContent = fyData.sick_used_round2;
            document.getElementById('bar-sick2').style.width = Math.min(100, Math.max(0, (fyData.sick_used_round2 / 10 * 100))) + '%';

            // รายละเอียด Breakdown
            document.getElementById('detail-vacation-bf').textContent = fyData.brought_forward + ' วัน';
            document.getElementById('detail-vacation-entitled').textContent = fyData.vacation_total_entitled + ' วัน';
            document.getElementById('detail-vacation-used').textContent = fyData.vacation_used + ' วัน';
            document.getElementById('detail-vacation-rem').textContent = fyData.vacation_remaining + ' วัน';

            document.getElementById('detail-sick1-used').textContent = fyData.sick_used_round1;
            document.getElementById('detail-sick1-rem').textContent = fyData.sick_remaining_round1;
            document.getElementById('detail-sick2-used').textContent = fyData.sick_used_round2;
            document.getElementById('detail-sick2-rem').textContent = fyData.sick_remaining_round2;
            document.getElementById('detail-sick-total-used').textContent = fyData.sick_used_total + ' วัน';
            document.getElementById('detail-sick-total-rem').textContent = fyData.sick_remaining_total + ' วัน';

            // รายการประวัติ (กรองรายการที่ไม่ใช่ยอดยกมาเปล่า)
            currentHistory = fyData.history.filter(h => h.days_taken > 0 || (h.note && !h.note.includes('ยกมาจาก')));
            renderTable();
        }}

        function renderTable() {{
            const tbody = document.getElementById('history-tbody');
            const keyword = (document.getElementById('table-search').value || '').toLowerCase().trim();
            tbody.innerHTML = '';

            const filtered = currentHistory.filter(item => {{
                if (!keyword) return true;
                return (item.leave_type && item.leave_type.toLowerCase().includes(keyword)) ||
                       (item.start_date && item.start_date.toLowerCase().includes(keyword)) ||
                       (item.end_date && item.end_date.toLowerCase().includes(keyword)) ||
                       (item.note && item.note.toLowerCase().includes(keyword));
            }});

            document.getElementById('table-count').textContent = filtered.length + ' รายการ';

            if (filtered.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color: var(--text-muted); padding: 28px;">ไม่พบรายการบันทึกการลา</td></tr>';
            }} else {{
                filtered.forEach(item => {{
                    const tr = document.createElement('tr');
                    const isVacation = item.leave_type.includes('พักผ่อน');
                    const tagClass = isVacation ? 'tag-vacation' : 'tag-sick';
                    const icon = isVacation ? '🏖️' : '🩺';

                    tr.innerHTML = `
                        <td><span class="tag ${{tagClass}}">${{icon}} ${{item.leave_type}}</span></td>
                        <td>${{item.start_date || '-'}}</td>
                        <td>${{item.end_date || '-'}}</td>
                        <td style="text-align: center;"><strong>${{item.days_taken}}</strong> วัน</td>
                        <td style="color: var(--text-muted);">${{item.note || '-'}}</td>
                    `;
                    tbody.appendChild(tr);
                }});
            }}
        }}

        window.onload = init;
    </script>
</body>
</html>
"""
    with open(output_html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"[OK] สร้างไฟล์ Dashboard เรียบร้อย: {output_html_path}")

def prompt_exit():
    """รอให้ผู้ใช้กดปิดหน้าต่าง (กรณีเปิดรันผ่านการดับเบิ้ลคลิกบน Windows)"""
    try:
        if sys.stdin.isatty():
            input("\nกดปุ่ม Enter เพื่อปิดหน้าต่างนี้...")
    except Exception:
        pass

def main():
    current_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
    csv_file = os.path.join(current_dir, 'leave_data.csv')
    html_output = os.path.join(current_dir, 'leave_dashboard.html')

    print("=" * 65)
    print("[+] ระบบประมวลผลวันลาและอัปเดต Dashboard อัตโนมัติ")
    print(f"[*] โฟลเดอร์ทำงาน: {current_dir}")
    print(f"[*] กำลังอ่านไฟล์ข้อมูล: {csv_file}")
    print("=" * 65)

    if not os.path.exists(csv_file):
        print("[!] ไม่พบไฟล์ leave_data.csv ในโฟลเดอร์เดียวกันกับสคริปต์")
        print("[i] กรุณาวางไฟล์ leave_data.csv ไว้ในโฟลเดอร์เดียวกับ update_dashboard.py")
        prompt_exit()
        return

    data = process_leave_data(csv_file)
    if not data:
        print("[!] ไม่สามารถประมวลผลข้อมูลได้")
        prompt_exit()
        return

    generate_html_dashboard(data, html_output)

    print(f"[+] กำลังเปิดหน้าเว็บ Dashboard บนเบราว์เซอร์ของคุณ...")
    try:
        webbrowser.open('file://' + os.path.abspath(html_output))
    except Exception as e:
        print(f"[!] ไม่สามารถเปิดเบราว์เซอร์อัตโนมัติได้: {e}")

    print("\n[OK] ดำเนินการเสร็จสมบูรณ์! ข้อมูลถูกอัปเดตและแสดงผลเรียบร้อยแล้ว")
    print("[i] เมื่อมีการอัปเดตไฟล์ CSV ในอนาคต เพียงดับเบิ้ลคลิกไฟล์นี้อีกครั้ง ระบบจะอัปเดตให้อัตโนมัติ")
    print("=" * 65)
    prompt_exit()

if __name__ == '__main__':
    main()
