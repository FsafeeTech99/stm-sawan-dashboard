from datetime import date
from io import BytesIO
import os
from pathlib import Path
from types import SimpleNamespace
import time
from unittest import TestCase
from unittest.mock import MagicMock, patch
import pandas as pd
import pymysql
import streamlit as st
from streamlit.testing.v1 import AppTest
from dashboard import local_jhcis as lj
from dashboard.jhcis import match_claims


def metadata():
    fields = {'person': ['pcucodeperson', 'pid', 'idcard', 'fname', 'lname', 'sex', 'birth', 'nation'],
              'visit': ['pcucode', 'pcucodeperson', 'pid', 'visitno', 'visitdate'],
              'visitdiag': ['pcucode', 'visitno', 'diagcode'],
              'visitdrug': ['pcucode', 'visitno', 'drugcode']}
    return [{'TABLE_NAME': table, 'COLUMN_NAME': field} for table, columns in fields.items() for field in columns]


def visits():
    return [dict(facility='05542', visit_id='V1', pid='1234567890123', patient_name='สมมติ ทดสอบ',
                 service_date='2026-10-14', sex='2', birth_date='2000-10-14', nationality='099')]


class LocalTests(TestCase):
    def test_connection_errors_are_specific_and_never_echo_secret_details(self):
        secret = 'DO_NOT_PRINT_PRIVATE_PASSWORD_OR_SQL'
        self.assertIn('ไม่เปิด TLS', lj.user_error_message(lj.TLSUnavailable(2026, secret)))
        for code, expected in [(1045, 'ฐานปฏิเสธบัญชี'), (1049, 'ไม่พบชื่อฐาน'),
                               (1142, 'ไม่มีสิทธิ SELECT'), (2003, 'ติดต่อ MySQL ไม่ได้')]:
            message = lj.user_error_message(pymysql.err.OperationalError(code, secret))
            self.assertIn(expected, message)
            self.assertNotIn(secret, message)
        self.assertNotIn(secret, lj.user_error_message(RuntimeError(secret)))
        with self.assertRaises(lj.ConnectionSettingsError) as failed:
            lj.connect_database(dict(host='8.8.8.8', port=3306, transport='local'))
        self.assertIn('Internet', lj.user_error_message(failed.exception))
        self.assertNotIn('366', lj.user_error_message(failed.exception))

    def test_adapter_detects_schema_and_preserves_visit_keys(self):
        connection, cursor = MagicMock(), MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchall.side_effect = [metadata(), visits(),
            [{'facility': '05542', 'visit_id': 'V1', 'code': 'Z13.0'}, {'facility': '05542', 'visit_id': 'V2', 'code': 'Z12.1'}],
            [{'facility': '05542', 'visit_id': 'V1', 'code': '14001'}, {'facility': '05542', 'visit_id': 'V2', 'code': '999'}]]
        with patch('dashboard.local_jhcis.connect_database', return_value=connection):
            data = lj.read_standard({'database': 'local_db'}, '05542', date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(data.icd10.tolist(), ['Z13.0'])
        self.assertEqual(data.drugcode.tolist(), ['14001'])
        calls = cursor.execute.call_args_list
        self.assertEqual(calls[0].args[0], 'START TRANSACTION READ ONLY')
        self.assertTrue(all(call.args[0].startswith('SELECT ') for call in calls[1:]))
        self.assertIn('v.`pcucodeperson` = p.`pcucodeperson`', calls[2].args[0])
        self.assertIn('v.`pid` = p.`pid`', calls[2].args[0])
        for call in calls[3:]:
            self.assertIn('v.`pcucode` = d.`pcucode`', call.args[0])
            self.assertIn('v.`visitno` = d.`visitno`', call.args[0])
            self.assertEqual(call.args[1][:3], ('05542', '2026-10-01', '2026-10-31'))
        claim = pd.DataFrame([{'_facility': '05542', 'PID': '1234567890123', 'วันเข้ารักษา': '2026-10-14', 'PP': 80}])
        missing_nation_map = match_claims(claim, data, '05542', thai_values=[])
        self.assertEqual(missing_nation_map.iloc[0, 3], 'ข้อมูลเงื่อนไขยังไม่ครบ')
        confirmed_map = match_claims(claim, data, '05542', thai_values=['099'])
        self.assertIn('ตรงเงื่อนไขหญิงไทย', confirmed_map.iloc[0, 3])
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()

    def test_mismatched_schema_and_duplicate_visits_reject_entire_result(self):
        connection, cursor = MagicMock(), MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        with patch('dashboard.local_jhcis.connect_database', return_value=connection):
            cursor.fetchall.side_effect = [metadata()[:-1]]
            with self.assertRaises(lj.SchemaMismatch):
                lj.read_standard({'database': 'local_db'}, '05542', date(2026, 10, 1), date(2026, 10, 31))
            cursor.fetchall.side_effect = [metadata(), visits() * 2]
            with self.assertRaises(lj.SchemaMismatch):
                lj.read_standard({'database': 'local_db'}, '05542', date(2026, 10, 1), date(2026, 10, 31))
            cursor.fetchall.side_effect = [metadata(), visits() * 2]
            with self.assertRaises(ValueError):
                lj.read_standard({'database': 'local_db'}, '05542', date(2026, 10, 1), date(2026, 10, 31), max_rows=1)
        self.assertEqual(connection.close.call_count, 3)

    def test_public_plaintext_blocked_and_tls_never_downgrades(self):
        config = dict(host='8.8.8.8', port=3306, user='synthetic', password='test-only', database='local_db', transport='local')
        with patch('dashboard.local_jhcis.RequiredTLSConnection') as connection:
            with self.assertRaises(ValueError):
                lj.connect_database(config)
            with self.assertRaises(ValueError):
                lj.connect_database({**config, 'transport': 'ssh'})
            connection.assert_not_called()
            lj.connect_database({**config, 'host': '127.0.0.1', 'transport': 'ssh'})
            self.assertTrue(connection.call_args.kwargs['ssl_disabled'])
            lj.connect_database({**config, 'transport': 'tls'})
            self.assertTrue(connection.call_args.kwargs['ssl_verify_identity'])
        bare = lj.RequiredTLSConnection.__new__(lj.RequiredTLSConnection)
        bare.ssl = True
        bare.server_capabilities = 0
        with self.assertRaises(pymysql.err.OperationalError):
            bare._request_authentication()

    def test_local_form_hidden_on_cloud_and_reads_only_when_submitted(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=45)
        app.session_state['user'] = 'Admin05542'
        app.session_state['clinical_input_mode'] = 'เชื่อมฐาน JHCIS'
        app.session_state['last_activity'] = time.time()
        with patch.dict(os.environ, {'KHAMTECH_LOCAL': ''}):
            app.run()
            self.assertFalse(app.exception)
            self.assertFalse(any(element.key == 'local_db_password' for element in app.text_input))
        original_option = st.get_option
        def local_option(name):
            return '127.0.0.1' if name == 'server.address' else original_option(name)
        data = pd.DataFrame(visits()).assign(icd10='Z13.0', drugcode='14001')
        with patch.dict(os.environ, {'KHAMTECH_LOCAL': '1'}), patch('streamlit.get_option', side_effect=local_option), \
             patch('dashboard.local_jhcis.read_standard', return_value=data) as reader:
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.text_input(key='local_db_name').value, 'jhcisdb05542')
            reader.assert_not_called()
            app.text_input(key='local_db_password').set_value('synthetic-test-password')
            next(button for button in app.button if button.label == 'เชื่อมและอ่าน JHCIS แบบ read-only').click().run()
            self.assertFalse(app.exception)
            reader.assert_called_once()
            self.assertEqual(reader.call_args.args[1], '05542')
            self.assertEqual(app.session_state['clinical_records'][0], '05542')
            app.button(key='local_db_clear').click().run()
            self.assertFalse(app.exception)
            self.assertNotIn('clinical_records', app.session_state)
            self.assertEqual(app.text_input(key='local_db_password').value, '')
