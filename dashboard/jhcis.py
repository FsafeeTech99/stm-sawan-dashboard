"""Read a facility-scoped clinical view and link evidence without guessing visits.

The view contract is ours, not a claim about the user's JHCIS table schema.
No patient data or database connections are cached across Streamlit sessions.
"""
from __future__ import annotations

from datetime import date, datetime
import re
import unicodedata
import pandas as pd
from dashboard.data import clean_text, normalize_code, money

VIEW_COLUMNS = ['facility', 'visit_id', 'pid', 'patient_name', 'service_date',
                'sex', 'birth_date', 'nationality', 'icd10', 'drugcode']


def identifier(value):
    text = clean_text(value)
    if re.fullmatch(r'\d+\.0', text):
        text = text[:-2]
    text = re.sub(r'[\s-]', '', text)
    # Never reconstruct a truncated citizen ID or match an empty identifier.
    return text if re.fullmatch(r'\d{13}', text) and len(set(text)) > 1 else ''


def service_date(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.date() if isinstance(value, (datetime, pd.Timestamp)) else value
    text = clean_text(value)
    if not text:
        return None
    # Explicit ISO, dd/mm/yyyy, and compact YYYYMMDD only; Buddhist year supported.
    patterns = [(r'^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?$', False),
                (r'^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$', True),
                (r'^(\d{4})(\d{2})(\d{2})$', False)]
    for pattern, day_first in patterns:
        match = re.match(pattern, text)
        if match:
            a, b, c = map(int, match.groups())
            year, month, day = (c, b, a) if day_first else (a, b, c)
            year = year - 543 if year >= 2400 else year
            try:
                return date(year, month, day) if 1900 <= year <= 2200 else None
            except ValueError:
                return None
    return None


def name_key(value):
    text = unicodedata.normalize('NFKC', clean_text(value)).casefold()
    text = re.sub(r'^(นางสาว|นาย|นาง|เด็กหญิง|เด็กชาย|ด\.ญ\.|ด\.ช\.)\s*', '', text)
    return re.sub(r'[\s.,_-]+', '', text)


def tokens(value, icd=False):
    parts = re.split(r'[,;|\s]+', clean_text(value).upper())
    return {part.replace('.', '') if icd else part for part in parts if part}


def prepare_evidence(frame, facility):
    missing = set(VIEW_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError('Clinical view is missing required columns')
    rows = frame.loc[frame.facility.map(normalize_code).eq(facility)].copy().reset_index(drop=True)
    rows['_pid'] = rows.pid.map(identifier)
    rows['_date'] = rows.service_date.map(service_date)
    rows['_name'] = rows.patient_name.map(name_key)
    rows['_visit'] = rows.visit_id.map(clean_text)
    # Missing visit IDs cannot prove that diagnoses and drugs belong to one visit.
    return rows


def assess_visit(rows, female_values, thai_values):
    def consistent(column):
        values = {clean_text(v).upper() for v in rows[column] if clean_text(v)}
        return next(iter(values)) if len(values) == 1 else ''
    sex, nationality = consistent('sex'), consistent('nationality')
    births = {service_date(v) for v in rows.birth_date}
    birth = next(iter(births)) if len(births) == 1 else None
    day = rows['_date'].iloc[0]
    age = day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day)) if birth and day and birth <= day else None
    diagnoses = set().union(*(tokens(v, True) for v in rows.icd10))
    drugs = set().union(*(tokens(v) for v in rows.drugcode))
    checks = {'เพศหญิง': sex in {str(v).upper() for v in female_values} if sex else None,
              'อายุ 13–45 ปี': 13 <= age <= 45 if age is not None else None,
              'ICD-10 Z13.0': 'Z130' in diagnoses if diagnoses else None,
              'drugcode 14001': '14001' in drugs if drugs else None,
              'สัญชาติไทย': nationality in {str(v).upper() for v in thai_values} if nationality and thai_values else None}
    if all(value is True for value in checks.values()):
        status = 'ตรงเงื่อนไขหญิงไทยแก้มแดงที่ผู้ใช้กำหนด'
    elif any(value is False for value in checks.values()):
        status = 'หลักฐานไม่ตรงเงื่อนไขที่ผู้ใช้กำหนด'
    else:
        status = 'ข้อมูลเงื่อนไขยังไม่ครบ'
    readable = ' • '.join(f'{key}: ' + ('ตรง' if value is True else 'ไม่ตรง' if value is False else 'ไม่มี/ขัดกัน') for key, value in checks.items())
    return status, readable, age


def match_claims(claims, evidence, facility, female_values=('2', 'F', 'FEMALE', 'หญิง'),
                 thai_values=('ไทย', 'TH', 'THAI')):
    """Exact PID + date + facility => one visit only; names never confirm identity."""
    clinical = prepare_evidence(evidence, facility)
    pid_lookup, name_lookup = {}, {}
    for idx, row in clinical.iterrows():
        if row['_date']:
            if row['_pid']:
                pid_lookup.setdefault((row['_pid'], row['_date']), []).append(idx)
            if row['_name']:
                name_lookup.setdefault((row['_name'], row['_date']), []).append(idx)
    results = []
    for _, claim in claims.iterrows():
        status, rule, explanation, visit, age, source = 'ยังจับคู่ไม่ได้', 'ยังไม่มีหลักฐานบริการ', '', '', None, ''
        pid, day = identifier(claim.get('PID')), service_date(claim.get('วันเข้ารักษา'))
        candidates = []
        if normalize_code(claim.get('_facility')) != facility:
            status = 'นอกหน่วยบริการบัญชี'
        elif day is None:
            status = 'วันที่รับบริการขาด/อ่านไม่ได้'
        else:
            candidates = pid_lookup.get((pid, day), []) if pid else []
            if candidates:
                selected = clinical.loc[candidates]
                source = ' / '.join(sorted(set(selected['_evidence_source'].dropna().map(clean_text)))) if '_evidence_source' in selected else 'ฐาน JHCIS'
                visits = set(selected['_visit'])
                if '' in visits or len(visits) != 1:
                    status = 'หลายครั้งรับบริการ/visit ไม่ครบ • รอตรวจสอบ'
                else:
                    status, visit = 'จับคู่เลขบัตร + วันรับบริการ + หน่วยบริการ', next(iter(visits))
                    rule, explanation, age = assess_visit(selected, female_values, thai_values)
                    if money(claim.get('PP')) not in (8000, -8000):
                        rule += ' • ยอด PP ไม่ใช่ 80 บาท'
                    elif money(claim.get('PP')) == -8000:
                        explanation += ' • PP -80 เป็นรายการปรับลดตามไฟล์'
            else:
                by_name = name_lookup.get((name_key(claim.get('ชื่อ-นามสกุล')), day), [])
                if by_name:
                    status = 'ชื่อ + วันตรง • ต้องยืนยันเลขบัตรก่อน'
                    explanation = f'พบ {clinical.loc[by_name, "_visit"].nunique()} visit ที่อาจตรง ไม่ยืนยันบริการอัตโนมัติ'
                elif not pid:
                    status = 'เลขบัตรขาด/รูปแบบไม่ครบ'
        results.append([status, visit, age, rule, explanation, source])
    return pd.DataFrame(results, index=claims.index, columns=['การจับคู่ JHCIS', 'JHCIS visit', 'อายุวันรับบริการ', 'ผลตรวจเงื่อนไข JHCIS', 'หลักฐาน/ข้อสังเกต JHCIS', 'แหล่งข้อมูลบริการ'])


def read_view(config, facility, start, end):
    """Static SELECT with bound values; DB user must also have SELECT-only grants."""
    import pymysql
    view = str(config.get('view', ''))
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', view):
        raise ValueError('Invalid configured clinical view')
    if not isinstance(start, date) or not isinstance(end, date) or start > end or (end - start).days > 366:
        raise ValueError('Choose a date range up to 366 days')
    cap = min(max(int(config.get('max_rows', 50000)), 1), 100000)
    tls = bool(config.get('tls', True))
    connection = pymysql.connect(host=config['host'], port=int(config.get('port', 3306)),
        user=config['user'], password=config['password'], database=config['database'],
        charset='utf8mb4', connect_timeout=8, read_timeout=20, write_timeout=10,
        autocommit=False, local_infile=False,
        ssl_verify_cert=tls, ssl_verify_identity=tls,
        ssl_ca=config.get('ssl_ca') if tls else None, ssl_disabled=not tls,
        cursorclass=pymysql.cursors.DictCursor)
    try:
        with connection.cursor() as cursor:
            cursor.execute('START TRANSACTION READ ONLY')
            cursor.execute('SELECT ' + ', '.join('`' + col + '`' for col in VIEW_COLUMNS) +
                f' FROM `{view}` WHERE `facility` = %s AND `service_date` >= %s AND `service_date` < DATE_ADD(%s, INTERVAL 1 DAY) LIMIT %s',
                (facility, start.isoformat(), end.isoformat(), cap + 1))
            records = cursor.fetchall()
        if len(records) > cap:
            raise ValueError('Clinical result exceeds limit; narrow date range')
        frame = pd.DataFrame(records, columns=VIEW_COLUMNS)
        return prepare_evidence(frame, facility)[VIEW_COLUMNS].reset_index(drop=True)
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()
