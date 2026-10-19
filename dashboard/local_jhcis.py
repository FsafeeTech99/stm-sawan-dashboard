"""Local-only JHCIS adapter. Validate actual metadata before building SELECTs."""
from datetime import date
import ipaddress
import re
import socket
import pandas as pd
import pymysql
from pymysql.constants import CLIENT
from dashboard.jhcis import VIEW_COLUMNS, prepare_evidence


class SchemaMismatch(ValueError):
    pass


class ConnectionSettingsError(ValueError):
    """Fixed user-facing messages; never contains credentials or SQL."""


class TLSUnavailable(pymysql.err.OperationalError):
    pass


def user_error_message(error):
    if isinstance(error, ConnectionSettingsError):
        return str(error)
    if isinstance(error, TLSUnavailable):
        return 'เซิร์ฟเวอร์ไม่เปิด TLS จึงใช้ Internet พร้อม TLS ไม่ได้ กรุณาเปิด SSH tunnel แล้วเลือกโหมด SSH หรือใช้ IP ภายในผ่าน LAN/VPN'
    code = error.args[0] if error.args and isinstance(error.args[0], int) else None
    messages = {
        1045: 'ฐานปฏิเสธบัญชี (1045): ตรวจ username/password และสิทธิให้บัญชีนี้เชื่อมจากเครื่องคุณ',
        1049: 'ไม่พบชื่อฐาน (1049): ตรวจชื่อ database ที่โปรแกรม JHCIS ใช้จริง',
        1142: 'บัญชีฐานไม่มีสิทธิ SELECT ที่จำเป็น (1142): ให้ผู้ดูแลตรวจสิทธิอ่านตาราง JHCIS',
        2003: 'ติดต่อ MySQL ไม่ได้ (2003): ตรวจ IP ของเครื่องฐานและพอร์ต ถ้าใช้ SSH ให้เปิด tunnel ไว้ก่อน',
        2013: 'การเชื่อม MySQL ขาดระหว่างอ่าน (2013): ตรวจเส้นทางเชื่อมและลองลดช่วงวันที่',
        2026: 'TLS หรือ certificate ไม่ผ่าน (2026): ให้ผู้ดูแลตรวจ TLS และชื่อ host ที่ตรง certificate หรือใช้ SSH tunnel',
    }
    if code in messages:
        return messages[code]
    if isinstance(error, socket.gaierror):
        return 'หาเครื่องฐานจาก host ที่กรอกไม่พบ กรุณาตรวจ IP หรือชื่อเครื่อง JHCIS'
    if isinstance(error, PermissionError):
        return 'ระบบของเครื่องที่รัน Dashboard ไม่อนุญาตการเชื่อมฐานนี้ กรุณาตรวจสิทธิและเส้นทางเชื่อมกับผู้ดูแล'
    return 'อ่าน JHCIS ไม่สำเร็จ: ตรวจการเชื่อม สิทธิ SELECT และโครงสร้างตารางกับผู้ดูแล ไม่มีการแสดงรหัสผ่านหรือข้อความ SQL ใน error'


class RequiredTLSConnection(pymysql.connections.Connection):
    def _request_authentication(self):
        # Older PyMySQL versions can silently downgrade when server SSL is absent.
        if self.ssl and not self.server_capabilities & CLIENT.SSL:
            raise TLSUnavailable(2026, 'TLS required before authentication')
        return super()._request_authentication()


def connect_database(config):
    host = str(config['host']).strip()
    transport = config.get('transport', 'tls')
    if transport not in ('tls', 'local', 'ssh'):
        raise ConnectionSettingsError('เลือกช่องทางเชื่อม JHCIS ที่รองรับ')
    if transport == 'ssh' and host not in ('127.0.0.1', '::1', 'localhost'):
        raise ConnectionSettingsError('โหมด SSH ต้องกรอก host เป็น 127.0.0.1 หรือ localhost พร้อมพอร์ตของ tunnel ที่เปิดไว้แล้ว')
    if transport == 'local':
        addresses = socket.getaddrinfo(host, int(config.get('port', 3306)), type=socket.SOCK_STREAM)
        if not addresses or any(not (ipaddress.ip_address(r[4][0]).is_private or ipaddress.ip_address(r[4][0]).is_loopback) for r in addresses):
            raise ConnectionSettingsError('host ที่กรอกเป็นปลายทางบน Internet จึงใช้โหมดเครื่องนี้/LAN ไม่ได้ กรุณาใช้ IP ภายในของเครื่องฐาน JHCIS หรือเปิด SSH tunnel แล้วเลือกโหมด SSH')
        # Pin the validated resolved address; a second DNS lookup cannot change it.
        host = addresses[0][4][0]
    tls = transport == 'tls'
    return RequiredTLSConnection(host=host, port=int(config.get('port', 3306)),
        user=config['user'], password=config['password'], database=config['database'],
        charset='utf8mb4', connect_timeout=8, read_timeout=20, write_timeout=10,
        autocommit=False, local_infile=False, ssl_disabled=not tls,
        ssl_verify_cert=tls, ssl_verify_identity=tls, ssl_ca=config.get('ssl_ca') if tls else None,
        cursorclass=pymysql.cursors.DictCursor)


def q(identifier):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', identifier):
        raise SchemaMismatch('Unsupported table or column identifier')
    return '`' + identifier + '`'


def discover_schema(cursor, database):
    cursor.execute('SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS '
                   'WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME, ORDINAL_POSITION', (database,))
    schema = {}
    for row in cursor.fetchall():
        schema.setdefault(row['TABLE_NAME'].lower(), {'table': row['TABLE_NAME'], 'columns': {}})['columns'][row['COLUMN_NAME'].lower()] = row['COLUMN_NAME']
    return schema


def plan_schema(schema):
    """A conservative common-schema adapter: absence => reject, never guess a join."""
    required = {'person': ['pcucodeperson', 'pid', 'idcard', 'fname', 'lname', 'sex', 'birth'],
                'visit': ['pcucode', 'pcucodeperson', 'pid', 'visitno', 'visitdate'],
                'visitdiag': ['pcucode', 'visitno', 'diagcode'],
                'visitdrug': ['pcucode', 'visitno', 'drugcode']}
    missing = []
    for table, fields in required.items():
        missing.extend(table + '.' + field for field in fields if table not in schema or field not in schema[table]['columns'])
    if missing:
        raise SchemaMismatch('โครงสร้างไม่ตรงตัวอ่านมาตรฐาน: ' + ', '.join(missing))
    return schema


def read_standard(config, facility, start, end, max_rows=50000, pid_filter="", telemed_only=False):
    if not isinstance(start, date) or not isinstance(end, date) or start > end or (end - start).days > 366:
        raise ConnectionSettingsError('วันที่เริ่มต้องไม่หลังวันสิ้นสุด และช่วงวันที่ต้องไม่เกิน 366 วัน')
    cap = min(max(int(max_rows), 1), 100000)
    connection = connect_database(config)
    try:
        with connection.cursor() as cursor:
            cursor.execute('START TRANSACTION READ ONLY')
            schema = plan_schema(discover_schema(cursor, config['database']))
            def table(key):
                return q(schema[key]['table'])
            def col(key, name, alias):
                return alias + '.' + q(schema[key]['columns'][name])
            v = lambda name: col('visit', name, 'v')
            p = lambda name: col('person', name, 'p')
            # Same-person composite join: visit.pcucodeperson is not visit.pcucode.
            base = f' FROM {table("visit")} v INNER JOIN {table("person")} p ON {v("pcucodeperson")} = {p("pcucodeperson")} AND {v("pid")} = {p("pid")}'
            where = f' WHERE {v("pcucode")} = %s AND {v("visitdate")} >= %s AND {v("visitdate")} < DATE_ADD(%s, INTERVAL 1 DAY)'
            params = (facility, start.isoformat(), end.isoformat())
            if str(pid_filter).strip():
                where += f' AND {p("idcard")} = %s'
                params += (str(pid_filter).strip(),)
            params += (cap + 1,)
            nation = next((name for name in ('nation', 'nationality') if name in schema['person']['columns']), None)
            nationality = p(nation) if nation else 'NULL'
            select = (f'SELECT {v("pcucode")} AS facility, {v("visitno")} AS visit_id, {p("idcard")} AS pid, '
                      f'CONCAT_WS(" ", {p("fname")}, {p("lname")}) AS patient_name, {v("visitdate")} AS service_date, '
                      f'{p("sex")} AS sex, {p("birth")} AS birth_date, {nationality} AS nationality')
            cursor.execute(select + base + where + ' LIMIT %s', params)
            visits = pd.DataFrame(cursor.fetchall(), columns=VIEW_COLUMNS[:8])
            if len(visits) > cap:
                raise ConnectionSettingsError('จำนวน visit เกินขีดจำกัด กรุณาลดช่วงวันที่แล้วอ่านใหม่')
            # Refuse collisions rather than attach another patient's drugs to a visit.
            if visits.duplicated(['facility', 'visit_id'], keep=False).any():
                raise SchemaMismatch('พบ visit ซ้ำจากการ join คนไข้ จึงยังไม่ใช้ผลชุดนี้')
            for key, field, alias, target in [('visitdiag', 'diagcode', 'd', 'icd10'), ('visitdrug', 'drugcode', 'd', 'drugcode')]:
                child = lambda name: col(key, name, alias)
                query = f'SELECT {v("pcucode")} AS facility, {v("visitno")} AS visit_id, {child(field)} AS code FROM {table("visit")} v INNER JOIN {table(key)} {alias} ON {v("pcucode")} = {child("pcucode")} AND {v("visitno")} = {child("visitno")}'
                cursor.execute(query + where + ' LIMIT %s', (facility, start.isoformat(), end.isoformat(), cap * 20 + 1))
                codes = cursor.fetchall()
                if len(codes) > cap * 20:
                    raise ConnectionSettingsError('จำนวนรหัสวินิจฉัย/ยาเกินขีดจำกัด กรุณาลดช่วงวันที่แล้วอ่านใหม่')
                lookup = {}
                for row in codes:
                    key_pair = (str(row['facility']), str(row['visit_id']))
                    if row['code'] is not None:
                        lookup.setdefault(key_pair, set()).add(str(row['code']))
                visits[target] = ['|'.join(sorted(lookup.get((str(row.facility), str(row.visit_id)), set()))) for row in visits.itertuples()]
        if telemed_only:
            diag_ok = visits["icd10"].fillna("").astype(str).str.upper().str.replace(".", "", regex=False).str.contains("Z719")
            drug_ok = visits["drugcode"].fillna("").astype(str).str.upper().str.contains("TELMED")
            visits = visits.loc[diag_ok & drug_ok].reset_index(drop=True)
        return prepare_evidence(visits, facility)[VIEW_COLUMNS].reset_index(drop=True)
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()
