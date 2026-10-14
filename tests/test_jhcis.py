from datetime import date
from unittest import TestCase
from unittest.mock import MagicMock, patch
from pathlib import Path
from io import BytesIO
from types import SimpleNamespace
import time
import pandas as pd
from streamlit.testing.v1 import AppTest
from dashboard.auth import hash_password
from dashboard import jhcis as jc


def evidence(**changes):
    row = dict(facility='05542', visit_id='V1', pid='1234567890123',
               patient_name='นางสาว สมมติ ทดสอบ', service_date='2026-10-14',
               sex='2', birth_date='2000-10-14', nationality='ไทย',
               icd10='Z13.0', drugcode='14001')
    row.update(changes)
    return row


def claim(**changes):
    row = {'_facility': '05542', 'PID': '1234567890123', 'วันเข้ารักษา': '14/10/2569',
           'ชื่อ-นามสกุล': 'สมมติ ทดสอบ', 'PP': 80, 'HN': 'different-from-JHCIS'}
    row.update(changes)
    return row


class JhcIsTests(TestCase):
    def match(self, claims=None, clinical=None):
        return jc.match_claims(pd.DataFrame(claims or [claim()]),
                              pd.DataFrame(clinical or [evidence()]), '05542')

    def test_pid_date_and_complete_rule_not_hn_or_name(self):
        result = self.match([claim(**{'ชื่อ-นามสกุล': 'ชื่อใน STM ต่างกัน'})])
        self.assertIn('จับคู่เลขบัตร', result.iloc[0, 0])
        self.assertIn('ตรงเงื่อนไขหญิงไทย', result.iloc[0, 3])
        self.assertEqual(result.iloc[0, 2], 26)
        self.assertNotIn('PID', result.columns)
        wrong_day = self.match([claim(**{'วันเข้ารักษา': '2026-10-15'})])
        self.assertEqual(wrong_day.iloc[0, 0], 'ยังจับคู่ไม่ได้')

    def test_names_never_confirm_and_same_day_multiple_visits_abstain(self):
        by_name = self.match([claim(PID='2234567890123')])
        self.assertIn('ต้องยืนยันเลขบัตร', by_name.iloc[0, 0])
        self.assertEqual(by_name.iloc[0, 3], 'ยังไม่มีหลักฐานบริการ')
        multiple = self.match(clinical=[evidence(visit_id='A', drugcode=''), evidence(visit_id='B', icd10='')])
        self.assertIn('หลายครั้งรับบริการ', multiple.iloc[0, 0])
        self.assertEqual(multiple.iloc[0, 3], 'ยังไม่มีหลักฐานบริการ')
        no_visit = self.match(clinical=[evidence(visit_id='')])
        self.assertIn('visit ไม่ครบ', no_visit.iloc[0, 0])

    def test_age_birthdays_same_visit_codes_and_missing_nationality(self):
        for birth, matches in [('2013-10-14', True), ('2013-10-15', False),
                               ('1980-10-15', True), ('1980-10-14', False)]:
            r = self.match(clinical=[evidence(birth_date=birth)])
            self.assertEqual(r.iloc[0, 3].startswith('ตรงเงื่อนไขหญิงไทย'), matches)
        split = self.match(clinical=[evidence(icd10='Z130;Z30.0', drugcode=''), evidence(icd10='', drugcode='14001|999')])
        self.assertIn('ตรงเงื่อนไขหญิงไทย', split.iloc[0, 3])
        missing = self.match(clinical=[evidence(nationality='')])
        self.assertEqual(missing.iloc[0, 3], 'ข้อมูลเงื่อนไขยังไม่ครบ')
        self.assertIn('ไม่ตรงเงื่อนไข', self.match(clinical=[evidence(drugcode='140010')]).iloc[0, 3])
        self.assertIn('ไม่ตรงเงื่อนไข', self.match(clinical=[evidence(sex='1')]).iloc[0, 3])

    def test_tenant_amount_adjustment_and_no_source_mutation(self):
        self.assertEqual(self.match(clinical=[evidence(facility='05555')]).iloc[0, 0], 'ยังจับคู่ไม่ได้')
        self.assertEqual(self.match([claim(_facility='05555')]).iloc[0, 0], 'นอกหน่วยบริการบัญชี')
        self.assertIn('ยอด PP ไม่ใช่ 80', self.match([claim(PP=160)]).iloc[0, 3])
        self.assertIn('ปรับลด', self.match([claim(PP=-80)]).iloc[0, 4])
        a, b = pd.DataFrame([claim()]), pd.DataFrame([evidence()])
        aa, bb = a.copy(deep=True), b.copy(deep=True)
        jc.match_claims(a, b, '05542')
        pd.testing.assert_frame_equal(a, aa)
        pd.testing.assert_frame_equal(b, bb)
        self.assertEqual(jc.identifier('12345'), '')
        self.assertEqual(jc.service_date('25691014'), date(2026, 10, 14))
        self.assertIsNone(jc.service_date('31/02/2569'))
        self.assertIsNone(jc.service_date(pd.NaT))

    def test_reader_static_select_limits_parameters_and_closes(self):
        config = dict(host='fake', user='test', password='private', database='fake', view='clinical_view', max_rows=1)
        connection, cursor = MagicMock(), MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchall.return_value = [evidence()]
        with patch('pymysql.connect', return_value=connection) as connect:
            frame = jc.read_view(config, '05542', date(2026, 10, 1), date(2026, 10, 31))
            self.assertEqual(len(frame), 1)
            self.assertEqual(cursor.execute.call_args_list[0].args[0], 'START TRANSACTION READ ONLY')
            query, params = cursor.execute.call_args_list[1].args
            self.assertIn('WHERE `facility` = %s', query)
            self.assertEqual(params, ('05542', '2026-10-01', '2026-10-31', 2))
            self.assertTrue(connect.call_args.kwargs['ssl_verify_identity'])
            self.assertFalse(connect.call_args.kwargs['local_infile'])
            connection.rollback.assert_called_once()
            connection.close.assert_called_once()
            cursor.fetchall.return_value = [evidence(), evidence()]
            with self.assertRaises(ValueError):
                jc.read_view(config, '05542', date(2026, 10, 1), date(2026, 10, 31))
            with self.assertRaises(ValueError):
                jc.read_view({**config, 'view': 'view; DROP TABLE x'}, '05542', date(2026, 10, 1), date(2026, 10, 31))
            with self.assertRaises(ValueError):
                jc.read_view(config, '05542', date(2020, 1, 1), date(2026, 10, 31))

    def test_app_gates_default_password_and_reads_only_on_request(self):
        app_path = str(Path(__file__).resolve().parents[1] / 'app.py')
        app = AppTest.from_file(app_path, default_timeout=45)
        app.secrets['jhcis'] = {'05542': {'enabled': True}}
        app.session_state['user'] = 'Admin05542'
        app.session_state['clinical_input_mode'] = 'เชื่อมฐาน JHCIS'
        app.session_state['last_activity'] = time.time()
        with patch('dashboard.jhcis.read_view') as reader:
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any('เปลี่ยนรหัสผ่าน' in warning.value for warning in app.warning))
            reader.assert_not_called()
        app.secrets['auth'] = {'users': {'Admin05542': {'password_hash': hash_password('test-private-password')}}}
        out = BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            pd.DataFrame([{'HSUB': '05542', 'REP': 'TEST', 'TRAN_ID': 'DEMO',
                'PID': '1234567890123', 'วันเข้ารักษา': '2026-10-14', 'PP': 80,
                'PROJCODE': 'WALKIN', 'ยอดชดเชยทั้งสิ้น': 80}]).to_excel(writer, index=False)
        upload = SimpleNamespace(name='synthetic.xlsx', getvalue=lambda: out.getvalue())
        with patch('streamlit.file_uploader', side_effect=lambda label, **kwargs: [upload] if label.startswith('1.') else []), \
             patch('dashboard.jhcis.read_view', return_value=pd.DataFrame([evidence()])) as reader:
            app.run()
            self.assertFalse(app.exception)
            reader.assert_not_called()
            app.button(key='jhcis_read').click().run()
            self.assertFalse(app.exception)
            reader.assert_called_once()
            clinical_tables = [element.value for element in app.dataframe if 'ผลตรวจเงื่อนไข ข้อมูลบริการ' in element.value]
            self.assertTrue(clinical_tables)
            self.assertTrue(any(table['ผลตรวจเงื่อนไข ข้อมูลบริการ'].str.contains('ตรงเงื่อนไขหญิงไทย').any() for table in clinical_tables))
            app.button(key='jhcis_clear').click().run()
            self.assertFalse(app.exception)
            self.assertNotIn('clinical_records', app.session_state)
