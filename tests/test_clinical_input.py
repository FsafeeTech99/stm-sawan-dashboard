from datetime import date
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import time
from unittest import TestCase
from unittest.mock import patch
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest
from dashboard import clinical_input as ci, local_jhcis as lj
from dashboard.jhcis import match_claims


def person():
    return dict(pid='1234567890123', patient_name='สมมติ ทดสอบ', service_date=date(2026, 10, 14),
                birth_date=date(2000, 1, 1), sex='หญิง', nationality='ไทย', icd10='Z13.0', drugcode='14001', visit_id='')


def claim():
    return pd.DataFrame([{'_facility': '05542', 'PID': '1234567890123', 'วันเข้ารักษา': '2026-10-14', 'PP': 80}])


class InputTests(TestCase):
    def test_manual_provenance_dedup_and_name_only_abstention(self):
        records, notices = ci.manual_record(person(), '05542')
        self.assertFalse(notices)
        self.assertEqual(len(ci.merge(records, records)), 1)
        result = match_claims(claim(), records, '05542')
        self.assertIn('ตรงเงื่อนไขหญิงไทย', result.iloc[0, 3])
        self.assertEqual(result['แหล่งข้อมูลบริการ'].iloc[0], 'ผู้ใช้กรอกเอง')
        _, reloaded = ci.read_file('roundtrip.xlsx', ci.export_bytes(records))[0]
        roundtrip, _ = ci.normalize(reloaded, '05542', 'ไฟล์จำลอง')
        self.assertEqual(roundtrip.pid.iloc[0], '1234567890123')
        self.assertEqual(roundtrip.birth_date.iloc[0], date(2000, 1, 1))
        names, _ = ci.manual_record({**person(), 'pid': ''}, '05542')
        named_claim = claim().assign(**{'ชื่อ-นามสกุล': 'สมมติ ทดสอบ'})
        self.assertIn('ต้องยืนยันเลขบัตร', match_claims(named_claim, names, '05542').iloc[0, 0])

    def test_upload_scope_invalid_identifiers_and_separate_visits(self):
        raw = pd.DataFrame([person(), {**person(), 'pid': '123'}, {**person(), 'facility': '05555'}])
        records, notices = ci.normalize(raw, '05542', 'ไฟล์จำลอง', True, 'test')
        self.assertEqual(len(records), 1)
        self.assertEqual(len(notices), 2)
        with self.assertRaises(ValueError):
            ci.normalize(pd.DataFrame([person()]), '05542', 'ไฟล์จำลอง')
        split = pd.DataFrame([{**person(), 'icd10': '', 'drugcode': '14001'}, {**person(), 'icd10': 'Z13.0', 'drugcode': ''}])
        records, _ = ci.normalize(split, '05542', 'ไฟล์จำลอง', True, 'test')
        self.assertIn('หลายครั้งรับบริการ', match_claims(claim(), records, '05542').iloc[0, 0])
        records, _ = ci.normalize(split.assign(visit_id='V1'), '05542', 'ไฟล์จำลอง', True, 'test')
        self.assertIn('ตรงเงื่อนไขหญิงไทย', match_claims(claim(), records, '05542').iloc[0, 3])

    def test_excel_headers_csv_and_blank_template(self):
        rows = pd.DataFrame([{**person(), 'facility': '05542'}]).rename(columns=ci.LABELS)
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            pd.DataFrame([['รายงานข้อมูลบริการ']]).to_excel(writer, index=False, header=False)
            rows.to_excel(writer, startrow=7, index=False)
        _, raw = ci.read_file('synthetic.xlsx', buffer.getvalue())[0]
        normalized, _ = ci.normalize(raw, '05542', 'ไฟล์จำลอง')
        self.assertEqual(normalized.pid.iloc[0], '1234567890123')
        csv = rows.to_csv(index=False).encode('utf-8-sig')
        _, raw = ci.read_file('synthetic.csv', csv)[0]
        self.assertEqual(len(ci.normalize(raw, '05542', 'ไฟล์จำลอง')[0]), 1)
        _, raw = ci.read_file('template.xlsx', ci.template_bytes('05542'))[0]
        self.assertTrue(ci.normalize(raw, '05542', 'แม่แบบ')[0].empty)

    def test_app_manual_row_updates_detail_and_can_be_cleared(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=45)
        app.session_state['user'] = 'Admin05542'
        app.session_state['last_activity'] = time.time()
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            claim().rename(columns={'_facility': 'HSUB'}).assign(REP='TEST', **{'ยอดชดเชยทั้งสิ้น': 80}).to_excel(writer, index=False)
        upload = SimpleNamespace(name='synthetic.xlsx', getvalue=lambda: output.getvalue())
        with patch('streamlit.file_uploader', side_effect=lambda label, **kwargs: [upload] if label.startswith('1.') else []), \
             patch('dashboard.jhcis.match_claims', side_effect=lambda *args: match_claims(*args).drop(columns='แหล่งข้อมูลบริการ')):
            app.run()
            self.assertFalse(app.exception)
            app.text_input(key='evidence_pid').set_value('1234567890123')
            app.date_input(key='evidence_day').set_value(date(2026, 10, 14))
            app.date_input(key='evidence_birth').set_value(date(2000, 1, 1))
            app.selectbox(key='evidence_sex').set_value('หญิง')
            app.selectbox(key='evidence_nation').set_value('ไทย')
            app.text_input(key='evidence_icd').set_value('Z13.0')
            app.text_input(key='evidence_drug').set_value('14001')
            next(button for button in app.button if button.label == 'เพิ่มข้อมูลรายนี้').click().run()
            self.assertFalse(app.exception)
            tables = [element.value for element in app.dataframe if 'แหล่งข้อมูลบริการ' in element.value]
            self.assertTrue(any(table['แหล่งข้อมูลบริการ'].eq('ผู้ใช้กรอกเอง').any() for table in tables))
            self.assertTrue(any(table['ผลตรวจเงื่อนไข ข้อมูลบริการ'].str.contains('ตรงเงื่อนไขหญิงไทย').any() for table in tables if 'ผลตรวจเงื่อนไข ข้อมูลบริการ' in table))
            app.button(key='entered_clinical_clear').click().run()
            self.assertFalse(app.exception)
            self.assertNotIn('entered_clinical', app.session_state)

    def test_old_cached_database_module_cannot_crash_error_handler(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=45)
        app.session_state['user'] = 'Admin05542'
        app.session_state['last_activity'] = time.time()
        app.session_state['clinical_input_mode'] = 'เชื่อมฐาน JHCIS'
        original_option = st.get_option
        with patch.dict('os.environ', {'KHAMTECH_LOCAL': '1'}), \
             patch('streamlit.get_option', side_effect=lambda name: '127.0.0.1' if name == 'server.address' else original_option(name)), \
             patch.object(lj, 'read_standard', side_effect=ValueError('PRIVATE_DETAILS')), \
             patch.object(lj, 'ConnectionSettingsError', None), patch.object(lj, 'user_error_message', None):
            app.run()
            app.text_input(key='local_db_password').set_value('test-only')
            next(button for button in app.button if button.label == 'เชื่อมและอ่าน JHCIS แบบ read-only').click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any('เชื่อมฐานไม่ได้' in element.value for element in app.error))
            self.assertFalse(any('PRIVATE_DETAILS' in element.value for element in app.error))
