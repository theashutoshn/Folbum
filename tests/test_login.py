import http.client
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ['DATA_DIR'] = str(Path(__file__).parent)
from app import server
REAL_WRITE_JSON = server.write_json


class LoginFlowTests(unittest.TestCase):
    def setUp(self):
        self.account_path = Path(__file__).parent / 'test_account.json'
        self.account_path.unlink(missing_ok=True)
        REAL_WRITE_JSON(self.account_path, {'username': 'admin',
            'password_hash': server.password_hash('test-password')})
        self.sessions = {}
        real_read = server.read_json

        def read_json(path, default):
            return self.sessions.copy() if path == server.SESSIONS else real_read(path, default)

        def write_json(path, data):
            if path == server.ACCOUNT:
                return REAL_WRITE_JSON(path, data)
            if path != server.SESSIONS:
                raise AssertionError('Unexpected file write during login test')
            self.sessions = data.copy()

        self.patches = [
            patch.object(server, 'ACCOUNT', self.account_path),
            patch.object(server, 'read_json', side_effect=read_json),
            patch.object(server, 'write_json', side_effect=write_json),
        ]
        for item in self.patches:
            item.start()
        server.LOGIN_FAILURES.clear()
        self.httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.client = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port)
        self.origin = 'http://127.0.0.1:' + str(self.httpd.server_port)

    def tearDown(self):
        self.client.close()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        for item in reversed(self.patches):
            item.stop()
        self.account_path.unlink(missing_ok=True)

    def request(self, method, path, body=None, cookie=None, forwarded_proto=None):
        headers = {'Origin': self.origin} if method == 'POST' else {}
        if forwarded_proto:
            headers['X-Forwarded-Proto'] = forwarded_proto
        if cookie:
            headers['Cookie'] = cookie
        if body is not None:
            headers['Content-Type'] = 'application/json'
            body = json.dumps(body)
        self.client.request(method, path, body=body, headers=headers)
        response = self.client.getresponse()
        content = response.read()
        return response, content

    def test_login_redirect_and_logout_without_basic_auth_challenge(self):
        response, content = self.request('GET', '/login')
        self.assertEqual(response.status, 200)
        self.assertIn(b'<form id="loginForm"', content)
        self.assertIn(b'/folbum-logo.png', content)

        response, content = self.request('GET', '/login.js?v=0.0.4')
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader('Content-Type'), 'application/javascript; charset=utf-8')
        self.assertIn(b'checkSetup();', content)

        response, content = self.request('GET', '/folbum-logo.png')
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader('Content-Type'), 'image/png')
        self.assertTrue(content.startswith(b'\x89PNG\r\n\x1a\n'))

        response, _ = self.request('GET', '/app')
        self.assertEqual((response.status, response.getheader('Location')), (303, '/login'))
        self.assertIsNone(response.getheader('WWW-Authenticate'))

        response, _ = self.request('GET', '/api/status')
        self.assertEqual(response.status, 401)
        self.assertIsNone(response.getheader('WWW-Authenticate'))

        response, _ = self.request('POST', '/api/login', {'username': 'admin', 'password': 'wrong'})
        self.assertEqual(response.status, 401)
        self.assertIsNone(response.getheader('Set-Cookie'))

        response, _ = self.request('POST', '/api/login', {'username': 'admin', 'password': 'test-password'})
        self.assertEqual(response.status, 200)
        cookie = response.getheader('Set-Cookie')
        self.assertTrue(cookie.startswith('folbum_session='))
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Strict', cookie)
        self.assertIn('Max-Age=43200', cookie)
        self.assertNotIn('; Secure', cookie)
        session = cookie.split(';', 1)[0]

        response, content = self.request('GET', '/app', cookie=session)
        self.assertEqual(response.status, 200)
        self.assertIn(b'Folbum', content)

        response, content = self.request('GET', '/api/status', cookie=session)
        self.assertEqual(response.status, 200)
        self.assertFalse(json.loads(content)['connected'])
        self.assertNotIn('mode', json.loads(content))

        response, content = self.request('GET', '/api/sources', cookie=session)
        self.assertEqual(response.status, 400)
        self.assertIn(b'Connect to ZimaOS Photos first', content)

        response, content = self.request('POST', '/api/sync', {'confirm': 'SYNC'}, cookie=session)
        self.assertEqual(response.status, 400)
        self.assertIn(b'Connect to ZimaOS Photos first', content)

        response, _ = self.request('GET', '/login', cookie=session)
        self.assertEqual((response.status, response.getheader('Location')), (303, '/app'))

        response, _ = self.request('POST', '/api/logout', cookie=session)
        self.assertEqual(response.status, 200)
        self.assertIn('Max-Age=0', response.getheader('Set-Cookie'))

        response, _ = self.request('GET', '/app', cookie=session)
        self.assertEqual((response.status, response.getheader('Location')), (303, '/login'))

    def test_https_proxy_sets_secure_session_cookie(self):
        response, _ = self.request('POST', '/api/login',
            {'username': 'admin', 'password': 'test-password'}, forwarded_proto='https')
        self.assertEqual(response.status, 200)
        cookie = response.getheader('Set-Cookie')
        self.assertIn('; Secure', cookie)
        session = cookie.split(';', 1)[0]
        response, _ = self.request('POST', '/api/logout', cookie=session,
            forwarded_proto='https')
        self.assertEqual(response.status, 200)
        self.assertIn('; Secure', response.getheader('Set-Cookie'))

    def test_remembered_login_survives_refresh_and_has_longer_expiry(self):
        response, _ = self.request('POST', '/api/login', {
            'username': 'admin', 'password': 'test-password', 'remember': True})
        self.assertEqual(response.status, 200)
        cookie = response.getheader('Set-Cookie')
        self.assertIn('Max-Age=2592000', cookie)
        session = cookie.split(';', 1)[0]
        for _ in range(2):
            response, _ = self.request('GET', '/app', cookie=session)
            self.assertEqual(response.status, 200)

    def test_first_run_setup_needs_no_code_and_stores_only_password_hash(self):
        self.account_path.unlink()
        response, content = self.request('GET', '/api/setup/status')
        self.assertEqual((response.status, json.loads(content)['required']), (200, True))
        response, _ = self.request('POST', '/api/setup', {
            'username': 'owner', 'password': 'short'})
        self.assertEqual(response.status, 400)
        response, _ = self.request('POST', '/api/setup', {
            'username': 'owner', 'password': 'a-new-strong-password'})
        self.assertEqual(response.status, 200)
        saved = self.account_path.read_text()
        self.assertNotIn('a-new-strong-password', saved)
        self.assertIn('pbkdf2_sha256', saved)
        response, content = self.request('GET', '/api/setup/status')
        self.assertEqual((response.status, json.loads(content)['required']), (200, False))
        response, _ = self.request('POST', '/api/login', {
            'username': 'owner', 'password': 'a-new-strong-password'})
        self.assertEqual(response.status, 200)
        response, _ = self.request('POST', '/api/setup', {
            'username': 'attacker', 'password': 'another-strong-password'})
        self.assertEqual(response.status, 400)

    def test_change_password_rejects_wrong_current_and_invalidates_sessions(self):
        response, _ = self.request('POST', '/api/account/password', {
            'current_password': 'test-password', 'new_password': 'a-new-strong-password'})
        self.assertEqual(response.status, 401)
        response, _ = self.request('POST', '/api/login', {
            'username': 'admin', 'password': 'test-password'})
        session = response.getheader('Set-Cookie').split(';', 1)[0]
        response, _ = self.request('POST', '/api/account/password', {
            'current_password': 'wrong', 'new_password': 'a-new-strong-password'}, cookie=session)
        self.assertEqual(response.status, 400)
        response, _ = self.request('POST', '/api/account/password', {
            'current_password': 'test-password', 'new_password': 'a-new-strong-password'}, cookie=session)
        self.assertEqual(response.status, 200)
        self.assertIn('Max-Age=0', response.getheader('Set-Cookie'))
        response, _ = self.request('GET', '/app', cookie=session)
        self.assertEqual((response.status, response.getheader('Location')), (303, '/login'))
        response, _ = self.request('POST', '/api/login', {
            'username': 'admin', 'password': 'test-password'})
        self.assertEqual(response.status, 401)
        response, _ = self.request('POST', '/api/login', {
            'username': 'admin', 'password': 'a-new-strong-password'})
        self.assertEqual(response.status, 200)

    def test_manual_nas_address_and_name_are_saved_after_authentication(self):
        class Probe:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        writes = []
        tokens = {'access_token': 'access', 'refresh_token': 'refresh', 'expires_at': 9999999999}
        with patch.object(server.PhotosClient, 'login', return_value=tokens) as login, \
             patch('urllib.request.urlopen', return_value=Probe()) as probe, \
             patch.object(server, 'write_json', side_effect=lambda path, data: writes.append((path, data))):
            result = server.connect({'url': '192.168.1.10', 'name': 'Living Room NAS',
                                     'username': 'nas-user', 'password': 'nas-pass'})

        self.assertEqual(result['url'], 'http://192.168.1.10')
        self.assertEqual(result['name'], 'Living Room NAS')
        self.assertEqual(login.call_args.args[0], 'http://192.168.1.10')
        self.assertEqual(probe.call_args.args[0].full_url, 'http://192.168.1.10/v2/photos/sources')
        self.assertIn((server.CONNECTION, {'url': 'http://192.168.1.10', 'name': 'Living Room NAS',
                                           'state_namespace': True, 'active': True}), writes)
        self.assertTrue(result['remember_connection'])

    def test_saved_nas_is_not_overridden_by_environment(self):
        stored = lambda path, default: {'url': 'http://old-nas', 'name': 'Old NAS'} if path == server.CONNECTION else default
        credentials = SimpleNamespace(is_file=lambda: True)
        with patch.object(server, 'CREDENTIALS', credentials), \
             patch.object(server, 'read_json', side_effect=stored):
            info = server.connection_info()
        self.assertEqual(info, {'url': 'http://old-nas', 'name': 'Old NAS',
                                'active': True, 'connected': True, 'remember_connection': True})

    def test_album_mappings_are_separate_for_each_nas(self):
        saved = {'url': 'http://first-nas', 'state_namespace': True}
        read = lambda path, default: saved if path == server.CONNECTION else default
        with patch.object(server, 'TEMP_CONNECTION', None), \
             patch.object(server, 'read_json', side_effect=read):
            first = server.mapping_key('/media/Gallery', 'Trips')
            saved = {'url': 'http://second-nas', 'state_namespace': True}
            second = server.mapping_key('/media/Gallery', 'Trips')
        self.assertNotEqual(first, second)

    def test_remembered_nas_connection_survives_page_reload_and_process_state_reset(self):
        class Probe:
            status = 200

            def __enter__(self): return self
            def __exit__(self, *args): return False

        tokens = {'access_token': 'access', 'refresh_token': 'refresh', 'expires_at': 9999999999}
        directory = Path(__file__).parent
        credentials = directory / 'test_persist_credentials.json'
        connection = directory / 'test_persist_connection.json'
        credentials.unlink(missing_ok=True)
        connection.unlink(missing_ok=True)
        try:
          with patch.object(server, 'CREDENTIALS', credentials), \
             patch.object(server, 'CONNECTION', connection), \
             patch.object(server, 'TEMP_CONNECTION', None), \
             patch.object(server.PhotosClient, 'login', return_value=tokens), \
             patch.object(server, 'write_json', side_effect=REAL_WRITE_JSON), \
             patch('urllib.request.urlopen', return_value=Probe()):
            server.connect({'url': 'http://fixed-nas', 'username': 'nas-user', 'password': 'nas-pass',
                            'remember_connection': True})
            self.assertTrue(server.connection_info()['connected'])
            self.assertTrue(server.connection_info()['remember_connection'])
            self.assertEqual(server.get_client().tokens['refresh_token'], 'refresh')
            # Reloading the app module would lose globals, but these files remain.
            with patch.object(server, 'TEMP_CONNECTION', None):
                self.assertTrue(server.connection_info()['connected'])
                self.assertEqual(server.get_client().tokens['access_token'], 'access')
        finally:
            credentials.unlink(missing_ok=True)
            connection.unlink(missing_ok=True)

    def test_nonremembered_nas_connection_does_not_use_persistent_files(self):
        class Probe:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False

        tokens = {'access_token': 'access', 'refresh_token': 'refresh', 'expires_at': 9999999999}
        volatile = Path(__file__).parent / 'test_volatile_credentials.json'
        volatile.unlink(missing_ok=True)
        try:
            with patch.object(server, 'CREDENTIALS', Path(__file__).parent / 'unused_persist_credentials.json'), \
                 patch.object(server, 'CONNECTION', Path(__file__).parent / 'unused_persist_connection.json'), \
                 patch.object(server, 'TEMP_CREDENTIALS', volatile), \
                 patch.object(server, 'TEMP_CONNECTION', None), \
                 patch.object(server.PhotosClient, 'login', return_value=tokens), \
                 patch.object(server, 'write_json', side_effect=REAL_WRITE_JSON), \
                 patch('urllib.request.urlopen', return_value=Probe()):
                result = server.connect({'url': 'http://fixed-nas', 'username': 'nas-user', 'password': 'nas-pass',
                                         'remember_connection': False})
                self.assertFalse(result['remember_connection'])
                self.assertTrue(server.connection_info()['connected'])
                self.assertFalse(server.connection_info()['remember_connection'])
                self.assertEqual(server.get_client().tokens['access_token'], 'access')
        finally:
            volatile.unlink(missing_ok=True)

    def test_disconnect_reconnect_and_delete_saved_nas(self):
        directory = Path(__file__).parent
        credentials = directory / 'test_controls_credentials.json'
        connection = directory / 'test_controls_connection.json'
        configuration = directory / 'test_controls_config.json'
        volatile = directory / 'test_controls_volatile.json'
        paths = (credentials, connection, configuration, volatile)
        for path in paths: path.unlink(missing_ok=True)
        try:
            REAL_WRITE_JSON(credentials, {'access_token': 'access', 'refresh_token': 'refresh',
                                          'expires_at': 9999999999})
            REAL_WRITE_JSON(connection, {'url': 'http://nas', 'name': 'My NAS',
                                         'state_namespace': True, 'active': True})
            REAL_WRITE_JSON(configuration, {'root': '/media/Gallery', 'interval_minutes': 30})
            with patch.object(server, 'CREDENTIALS', credentials), \
                 patch.object(server, 'CONNECTION', connection), \
                 patch.object(server, 'CONFIG', configuration), \
                 patch.object(server, 'TEMP_CREDENTIALS', volatile), \
                 patch.object(server, 'TEMP_CONNECTION', None), \
                 patch.object(server, 'TEMP_ACTIVE', False), \
                 patch.object(server, 'write_json', side_effect=REAL_WRITE_JSON), \
                 patch.object(server.PhotosClient, 'sources', return_value=[]) as sources:
                server.disconnect_connection()
                self.assertFalse(server.connection_info()['connected'])
                self.assertFalse(server.connection_info()['active'])
                self.assertTrue(credentials.is_file())
                server.reconnect_connection()
                sources.assert_called_once()
                self.assertTrue(server.connection_info()['connected'])
                server.disconnect_connection()
                with patch.object(server.PhotosClient, 'sources', side_effect=server.IntegrationError('offline')):
                    with self.assertRaises(server.IntegrationError):
                        server.reconnect_connection()
                self.assertFalse(server.connection_info()['active'])
                server.delete_connection()
                self.assertFalse(credentials.exists())
                self.assertFalse(connection.exists())
                self.assertEqual(server.config(), {'root': '', 'interval_minutes': 0})
        finally:
            for path in paths: path.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
