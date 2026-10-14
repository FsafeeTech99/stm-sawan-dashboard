"""Session-local clinical evidence supplied by the user, not fetched from JHCIS."""
from io import BytesIO
import hashlib
import json
import pandas as pd
from dashboard.data import clean_text, normalize_code, excel_bytes
from dashboard.jhcis import VIEW_COLUMNS, identifier, service_date

LABELS = dict(zip(VIEW_COLUMNS, ['รหัสหน่วยบริการ', 'เลขครั้งรับบริการ', 'เลขบัตรประชาชน',
    'ชื่อ-นามสกุล', 'วันที่รับบริการ', 'เพศ', 'วันเกิด', 'สัญชาติ', 'ICD10', 'drugcode']))
ALIASES = {
    'facility': ['รหัสหน่วยบริการ', 'HSUB', 'HCODE', 'pcucode'],
    'visit_id': ['เลขครั้งรับบริการ', 'visitno', 'visit', 'เลข visit'],
    'pid': ['เลขบัตรประชาชน', 'เลขบัตร', 'PID', 'CID', 'idcard'],
    'patient_name': ['ชื่อ-นามสกุล', 'ชื่อสกุล', 'ชื่อผู้ป่วย'],
    'service_date': ['วันที่รับบริการ', 'วันเข้ารักษา', 'visitdate', 'วันที่บริการ'],
    'sex': ['เพศ', 'gender'], 'birth_date': ['วันเกิด', 'birth', 'dob', 'birthdate'],
    'nationality': ['สัญชาติ', 'nation'], 'icd10': ['ICD10', 'ICD-10', 'diagcode', 'diagnosis'],
    'drugcode': ['drugcode', 'รหัสยา', 'รหัสจ่ายยา'],
}


def key(value):
    return clean_text(value).casefold().replace(' ', '').replace('_', '').replace('-', '')


def column_map(columns):
    lookup = {key(alias): field for field, names in ALIASES.items() for alias in [field, *names]}
    result = {}
    for column in columns:
        field = lookup.get(key(column))
        if field and field not in result.values():
            result[column] = field
    return result


def read_file(filename, content):
    if len(content) > 25 * 1024 * 1024:
        raise ValueError('ไฟล์ข้อมูลบริการต้องไม่เกิน 25 MB')
    if filename.lower().endswith('.csv'):
        for encoding in ('utf-8-sig', 'cp874'):
            try:
                text = content.decode(encoding)
                return [('CSV', pd.read_csv(BytesIO(text.encode('utf-8')), dtype=str, keep_default_na=False))]
            except UnicodeDecodeError:
                continue
        raise ValueError('อ่านรหัสอักษร CSV ไม่ได้ ใช้ CSV UTF-8 หรือ Excel ตามแม่แบบ')
    engine = 'openpyxl' if content.startswith(b'PK') else 'xlrd' if content.startswith(bytes.fromhex('D0CF11E0A1B11AE1')) else None
    if engine is None:
        raise ValueError('ไฟล์นี้ไม่ใช่ Excel .xls/.xlsx ที่รองรับ')
    result = []
    with pd.ExcelFile(BytesIO(content), engine=engine) as book:
        for sheet in book.sheet_names:
            preview = book.parse(sheet, header=None, nrows=40, dtype=object)
            candidates = []
            for index, row in preview.iterrows():
                fields = set(column_map(row.tolist()).values())
                if 'service_date' in fields and ('pid' in fields or 'patient_name' in fields) and len(fields) >= 3:
                    candidates.append((len(fields), int(index)))
            if candidates:
                header = sorted(candidates, key=lambda item: (-item[0], item[1]))[0][1]
                result.append((sheet, book.parse(sheet, header=header, dtype=object)))
    if not result:
        raise ValueError('ไม่พบหัวตารางข้อมูลบริการ กรุณาใช้แม่แบบหรือคอลัมน์เลขบัตร/ชื่อ และวันที่รับบริการ')
    return result


def normalize(frame, scope, source, declare_scope=False, token=''):
    rename = column_map(frame.columns)
    if 'service_date' not in rename.values() or not {'pid', 'patient_name'} & set(rename.values()):
        raise ValueError('ต้องมีวันที่รับบริการ และเลขบัตรประชาชนหรือชื่อ-นามสกุล')
    if 'facility' not in rename.values() and not declare_scope:
        raise ValueError('ไฟล์ไม่มีรหัสหน่วยบริการ กรุณายืนยันว่าเป็นข้อมูลของหน่วยบัญชีนี้ก่อนนำเข้า')
    source_columns = {field: column for column, field in rename.items()}
    canonical = pd.DataFrame(index=frame.index)
    for field in VIEW_COLUMNS:
        canonical[field] = frame[source_columns[field]] if field in source_columns else ''
    records, notices = [], []
    for ordinal, (_, row) in enumerate(canonical.iterrows(), start=2):
        record = {field: clean_text(row[field]) for field in VIEW_COLUMNS}
        if not any(record[field] for field in VIEW_COLUMNS if field != 'facility'):
            continue
        facility = normalize_code(row.facility) if record['facility'] else scope if declare_scope else ''
        if facility != scope:
            notices.append(f'แถว {ordinal}: ข้ามรหัสหน่วยบริการอื่น/ไม่มีรหัส')
            continue
        day = service_date(row.service_date)
        pid = identifier(row.pid)
        if day is None or (record['pid'] and not pid) or (not pid and not record['patient_name']):
            notices.append(f'แถว {ordinal}: วันที่หรือเลขบัตรไม่ครบ/อ่านไม่ได้ จึงยังไม่นำเข้า')
            continue
        birth = service_date(row.birth_date)
        if record['birth_date'] and birth is None:
            notices.append(f'แถว {ordinal}: วันเกิดอ่านไม่ได้ จะตรวจอายุไม่ได้')
        record.update(facility=scope, pid=pid, service_date=day, birth_date=birth)
        if not record['visit_id']:
            # User declares one row as one visit; keep separate rows separate.
            record['visit_id'] = 'INPUT-' + hashlib.sha256(f'{token}:{ordinal}'.encode()).hexdigest()[:12]
        record['_evidence_source'] = source
        records.append(record)
    return pd.DataFrame(records, columns=VIEW_COLUMNS + ['_evidence_source']), notices


def manual_record(values, scope):
    fingerprint = hashlib.sha256(json.dumps(values, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()
    return normalize(pd.DataFrame([values]), scope, 'ผู้ใช้กรอกเอง', True, fingerprint)


def merge(existing, incoming):
    combined = pd.concat([existing, incoming], ignore_index=True)
    if len(combined) > 100000:
        raise ValueError('ข้อมูลบริการเกิน 100,000 แถว กรุณานำเข้าเป็นช่วงวันที่')
    return combined.drop_duplicates(VIEW_COLUMNS).reset_index(drop=True)


def template_bytes(scope):
    frame = pd.DataFrame([{field: scope if field == 'facility' else '' for field in VIEW_COLUMNS}]).rename(columns=LABELS)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        frame.to_excel(writer, sheet_name='ข้อมูลบริการ', index=False)
        sheet = writer.sheets['ข้อมูลบริการ']
        sheet.freeze_panes = 'A2'
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = 22
            for cell in column:
                cell.number_format = '@'
    return output.getvalue()


def export_bytes(frame):
    exported = frame.reindex(columns=VIEW_COLUMNS).copy()
    for column in ('service_date', 'birth_date'):
        exported[column] = exported[column].map(lambda value: service_date(value).isoformat() if service_date(value) else '')
    for column in exported:
        exported[column] = exported[column].map(clean_text)
    return excel_bytes({'ข้อมูลบริการ': exported.rename(columns=LABELS)})
